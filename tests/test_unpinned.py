"""What a mutation sweep found nothing was holding.

Every test here exists because the model could be broken in that exact way
while 534 tests, the golden fixture, the workbook checks and the verifier all
passed. They are not hypothetical: each was produced by making the change and
watching the suite stay green.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.providers import ShillerHistory  # noqa: E402


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
