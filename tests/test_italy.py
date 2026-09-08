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

def test_no_input_is_provisional_any_more(italy) -> None:
    """Both guesses have been replaced by measurements.

    The file shipped with a safe rate and a volatility that had been reasoned
    about. The volatility is now five years of euro-priced closes and the safe
    rate is an ECB curve deflated by an ECB survey. The field stays in the
    configuration so that a guess added back has to declare itself.
    """
    assert italy.provisional_fields == ()
    assert not italy.is_provisional


def test_the_american_configuration_is_not_provisional() -> None:
    assert load_market_data().provisional_fields == ()
    assert not load_market_data().is_provisional


def test_every_provisional_field_names_a_real_input(italy) -> None:
    """A field marked provisional that does not exist protects nothing."""
    for name in italy.provisional_fields:
        assert hasattr(italy, name) or name in {
            "real_risk_free", "stock_volatility", "expected_stock_real_return"}


# --- what the variant currently produces ------------------------------------

def test_the_answer_discriminates_rather_than_saturating(italy) -> None:
    """With the safe rate measured, the variant is no longer a constant.

    It saturated for three of four households when the safe rate was a guess
    of 1.35%. The measured 1.71% leaves one at the cap, the household with two
    years of salary saved, which is where the American variant saturates too
    and for the same reason: the model wants leverage and the clip refuses it.
    """
    from your_equity_share.market_data import load_market_data

    args = (italy.expected_stock_real_return, italy.real_risk_free_rate,
            italy.stock_volatility)
    households = [
        Household(200_000.0, [Person(45, 40_000.0)], 5.0),
        Household(600_000.0, [Person(45, 40_000.0)], 5.0),
        Household(900_000.0, [Person(55, 60_000.0)], 5.0),
        Household(500_000.0, [Person(68, 0.0, 25_000.0)], 5.0),
    ]
    shares = [recommend(h, *args, ITALY_CALIBRATION).equity_share
              for h in households]
    assert len(set(shares)) > 1, "a constant answer is not advice"
    assert sum(1 for s in shares if s == 1.0) <= 1


def test_the_euro_safe_rate_is_below_the_american_one(italy) -> None:
    """And that difference goes straight into the drift.

    A euro household is offered a materially lower real rate for the same
    maturity and better credit, which raises the equity share against the
    American answer before anything about Italy is considered at all.
    """
    from your_equity_share.market_data import load_market_data

    assert italy.real_risk_free_rate < load_market_data().real_risk_free_rate


def test_the_safe_rate_is_a_traded_real_yield(italy) -> None:
    """The same kind of object the American variant reads, or the two variants
    cannot be compared.

    FRED's 30-year TIPS is a traded real yield. Deflating a nominal curve by a
    survey would have made part of the gap between the two answers a
    difference in method rather than in country, and it was worth 5.4 points
    of equity share, so it was not a rounding decision.
    """
    source = italy.provenance["real_risk_free_source"]
    assert source.startswith("DE")
    assert "traded real yield" in source


def test_the_safe_rate_records_the_cross_check_that_brackets_it(italy) -> None:
    """One number, two constructions, and the honest range between them.

    The traded yield is biased low by scarcity: three bonds outstanding and no
    issuance since 2023. The deflated AAA curve is biased high, because the
    gap between the market breakeven and the survey expectation is an
    inflation risk premium and deflating books it as return.
    """
    source = italy.provenance["real_risk_free_source"]
    assert "Cross-checked" in source
    assert "bracket" in source
    assert "Survey of Professional Forecasters" in source


def test_the_safe_rate_is_not_italian_paper(italy) -> None:
    """Equation (4) has no way to represent default risk.

    All euro area government bonds yield about 0.61 points more at the same
    maturity, and that spread is compensation for a government not paying.
    Booking it as a risk-free return would raise the rate and lower the
    recommendation while looking prudent.
    """
    text = Path("config/market_data_it.toml").read_text(encoding="utf-8")
    assert "NOT holding this asset" in text
    assert "0.61 points" in text


def test_the_currency_basis_is_recorded_and_names_its_assumption(italy) -> None:
    """Everything is in euro, and the one assumption is stated rather than hidden.

    The volatility is measured on a euro-priced series and the safe rate is a
    euro yield deflated by euro inflation. The expected return is AQR's local
    real figure, which is only a euro real figure under purchasing power
    parity. That is their own stated assumption and it is the weakest link in
    the configuration, so it is written down where the numbers are.
    """
    basis = italy.provenance["currency_basis"]
    assert basis.startswith("EUR")
    assert "purchasing power" in basis


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


# --- the expected return was borrowed, so it needs an independent check -----

def test_the_borrowed_growth_rate_has_an_independent_cross_check(italy) -> None:
    """AQR's 2.6% is used, so something must corroborate it.

    The Italian variant does not compute its own expected return, which is a
    real dependency on one firm. It is checked against a reconstruction from
    the Jorda-Schularick-Taylor Macrohistory Database, eighteen advanced
    economies from 1870, which is free and has nothing to do with AQR.
    """
    check = italy.provenance["growth_cross_check"]
    assert "Jorda-Schularick-Taylor" in check
    assert "1.33%" in check and "3.16%" in check


def test_the_cross_check_says_why_it_is_not_the_estimate(italy) -> None:
    """A range of 1.82 points is not an estimate, and the config says so.

    The reconstruction is seven times more sensitive to its start year than
    the American estimator is to its window. That is the reason for borrowing
    rather than building, and it is a measured reason rather than an assumed
    one, which is what it was before.
    """
    check = italy.provenance["growth_cross_check"]
    assert "1.82 point" in check
    assert "seven times" in check
