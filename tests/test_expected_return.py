"""The three expected-return estimators, and the log premium conversion."""

from __future__ import annotations

import math
from datetime import date

import pytest

from your_equity_share.expected_return import (
    arithmetic_from_compound,
    compound_from_arithmetic,
    CHOI_FITTED_LOG_PREMIUM_RANGE,
    building_block_estimate,
    consensus,
    implied_premium_estimate,
    log_premium,
    real_total_return_index,
    spread,
    valuation_regression_estimate,
    within_fitted_range,
)


def test_log_premium_is_not_the_arithmetic_premium() -> None:
    """The distinction that decides whether an input is inside Choi's range."""
    mu, rf, sigma = 0.0707, 0.0298, 0.185
    arithmetic = mu - rf
    log = log_premium(mu, rf, sigma)
    assert arithmetic == pytest.approx(0.0409, abs=1e-4)
    assert log == pytest.approx(0.0218, abs=1e-4)
    assert arithmetic - log > 0.015


def test_fitted_range_check() -> None:
    low, high = CHOI_FITTED_LOG_PREMIUM_RANGE
    assert (low, high) == (0.02, 0.04)
    assert within_fitted_range(0.0707, 0.0298)
    # Choi's own guide defaults fall below the range his model was fitted over
    assert not within_fitted_range(0.05, 0.025)


def test_implied_premium_adds_the_real_rate() -> None:
    e = implied_premium_estimate(0.0409, 0.0298, date(2026, 9, 1))
    assert e.value == pytest.approx(0.0707)
    assert "Damodaran" in e.detail


def test_building_blocks_sum_their_parts() -> None:
    e = building_block_estimate(0.0110, 0.0229)
    assert e.value == pytest.approx(0.0339)
    assert "no repricing" in e.detail
    assert "dividend yield" in e.detail


def _holder_return(shares, price, earnings, dividends, buyback):
    """What one share actually earns over a year, by construction.

    Aggregate earnings are held flat in real terms, the multiple is held
    constant, and the buyback is executed at the going price. No formula is
    used, so this is something the formulas can be checked against.
    """
    retired = buyback / price
    after = shares - retired
    eps_before, eps_after = earnings / shares, earnings / after
    multiple = price / eps_before
    price_after = multiple * eps_after
    income = dividends / shares
    return (price_after + income) / price - 1.0, eps_after / eps_before - 1.0


def test_dividend_yield_pairs_with_per_share_growth() -> None:
    """The pairing is the whole point, and the wrong one is plausible."""
    shares, price, earnings, dividends, buyback = 100.0, 15.0, 100.0, 30.0, 20.0
    truth, growth = _holder_return(shares, price, earnings, dividends, buyback)
    cap = shares * price
    dividend_yield = dividends / cap
    payout_yield = (dividends + buyback) / cap

    right = building_block_estimate(dividend_yield, growth)
    assert right.value == pytest.approx(truth, abs=1e-12)

    # Aggregate earnings are flat, so the other consistent pairing is the
    # payout yield with no growth. Same answer up to the timing of the buyback.
    assert payout_yield == pytest.approx(truth, abs=2e-4)

    # And the pairing that was in use here until it was measured.
    wrong = building_block_estimate(payout_yield, growth)
    assert wrong.value - truth == pytest.approx(buyback / cap, abs=2e-4)
    assert wrong.value > truth


def test_double_count_moves_the_answer_by_double_digits() -> None:
    """Not a rounding difference. Recorded so the size is not forgotten.

    Twelve points of total wealth, and a household whose human capital is a
    little over half its total wealth sees roughly twice that in its financial
    portfolio, because the multiplier scales the Merton share up.
    """
    from your_equity_share.expected_return import arithmetic_from_compound
    from your_equity_share.allocation import merton_share

    vol, real_rf, gamma = 0.171808, 0.0296, 4.0
    right = arithmetic_from_compound(0.0110 + 0.0229, vol)
    wrong = arithmetic_from_compound(0.0110 + 0.0153 + 0.0229, vol)
    gap = merton_share(wrong, real_rf, gamma, vol) - merton_share(
        right, real_rf, gamma, vol
    )
    assert 0.10 < gap < 0.15


def test_repricing_enters_with_its_sign() -> None:
    lower = building_block_estimate(0.0263, 0.0251, repricing=-0.01)
    assert lower.value == pytest.approx(0.0414)


def test_total_return_index_beats_price_alone() -> None:
    """Dividends are the larger part of the long-run real return."""
    prices = [100.0] * 121           # flat prices
    dividends = [4.0] * 121          # 4% a year, paid monthly
    index = real_total_return_index(prices, dividends)
    assert index[-1] > 1.4           # ten years of reinvested income
    assert index[0] == 1.0


def test_total_return_index_rejects_mismatched_input() -> None:
    with pytest.raises(ValueError, match="same length"):
        real_total_return_index([1.0, 2.0], [1.0])


