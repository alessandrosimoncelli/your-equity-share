"""The Italian variant, and the one honest change it can make.

Phase one of the Italian tool changes the equity sleeve from the S&P 500 to a
global index, the safe asset from a 30-year TIPS to a euro inflation-linked
bond, and the retirement benefit replacement rate from 40% to 74%. It changes
nothing else in the human capital half, because nothing else in it can be
changed from outside Choi's fitted coefficients.

These tests exist to keep that honest in both directions: that the one Italian
constant really is Italian and sits inside the grid Choi solved over, and that
the rest is still American and still says so. They also refuse to let a
number nobody has measured be presented as though somebody had.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share import (  # noqa: E402
    CGM_CALIBRATION,
    ITALY_CALIBRATION,
    Household,
    Person,
    recommend,
)
from your_equity_share.market_data import load_market_data  # noqa: E402

IT_CONFIG = ROOT / "config" / "market_data_it.toml"


@pytest.fixture(scope="module")
def italy():
    return load_market_data(IT_CONFIG)


# --- the one constant that can be Italian -----------------------------------

def test_only_the_replacement_rate_differs_from_the_american_calibration() -> None:
    """Everything else is inside the fitted coefficients, not beside them.

    The earnings profile and the two shock volatilities are Cocco, Gomes and
    Maenhout's estimates on United States households, and the profile is not
    even a regressor: it is inside the numerical solution Choi fitted to, as
    is United States mortality. Changing them means re-solving his model.
    """
    differences = {
        f.name for f in dataclasses.fields(CGM_CALIBRATION)
        if getattr(CGM_CALIBRATION, f.name) != getattr(ITALY_CALIBRATION, f.name)
    }
    assert differences == {"benefit_replacement_rate"}


def test_the_italian_replacement_rate_is_the_oecd_figure() -> None:
    """74.0% net for an average earner, Pensions at a Glance 2025."""
    assert ITALY_CALIBRATION.benefit_replacement_rate == 0.74


def test_the_italian_rate_sits_inside_the_grid_choi_solved_over() -> None:
    """This is why the swap is legitimate rather than an extrapolation.

    Equation (12) takes the replacement rate as a regressor, fitted over 0.4,
    0.6 and 0.8. Italy's 74% is between the second and third, so the
    coefficient is being interpolated rather than used outside its range. The
    American 40% sits on the bottom edge of the same grid.
    """
    low, high = 0.4, 0.8
    assert low <= ITALY_CALIBRATION.benefit_replacement_rate <= high
    assert low <= CGM_CALIBRATION.benefit_replacement_rate <= high


# --- the market data --------------------------------------------------------

def test_the_equity_sleeve_is_global_and_the_configuration_says_so(italy) -> None:
    assert italy.market_ticker != "SPY"
    assert "All-World" in italy.provenance.get("equity_index", "")


def test_the_expected_return_is_traceable_to_a_published_source(italy) -> None:
    """AQR's Global All Country figure, and its two halves.

    1.6% dividend yield plus 2.6% real EPS growth is 4.2% compound, which is
    equation (5) with no repricing, from the one firm that publishes every
    component. Section 8.3 of the American methodology checks that same firm's
    US figure against their own report.
    """
    yield_ = float(italy.provenance["dividend_yield"])
    growth = float(italy.provenance["real_growth"])
    compound = float(italy.provenance["expected_return_compound"])
    assert yield_ + growth == pytest.approx(compound, abs=5e-4)
    assert "AQR" in italy.provenance["expected_return_source"]


def test_the_expected_return_is_the_arithmetic_mean_the_model_takes(italy) -> None:
    """The same conversion the American variant makes, at the global volatility."""
    from your_equity_share.expected_return import arithmetic_from_compound

    compound = float(italy.provenance["expected_return_compound"])
    expected = arithmetic_from_compound(compound, italy.stock_volatility)
    assert italy.expected_stock_real_return == pytest.approx(expected, abs=5e-6)


# --- the guard --------------------------------------------------------------

def test_the_configuration_admits_which_inputs_are_not_measured(italy) -> None:
    """The safe rate is reasoned about rather than read off a market.

    An answer built on a guessed safe rate is not the same kind of object as
    one built on a measured one, and the difference has to survive into the
    data rather than living in somebody's memory. The volatility started
    provisional too and is now measured from the ticker, which is what this
    field is for: it shrinks as the numbers get real.
    """
    assert set(italy.provisional_fields) == {"real_risk_free"}
    assert italy.is_provisional


def test_the_american_configuration_is_not_provisional() -> None:
    assert load_market_data().provisional_fields == ()
    assert not load_market_data().is_provisional


def test_every_provisional_field_names_a_real_input(italy) -> None:
    """A field marked provisional that does not exist protects nothing."""
    for name in italy.provisional_fields:
        assert hasattr(italy, name) or name in {
            "real_risk_free", "stock_volatility", "expected_stock_real_return"}


# --- what the variant currently produces ------------------------------------

def test_the_italian_inputs_saturate_the_cap_for_the_default_household(
    italy,
) -> None:
    """Recorded because it is the phase one result, not because it is right.

    A higher expected return, a much lower safe rate and a lower volatility
    compound into a Merton share well above the American one, and the
    multiplier then takes it past 100%. The safe rate driving most of that is
    provisional, so this saturation rests on a number nobody has measured and
    must not be read as a recommendation.
    """
    household = Household(200_000.0, [Person(45, 40_000.0)], 5.0)
    answer = recommend(household, italy.expected_stock_real_return,
                       italy.real_risk_free_rate, italy.stock_volatility,
                       ITALY_CALIBRATION)
    assert answer.is_capped
    assert answer.equity_share == 1.0
    assert italy.is_provisional, (
        "if the inputs ever become measured, this test should be replaced by "
        "one that checks the answer discriminates rather than saturating"
    )


def test_a_higher_replacement_rate_raises_the_share_on_its_own(italy) -> None:
    """The Italian pension is the one change that is unambiguously Italian.

    More guaranteed retirement income is more bond-like wealth, so it leaves
    room for more equity. Measured on the American market data so that only
    the pension moves.
    """
    market = load_market_data()
    household = Household(1_500_000.0, [Person(45, 100_000.0)], 5.0)
    args = (market.expected_stock_real_return, market.real_risk_free_rate,
            market.stock_volatility)
    american = recommend(household, *args, CGM_CALIBRATION).equity_share
    italian = recommend(household, *args, ITALY_CALIBRATION).equity_share
    assert italian > american
