"""What a mutation sweep found nothing was holding.

Every test here exists because the model could be broken in that exact way
while 534 tests, the golden fixture, the workbook checks and the verifier all
passed. They are not hypothetical: each was produced by making the change and
watching the suite stay green.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share import statistics as stats  # noqa: E402
from your_equity_share.providers import ShillerHistory  # noqa: E402


def test_volatility_is_annualised_by_the_conventional_trading_year() -> None:
    """252 could be set to 200 and nothing failed.

    Volatility enters the recommendation squared, so a fifth off the
    annualisation is worth about half the equity share. The number is a
    convention rather than a measurement, which is exactly why it needs
    pinning: nothing about the data would object.
    """
    assert stats.TRADING_DAYS_PER_YEAR == 252


def test_annualising_scales_by_the_square_root_of_the_period_count() -> None:
    """The other half of the same constant: that it enters under a square root.

    A series with a known daily standard deviation must come back as that
    figure times sqrt(252), and doubling the period count must multiply the
    answer by sqrt(2), not by 2.
    """
    daily = [0.01, -0.01] * 500
    one = stats.annualised_volatility(daily, periods_per_year=252)
    two = stats.annualised_volatility(daily, periods_per_year=504)
    assert two / one == pytest.approx(math.sqrt(2.0), rel=1e-12)


def test_the_dividend_yield_is_the_latest_month_not_an_earlier_one() -> None:
    """Taking both from the month before survived every check.

    That the two come from the same month is already pinned. That the month is
    the most recent one was not, and a yield computed from stale prices is the
    quietest possible way to be wrong: it stays plausible.
    """
    history = ShillerHistory(
        dates=("2026.04", "2026.05", "2026.06"),
        real_prices=(100.0, 200.0, 400.0),
        real_dividends=(4.0, 4.0, 4.0),
        real_earnings=(10.0, 10.0, 10.0),
        cape=(20.0, 20.0, 20.0),
    )
    # 4 / 400, the last month. Any earlier month gives 2% or 4%.
    assert history.dividend_yield == pytest.approx(0.01)


def test_the_yield_uses_one_month_for_both_halves() -> None:
    """A dividend from one month over a price from another is not a yield."""
    history = ShillerHistory(
        dates=("2026.05", "2026.06"),
        real_prices=(100.0, 400.0),
        real_dividends=(8.0, 4.0),
        real_earnings=(10.0, 10.0),
        cape=(20.0, 20.0),
    )
    assert history.dividend_yield == pytest.approx(0.01)