def _synthetic(n_months: int = 1800):
    """A history where cheap valuations really do precede better returns."""
    cape, prices, dividends = [], [], []
    price = 100.0
    for i in range(n_months):
        ratio = 15.0 + 10.0 * math.sin(i / 90.0)
        cape.append(ratio)
        price *= 1.0 + (0.10 / ratio) / 12.0
        prices.append(price)
        dividends.append(price * 0.03)
    return cape, real_total_return_index(prices, dividends)


def test_regression_finds_a_positive_slope_when_one_exists() -> None:
    cape, index = _synthetic()
    e = valuation_regression_estimate(cape, index, current_cape=20.0, horizon_years=10)
    assert "slope" in e.detail
    assert e.value > 0


def test_regression_predicts_more_from_a_cheaper_market() -> None:
    cape, index = _synthetic()
    cheap = valuation_regression_estimate(cape, index, 10.0, horizon_years=10).value
    dear = valuation_regression_estimate(cape, index, 40.0, horizon_years=10).value
    assert cheap > dear


def test_regression_reports_independent_windows_not_overlapping_ones() -> None:
    """Overlap makes the naive count wildly overstate the information."""
    cape, index = _synthetic()
    e = valuation_regression_estimate(cape, index, 20.0, horizon_years=30)
    assert e.observations > 1000
    assert e.independent_observations <= 5
    assert e.standard_error is not None


def test_regression_needs_more_history_than_the_horizon() -> None:
    cape, index = _synthetic(200)
    with pytest.raises(ValueError, match="need more than"):
        valuation_regression_estimate(cape, index, 20.0, horizon_years=30)


def test_regression_rejects_a_non_positive_valuation() -> None:
    cape, index = _synthetic()
    with pytest.raises(ValueError, match="must be positive"):
        valuation_regression_estimate(cape, index, 0.0, horizon_years=10)


def test_consensus_is_the_median_so_one_outlier_cannot_drive_it() -> None:
    e = [
        implied_premium_estimate(0.0409, 0.0298),
        building_block_estimate(0.0263, 0.0251),
        building_block_estimate(0.0263, 0.0254),
    ]
    assert consensus(e) == pytest.approx(0.0514, abs=1e-3)
    assert consensus(e) < e[0].value


def test_spread_reports_the_disagreement() -> None:
    e = [
        implied_premium_estimate(0.0409, 0.0298),
        building_block_estimate(0.0263, 0.0251),
    ]
    assert spread(e) == pytest.approx(0.0707 - 0.0514, abs=1e-3)


def test_combining_nothing_is_an_error() -> None:
    with pytest.raises(ValueError, match="no estimates"):
        consensus([])


# --- compound versus arithmetic ---------------------------------------------


def test_arithmetic_exceeds_compound_by_roughly_half_the_variance() -> None:
    """The volatility drag. Not a rounding difference."""
    compound, sigma = 0.0517, 0.1719
    arithmetic = arithmetic_from_compound(compound, sigma)
    assert arithmetic > compound
    assert arithmetic - compound == pytest.approx(0.5 * sigma**2, abs=0.001)


def test_conversion_round_trips() -> None:
    for compound in (0.02, 0.0517, 0.09):
        for sigma in (0.10, 0.1719, 0.30):
            back = compound_from_arithmetic(
                arithmetic_from_compound(compound, sigma), sigma
            )
            assert back == pytest.approx(compound)


def test_zero_volatility_leaves_the_return_alone() -> None:
    assert arithmetic_from_compound(0.05, 0.0) == pytest.approx(0.05)


def test_estimates_are_compound_by_default() -> None:
    """Every estimator here produces a compound return, so the flag must say so."""
    for estimate in (
        implied_premium_estimate(0.0409, 0.0298),
        building_block_estimate(0.0263, 0.0251),
    ):
        assert estimate.basis == "compound"


def test_as_arithmetic_converts_once_and_marks_it() -> None:
    original = building_block_estimate(0.0263, 0.0251)
    converted = original.as_arithmetic(0.1719)
    assert converted.basis == "arithmetic"
    assert converted.value > original.value
    assert converted.method == original.method
    # converting again is a no-op, not a second conversion
    assert converted.as_arithmetic(0.1719).value == pytest.approx(converted.value)


def test_the_conversion_decides_whether_we_are_in_choi_range() -> None:
    """The bug this guards: feeding a compound figure into an arithmetic slot."""
    compound, rf, sigma = 0.0517, 0.0298, 0.1719
    arithmetic = arithmetic_from_compound(compound, sigma)
    assert log_premium(compound, rf) == pytest.approx(0.0039, abs=5e-4)
    assert log_premium(arithmetic, rf) == pytest.approx(0.0187, abs=5e-4)
    # the correction is worth more than a percentage point of log premium
    assert log_premium(arithmetic, rf) - log_premium(compound, rf) > 0.013
