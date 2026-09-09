"""The Italian tax code, and the four ways this arithmetic could be wrong.

Taxes are easy to get subtly wrong in a direction nobody notices, so these
tests pin the properties rather than the numbers wherever they can. Where they
do pin a number it is worked by hand in the docstring, so a reader can check
the test rather than trusting it.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.taxes import (  # noqa: E402
    ITALY_TAX,
    NO_TAX,
    TaxRegime,
    after_tax_equity_compound,
    after_tax_safe_rate,
)

INFLATION = 0.020369
NOMINAL_YIELD = 0.037842
EQUITY = 0.042


# --- the rates themselves ---------------------------------------------------

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


# --- the null case ----------------------------------------------------------

def test_no_tax_returns_the_input_untouched() -> None:
    """The identity that says the arithmetic is not doing anything on its own.

    With every rate at zero the safe rate is the nominal yield deflated, and
    the equity return is exactly what went in, at any horizon.
    """
    assert after_tax_safe_rate(NOMINAL_YIELD, INFLATION, NO_TAX) == \
        pytest.approx((1 + NOMINAL_YIELD) / (1 + INFLATION) - 1)
    for years in (1.0, 10.0, 30.0, 60.0):
        assert after_tax_equity_compound(EQUITY, INFLATION, years, NO_TAX) == \
            pytest.approx(EQUITY, abs=1e-12)


# --- the safe side ----------------------------------------------------------

def test_the_safe_rate_is_taxed_on_the_nominal_coupon() -> None:
    """Worked by hand: the tax is 12.5% of 3.7842%, not of the real yield.

        after tax nominal  3.7842% x 0.875        = 3.31118%
        less the bollo     3.31118% - 0.2%        = 3.11118%
        deflated           1.0311118 / 1.020369   = 1.05280%

    Taxing the real yield instead would give 1.7125% x 0.875 - 0.2% = 1.29%,
    which is 0.24 points too generous, and that error is invisible unless
    somebody writes the two out side by side.
    """
    assert after_tax_safe_rate(NOMINAL_YIELD, INFLATION, ITALY_TAX) == \
        pytest.approx(0.0105280, abs=1e-6)


def test_taxing_inflation_costs_more_when_inflation_is_higher() -> None:
    """The real yield held fixed, the tax bill rises with inflation.

    This is the whole point of taxing nominal income and it is the property
    most likely to be lost in a refactor: at a constant real yield, a household
    facing 5% inflation keeps less than one facing 1%.
    """
    kept = []
    for inflation in (0.01, 0.03, 0.05):
        nominal = (1 + 0.017) * (1 + inflation) - 1
        kept.append(after_tax_safe_rate(nominal, inflation, ITALY_TAX))
    assert kept[0] > kept[1] > kept[2]


# --- the equity side --------------------------------------------------------

def test_deferral_is_worth_more_the_longer_it_runs() -> None:
    """One year of deferral is no deferral, and thirty is a great deal."""
    short = after_tax_equity_compound(EQUITY, INFLATION, 1.0, ITALY_TAX)
    long_ = after_tax_equity_compound(EQUITY, INFLATION, 30.0, ITALY_TAX)
    longer = after_tax_equity_compound(EQUITY, INFLATION, 60.0, ITALY_TAX)
    assert short < long_ < longer


def test_a_single_year_is_close_to_taxing_the_whole_nominal_gain() -> None:
    """With no time to compound, the deferred tax and an annual one agree.

        nominal        1.042 x 1.020369 - 1     = 6.322450%
        less bollo     1.0632245 x 0.998 - 1    = 6.109805%
        taxed          6.109805% x 0.74         = 4.521256%
        deflated       1.04521256 / 1.020369 -1 = 2.434762%
    """
    assert after_tax_equity_compound(EQUITY, INFLATION, 1.0, ITALY_TAX) == \
        pytest.approx(0.0243476, abs=1e-6)


def test_the_horizon_must_be_positive() -> None:
    with pytest.raises(ValueError):
        after_tax_equity_compound(EQUITY, INFLATION, 0.0, ITALY_TAX)


# --- the asymmetry, which is the reason any of this exists ------------------

def test_tax_takes_more_from_equities_than_from_the_safe_asset() -> None:
    """26% against 12.5%, and deferral does not fully close it.

    Deferral is worth a lot, so the gap is much smaller than the headline
    rates suggest, but it does not reverse. If this ever flips, either the
    deferral horizon has become absurd or the arithmetic is wrong.
    """
    real_safe = (1 + NOMINAL_YIELD) / (1 + INFLATION) - 1
    lost_safe = real_safe - after_tax_safe_rate(NOMINAL_YIELD, INFLATION,
                                                ITALY_TAX)
    lost_equity = EQUITY - after_tax_equity_compound(EQUITY, INFLATION, 30.0,
                                                     ITALY_TAX)
    assert 0 < lost_safe < lost_equity


def test_tax_narrows_the_gap_between_the_two_assets() -> None:
    """Which is why it lowers the recommendation rather than raising it."""
    real_safe = (1 + NOMINAL_YIELD) / (1 + INFLATION) - 1
    before = math.log(1 + EQUITY) - math.log(1 + real_safe)
    after = (math.log(1 + after_tax_equity_compound(EQUITY, INFLATION, 30.0,
                                                    ITALY_TAX))
             - math.log(1 + after_tax_safe_rate(NOMINAL_YIELD, INFLATION,
                                                ITALY_TAX)))
    assert after < before


def test_the_rate_gap_alone_would_cost_more_than_it_does() -> None:
    """Deferral is doing real work, and this measures how much.

    Taxing equities every year at 26% rather than once on sale is the same
    code with a one-year horizon compounded, and the difference between that
    and the thirty-year answer is what deferral is worth. It should be worth
    more than half a point a year at these figures, which is larger than the
    entire withholding leakage the configuration also records.
    """
    annual = after_tax_equity_compound(EQUITY, INFLATION, 1.0, ITALY_TAX)
    deferred = after_tax_equity_compound(EQUITY, INFLATION, 30.0, ITALY_TAX)
    assert deferred - annual > 0.005
