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


def test_the_expected_return_is_equation_five_with_no_repricing(italy) -> None:
    """A measured dividend yield plus a measured growth rate, and nothing else.

    This variant borrowed AQR's 4.2% whole until September 2026. It now builds
    the estimate itself, from the same three terms the American variant uses,
    so that the two answers differ by country rather than by method.
    """
    yield_ = float(italy.provenance["dividend_yield"])
    growth = float(italy.provenance["real_growth"])
    compound = float(italy.provenance["expected_return_compound"])
    assert yield_ + growth == pytest.approx(compound, abs=5e-6)


def test_the_expected_return_names_its_publisher_and_its_cadence(italy) -> None:
    """A borrowed number has to say whose it is and when it goes stale.

    The figure is AQR's and it is refreshed once a year, so the provenance
    carries the report, the as-of date and the annual cadence. Without the
    cadence a reader cannot tell whether a two-year-old file is current.
    """
    source = italy.provenance["expected_return_source"]
    assert "AQR" in source
    assert "2025-12-31" in source
    assert "once a year" in source


def test_the_borrowed_return_carries_its_own_running_checks(italy) -> None:
    """Borrowing annually is only safe if the halves are checked in between.

    Both are, on every run of the refresh tool, against data that costs
    nothing: the dividend yield against MSCI's own index levels and the growth
    rate against the American variant's Shiller trend. The provenance has to
    record what those checks currently return, or the check is invisible to a
    reader and might as well not run.
    """
    source = italy.provenance["expected_return_source"]
    assert "MSCI" in source and "Shiller" in source
    assert "points from theirs" in source


def test_the_growth_rate_still_agrees_with_our_own_estimator(italy) -> None:
    """AQR's growth rate is used, so our own has to keep confirming it.

    The American variant measures real growth in earnings per share over a
    hundred years of Shiller. That is a genuine independent check on AQR's
    global figure, and a legitimate comparison because AQR themselves publish
    2.7% for United States large cap against 2.6% for Global All Country.

    Half a point is the bar. Closer than that and the two are measuring the
    same thing; further apart and one of them has moved, which is the signal
    to go and read AQR's current report rather than wait for January.
    """
    sys.path.insert(0, str(ROOT))
    from tools.refresh_italy import american_growth_trend

    ours, _ = american_growth_trend()
    if ours is None:
        pytest.skip("Shiller's workbook is not on this machine")
    theirs = float(italy.provenance["real_growth"])
    assert abs(ours - theirs) < 0.005


def test_the_growth_source_says_what_checks_it(italy) -> None:
    """The check is only worth something if its logic is written down."""
    source = italy.provenance["growth_source"]
    assert "American" in source
    assert "2.7%" in source and "2.6%" in source


def test_our_measured_yield_agrees_with_the_one_being_used(italy) -> None:
    """AQR quote 1.6% for this index, and our measurement has to land near it.

    Not a tolerance picked to pass: a global dividend yield is a slow and
    heavily reported quantity, so a measurement a third of a point from the
    published figure would mean either that the gross-minus-price construction
    is wrong or that the market has moved away from the number in use. Both
    are worth knowing and neither is quiet.
    """
    used = float(italy.provenance["dividend_yield"])
    measured = float(italy.provenance["dividend_yield_measured"])
    assert measured == pytest.approx(used, abs=0.0033)


def test_the_withholding_tax_is_recorded_rather_than_netted_off(italy) -> None:
    """The yield is gross, so the tax a euro investor pays has to stay visible.

    Shiller's dividend column is gross, so the global yield is measured gross
    too and the two variants compare. That leaves a real cost of a global
    sleeve out of the model, and a cost left out without being written down is
    a cost hidden.
    """
    withheld = float(italy.provenance["dividend_yield_withheld"])
    assert 0.001 < withheld < 0.010
    assert "withholding tax" in IT_CONFIG.read_text(encoding="utf-8").lower()


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


def test_the_safe_rate_holds_its_maturity_fixed(italy) -> None:
    """A constant-maturity curve, which is what FRED's DFII30 is.

    DFII30 is not a bond: it is the thirty-year point read off the TIPS curve
    every day, so it describes the same horizon at every refresh. This file
    used a single bond until September 2026, the Bund/euro-i 2046, on the
    argument that a traded real yield is the same kind of object. It is not.
    That bond has 19.6 years left and one fewer every year, so it would have
    been quoting a fifteen-year horizon inside a decade while the file still
    called it the thirty-year rate.
    """
    source = italy.provenance["real_risk_free_source"]
    assert source.startswith("ECB AAA")
    assert "CONSTANT MATURITY" in source
    assert "30-year" in source


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


# --- the global growth rate was attempted and abandoned, so say so ----------

def test_the_abandoned_alternative_is_recorded(italy) -> None:
    """Using a United States growth rate globally needs the failure written down.

    The honest alternative is to measure growth on global data, and it was
    tried: tools/global_growth.py rebuilds it from the
    Jorda-Schularick-Taylor Macrohistory Database, eighteen advanced economies
    from 1870, free and unconnected to AQR. The configuration has to carry what
    that found, because the reason for not using it IS the justification for
    the American growth term.
    """
    check = italy.provenance["growth_cross_check"]
    assert "Jorda-Schularick-Taylor" in check
    assert "0.89%" in check and "5.43%" in check


def test_the_cross_check_reports_the_whole_envelope(italy) -> None:
    """One scheme's range is not the uncertainty, and this file said it was.

    An earlier version quoted 1.33% to 3.16%, the spread of a single weighting
    scheme across start years, as though it were the error on the estimate.
    The weighting scheme moves the answer four times further than the start
    year does, and the config now says that and says what it used to say.
    """
    check = italy.provenance["growth_cross_check"]
    assert "4.5 points" in check
    assert "too flattering" in check


def test_the_cross_check_gives_the_structural_reason(italy) -> None:
    """A number that moves is a symptom. The config has to name the cause.

    A fixed basket of countries is not an index, because an index
    reconstitutes and JST publishes country index returns rather than the
    world index's constituents. Without that sentence the cross-check reads as
    an admission of defeat rather than a finding.
    """
    check = italy.provenance["growth_cross_check"]
    assert "reconstitut" in check
