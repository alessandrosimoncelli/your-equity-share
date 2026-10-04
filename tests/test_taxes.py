"""Italian tax, and the check that justifies leaving it out of the model.

The model reads the figures before tax (taxes.py says why). These tests pin the
legal rates and the properties of tools/tax_check.py that the argument rests
on, so a change that broke the argument would fail here rather than in a
reader's head.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import tax_check  # noqa: E402
from your_equity_share.allocation import merton_share  # noqa: E402
from your_equity_share.market_data import load_market_data  # noqa: E402
from your_equity_share.taxes import ITALY_TAX, NO_TAX, TaxRegime  # noqa: E402


def test_the_rates_are_the_ones_italian_law_sets() -> None:
    """12.5% on government bonds, 26% on everything else, 0.2% of bollo."""
    assert ITALY_TAX.government_bond_rate == 0.125
    assert ITALY_TAX.other_financial_income_rate == 0.26
    assert ITALY_TAX.wealth_tax_rate == 0.002


def test_a_rate_outside_zero_to_one_is_refused() -> None:
    """A rate of 26 rather than 0.26 would quietly invert every answer."""
    with pytest.raises(ValueError):
        TaxRegime(26.0, 0.26, 0.002, "wrong")
    with pytest.raises(ValueError):
        TaxRegime(0.125, -0.1, 0.002, "wrong")


def test_the_check_reproduces_merton_without_tax() -> None:
    """The control: with no tax, the best share held to a date is Merton's.

    Not exactly, because a single date is a discrete problem and Merton's is a
    continuous one, but within about two points at every horizon (2.1 at
    thirty years on the snapshot).
    """
    m = load_market_data(tax_check.SNAPSHOT)
    merton = merton_share(m.expected_stock_real_return, m.real_risk_free_rate,
                          5.0, m.stock_volatility)
    for years in tax_check.YEARS:
        assert tax_check.best_weight(years, 5.0, NO_TAX) == pytest.approx(merton, abs=0.025)


@pytest.mark.parametrize("years", tax_check.YEARS)
def test_tax_lowers_the_share_less_than_taxing_the_mean_alone(years) -> None:
    """The heart of section 8: the law lowers the best share, and taking tax
    off the expected return only lowers it more, about twice as much or more
    once the money stays invested seven years."""
    law = tax_check.law_ratio(years)
    mean_only = tax_check.mean_only_ratio(years)
    assert mean_only < law < 1.0
    if years >= 7:
        assert (1.0 - mean_only) > 2.0 * (1.0 - law)


def test_ignoring_tax_costs_little() -> None:
    """Under two basis points a year at three years, much less beyond."""
    costs = [tax_check.cost_of_ignoring(years) for years in tax_check.YEARS]
    assert all(0.0 <= c < 2.0 for c in costs)
    assert costs[0] > costs[1] > costs[2]


def test_a_long_held_fund_is_rarely_sold_at_a_loss() -> None:
    """Why the missing loss credit matters little: the upside is nearly all
    there is once the money stays invested (a loss in about one sale in five
    at seven years, one in thirty at thirty)."""
    chances = [tax_check.loss_probability(years) for years in tax_check.YEARS]
    assert all(a > b for a, b in zip(chances, chances[1:]))
    assert chances[-1] < 0.05
