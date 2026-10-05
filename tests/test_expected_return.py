"""The expected-return estimator, and the log premium conversion."""

from __future__ import annotations

import pytest

from your_equity_share.expected_return import (
    arithmetic_from_compound,
    compound_from_arithmetic,
    CHOI_FITTED_LOG_PREMIUM_RANGE,
    building_block_estimate,
    log_premium,
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
    # The guide's 5% default, with the 2.5% TIPS yield it cites, falls below the
    # range his model was fitted over
    assert not within_fitted_range(0.05, 0.025)


def test_building_blocks_compound_their_parts() -> None:
    """A trailing yield and growth, compounded: 1 + R = (1 + D0/P0)(1 + g)."""
    e = building_block_estimate(0.0110, 0.0229)
    assert e.value == pytest.approx(1.0110 * 1.0229 - 1)
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

    # The example pays its dividend over the year it measures, a forward
    # yield; the estimator takes a trailing one, last year's dividend, which
    # is the same dividend before a year of growth. Given that, compounding
    # recovers the holder's return exactly.
    right = building_block_estimate(dividend_yield / (1 + growth), growth)
    assert right.value == pytest.approx(truth, abs=1e-12)

    # Aggregate earnings are flat, so the other consistent pairing is the
    # payout yield with no growth. Same answer up to the timing of the buyback.
    assert payout_yield == pytest.approx(truth, abs=2e-4)

    # And the pairing that was in use here until it was measured.
    wrong = building_block_estimate(payout_yield / (1 + growth), growth)
    assert wrong.value - truth == pytest.approx(buyback / cap, abs=1e-12)
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
    assert lower.value == pytest.approx(1.0263 * 1.0251 * 0.99 - 1)
    assert lower.value < building_block_estimate(0.0263, 0.0251).value


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


def test_the_conversion_decides_whether_we_are_in_choi_range() -> None:
    """The bug this guards: feeding a compound figure into an arithmetic slot."""
    compound, rf, sigma = 0.0517, 0.0298, 0.1719
    arithmetic = arithmetic_from_compound(compound, sigma)
    assert log_premium(compound, rf) == pytest.approx(0.0039, abs=5e-4)
    assert log_premium(arithmetic, rf) == pytest.approx(0.0187, abs=5e-4)
    # the correction is worth more than a percentage point of log premium
    assert log_premium(arithmetic, rf) - log_premium(compound, rf) > 0.013


