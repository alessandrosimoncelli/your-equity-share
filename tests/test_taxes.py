"""The Italian tax code, and the ways this arithmetic could be wrong.

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

from your_equity_share.expected_return import (  # noqa: E402
    arithmetic_from_compound,
    compound_from_arithmetic,
)
from your_equity_share.mortality import (  # noqa: E402
    LIFE_EXPECTANCY_2019,
    remaining_life_expectancy,
)
from your_equity_share.taxes import (  # noqa: E402
    ITALY_TAX,
    NO_TAX,
    TAX_DEFERRAL_YEARS,
    TaxRegime,
    after_tax_bond_fund,
    after_tax_equity_compound,
    after_tax_returns,
    deferral_years,
)

INFLATION = 0.020369
NOMINAL_YIELD = 0.037842
REAL_YIELD = (1 + NOMINAL_YIELD) / (1 + INFLATION) - 1
EQUITY = 0.042
VOLATILITY = 0.14


def drift(pair: tuple[float, float]) -> float:
    return math.log(1 + pair[0]) - math.log(1 + pair[1])


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
    """The identity that says the arithmetic is not doing anything on its own."""
    for years in (1.0, 10.0, 30.0, 60.0):
        assert after_tax_equity_compound(EQUITY, INFLATION, years, NO_TAX) == \
            pytest.approx(EQUITY, abs=1e-12)
        assert after_tax_bond_fund(REAL_YIELD, INFLATION, years, NO_TAX) == \
            pytest.approx(REAL_YIELD, abs=1e-12)
        mu, rf = after_tax_returns(0.05, REAL_YIELD, VOLATILITY, INFLATION,
                                   years, NO_TAX)
        assert mu == pytest.approx(0.05, abs=1e-12)
        assert rf == pytest.approx(REAL_YIELD, abs=1e-12)


# --- the bond fund ----------------------------------------------------------

def test_the_bond_fund_is_taxed_on_its_nominal_gain() -> None:
    """Worked by hand for one year: 12.5% of the nominal gain, not the real one.

        real yield        1.037842 / 1.020369 - 1    = 1.712420%
        less the bollo    1.037842 x 0.998 - 1        = 3.576632%
        taxed             3.576632% x 0.875           = 3.129553%
        deflated          1.03129553 / 1.020369 - 1   = 1.070841%

    Taxing the real yield instead would leave 1.71% x 0.875 less the bollo,
    about 1.30%, a quarter of a point too generous.
    """
    assert after_tax_bond_fund(REAL_YIELD, INFLATION, 1.0, ITALY_TAX) == \
        pytest.approx(0.01070841, abs=1e-8)


def test_taxing_inflation_costs_more_when_inflation_is_higher() -> None:
    """The real yield held fixed, the tax bill rises with inflation, on both."""
    for fund in (after_tax_bond_fund, after_tax_equity_compound):
        kept = [fund(0.017, inflation, 20.0, ITALY_TAX)
                for inflation in (0.01, 0.03, 0.05)]
        assert kept[0] > kept[1] > kept[2]


# --- deferral ---------------------------------------------------------------

def test_deferral_is_worth_more_the_longer_it_runs() -> None:
    """One year of deferral is no deferral, and thirty is a great deal."""
    for fund, r in ((after_tax_equity_compound, EQUITY),
                    (after_tax_bond_fund, REAL_YIELD)):
        short, long_, longer = (fund(r, INFLATION, y, ITALY_TAX)
                                for y in (1.0, 30.0, 60.0))
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
    with pytest.raises(ValueError):
        after_tax_bond_fund(REAL_YIELD, INFLATION, 0.0, ITALY_TAX)


# --- the asymmetry, which is the reason any of this exists ------------------

@pytest.mark.parametrize("years", [2.2, 12.4, 30.0])
def test_tax_takes_more_from_equities_than_from_the_safe_asset(years) -> None:
    """26% against 12.5%, both deferred to the same sale, at any horizon."""
    lost_safe = REAL_YIELD - after_tax_bond_fund(REAL_YIELD, INFLATION, years)
    lost_equity = EQUITY - after_tax_equity_compound(EQUITY, INFLATION, years)
    assert 0 < lost_safe < lost_equity


@pytest.mark.parametrize("years", [2.2, 12.4, 30.0])
def test_tax_narrows_the_gap_between_the_two_assets(years) -> None:
    """Which is why it lowers the recommendation rather than raising it."""
    mu = arithmetic_from_compound(EQUITY, VOLATILITY)
    before = drift((mu, REAL_YIELD))
    after = drift(after_tax_returns(mu, REAL_YIELD, VOLATILITY, INFLATION, years))
    assert after < before


def test_the_pair_is_the_two_funds_composed_by_hand() -> None:
    """after_tax_returns is a convenience, not a second implementation."""
    mu = 0.048148
    mu_after, rf_after = after_tax_returns(mu, REAL_YIELD, VOLATILITY,
                                           INFLATION, 12.4)
    kept = after_tax_equity_compound(compound_from_arithmetic(mu, VOLATILITY),
                                     INFLATION, 12.4)
    assert mu_after == arithmetic_from_compound(kept, VOLATILITY)
    assert rf_after == after_tax_bond_fund(REAL_YIELD, INFLATION, 12.4)


# --- when the funds are sold ------------------------------------------------

def test_the_life_table_is_the_published_one() -> None:
    """NCHS, United States Life Tables, 2019, NVSR 70(19), Table 1, e_x.

    Spot values read off the publication: 78.8 at birth, 36.3 at 45, 19.6 at
    65, 12.4 at 75, 2.2 at 100 and over.
    """
    assert len(LIFE_EXPECTANCY_2019) == 101
    for age, years in ((0, 78.8), (45, 36.3), (65, 19.6), (75, 12.4), (100, 2.2)):
        assert remaining_life_expectancy(age) == years
    assert remaining_life_expectancy(120) == 2.2
    assert all(a > b for a, b in zip(LIFE_EXPECTANCY_2019[1:], LIFE_EXPECTANCY_2019[2:]))
    with pytest.raises(ValueError):
        remaining_life_expectancy(-1)


def test_the_sale_comes_at_thirty_years_or_at_death_if_sooner() -> None:
    """Thirty below about fifty-two, the expected lifetime above it."""
    assert TAX_DEFERRAL_YEARS == 30.0
    assert deferral_years([25]) == 30.0
    assert deferral_years([45]) == 30.0
    assert deferral_years([60]) == 23.5
    assert deferral_years([75]) == 12.4
    horizons = [deferral_years([age]) for age in range(20, 100)]
    assert all(a >= b for a, b in zip(horizons, horizons[1:]))


def test_a_couple_sells_at_the_average_of_their_two_lifetimes() -> None:
    """Italian law taxes each adult's units at that adult's death.

    75 and 72 expect 12.4 and 14.5 more years, so their savings are sold, on
    average, after 13.45. The cap applies to the average, not to each adult.
    """
    assert deferral_years([75, 72]) == pytest.approx(13.45)
    assert deferral_years([72, 75]) == deferral_years([75, 72])
    assert deferral_years([20, 99]) == 30.0
    with pytest.raises(ValueError):
        deferral_years([])


def test_an_older_household_keeps_less_of_the_equity_premium() -> None:
    """A shorter wait means less deferral, and the 26% fund loses more of it
    than the 12.5% one, so the after-tax premium falls with age."""
    mu = arithmetic_from_compound(EQUITY, VOLATILITY)
    drifts = [drift(after_tax_returns(mu, REAL_YIELD, VOLATILITY, INFLATION,
                                      deferral_years([age])))
              for age in (45, 60, 75, 90)]
    assert drifts[0] > drifts[1] > drifts[2] > drifts[3]
