"""The three expected-return estimators, and the log premium conversion."""

from __future__ import annotations

import math
from datetime import date

import pytest

from merton_share.expected_return import (
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
    e = building_block_estimate(0.0263, 0.0251)
    assert e.value == pytest.approx(0.0514)
    assert "no repricing" in e.detail


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
