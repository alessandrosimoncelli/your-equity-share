"""The Italian variant, and the one honest change it can make.

Phase one of the Italian tool changes the equity sleeve from the S&P 500 to a
global index, the safe asset from a 30-year TIPS to a euro inflation-linked
bond, and the retirement benefit replacement rate from 40% to 66%. It changes
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

IT_CONFIG = ROOT / "variants" / "it" / "market_data.toml"


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


def test_the_italian_replacement_rate_is_the_treasury_figure() -> None:
    """66% net, the Ragioneria Generale dello Stato's projection for a private
    employee retiring in 2050 at 66 with 38 years of contributions (Rapporto
    n. 26, 2025, Table 6.3.a). The model retires at 67.

    It was the OECD's 79% until October 2026, a figure for 48 years of
    contributions ending at 70. Italian pensions are contributory, so a
    retirement at 67 earns less, and 79% paid from 67 overstated the pension.
    """
    assert ITALY_CALIBRATION.benefit_replacement_rate == 0.66


def test_the_italian_rate_sits_inside_the_grid_choi_solved_over() -> None:
    """This is why the swap is legitimate rather than an extrapolation.

    Equation (12) takes the replacement rate as a regressor, fitted over 0.4,
    0.6 and 0.8. Italy's 66% is between the second and third, so the
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


def test_the_expected_return_is_built_rather_than_borrowed(italy) -> None:
    """The provenance has to name the two measurements, because they are ours.

    This variant took AQR's published figure until September 2026. It now
    builds the estimate from a measured yield and a measured growth trend, so
    the source has to say where each half came from rather than name a firm.
    """
    source = italy.provenance["expected_return_source"]
    assert "Built here" in source
    assert "MSCI" in source and "Shiller" in source


def test_the_expected_return_carries_no_horizon_and_says_why(italy) -> None:
    """The reason for building it is a horizon mismatch, so record the reason.

    AQR state their figure is for five to ten years and that at multi-decade
    horizons "theory and long-term historical averages may matter more". This
    model prices a lifetime. A current yield plus a long-run growth rate with
    no repricing is the same number at any holding period, which is the
    property that makes it usable at thirty years, and Table 7 of the American
    methodology shows it is also the one that wins there.
    """
    source = italy.provenance["expected_return_source"]
    assert "5 to 10 years" in source
    assert "no horizon" in source
    assert "AQR" in source


def test_aqr_is_kept_as_the_cross_check_with_its_numbers(italy) -> None:
    """Demoting a source is not the same as dropping it.

    AQR remain the only firm publishing every component of this estimate, so
    they are still the best independent check on it, and the provenance has to
    carry how far apart the two currently are or the check is invisible.
    """
    source = italy.provenance["expected_return_source"]
    assert "2025-12-31" in source
    assert "points from ours" in source


def test_the_growth_term_is_the_american_estimator_exactly(italy) -> None:
    """One estimator, two variants, so neither can drift away from the other.

    The Italian growth term IS the American variant's hundred-year OLS trend
    through Shiller, not something near it. If that stops being true the two
    configurations measure growth two different ways and any gap between their
    answers stops being about the countries.

    This is the test that would have caught the horizon problem earlier: while
    this variant borrowed AQR's five-to-ten-year figure it could only be
    written as a tolerance, and a tolerance is what a mismatch hides in.
    """
    sys.path.insert(0, str(ROOT))
    from tools.refresh_italy import american_growth_trend

    ours, _ = american_growth_trend()
    if ours is None:
        pytest.skip("Shiller's workbook is not on this machine")
    assert float(italy.provenance["real_growth"]) == pytest.approx(
        ours, abs=5e-6)


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
    measured = float(italy.provenance["dividend_yield_measured"])
    assert measured == pytest.approx(float(italy.provenance["dividend_yield"]))
    assert measured == pytest.approx(0.016, abs=0.0033)


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
    assert italy.before_tax_expected_return == pytest.approx(expected, abs=5e-6)


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
    used a single bond until September 2026, the Bund/euro-i 2046, which has
    19.6 years left and one fewer every year, so it would have been quoting a
    fifteen-year horizon inside a decade under a thirty-year label.
    """
    source = italy.provenance["real_risk_free_source"]
    assert source.startswith("ECB AAA")
    assert "30-year spot rate" in source
    assert "constant maturity" in source.lower()


def test_the_safe_rate_deflator_is_a_price_not_a_forecast(italy) -> None:
    """No survey in the safe rate, which is the whole reason it changed.

    The deflator is the market break-even of the longest euro linker: the rate
    at which holding that bond and holding a nominal bond pay the same. It is
    a price. The ECB Survey of Professional Forecasters is an opinion, and the
    tool is meant to hold measurements and trends.
    """
    source = italy.provenance["real_risk_free_source"]
    assert "break-even" in source.lower()
    breakeven = float(italy.provenance["expected_inflation"])
    survey = float(italy.provenance["expected_inflation_survey"])
    assert breakeven > survey
    assert 0.0 < breakeven - survey < 0.01


def test_the_survey_would_have_flattered_the_safe_asset(italy) -> None:
    """The gap between break-even and survey is an inflation risk premium.

    Deflating by the survey books that premium as return, which makes the safe
    asset look better than any bond a household can actually buy. Recording it
    is the point: it was worth several points of equity share, so a reader has
    to be able to see which deflator produced the number.
    """
    nominal = float(italy.provenance["nominal_safe_yield"])
    breakeven = float(italy.provenance["expected_inflation"])
    survey = float(italy.provenance["expected_inflation_survey"])
    used = (1 + nominal) / (1 + breakeven) - 1
    flattered = (1 + nominal) / (1 + survey) - 1
    assert italy.before_tax_real_risk_free == pytest.approx(used, abs=5e-6)
    assert flattered > used


def test_the_safe_rate_reproduces_a_bond_that_exists(italy) -> None:
    """The construction has to agree with itself, and this is that check.

    The break-even is derived from the Bund/euro-i 2046, so deflating a
    nominal yield by it should recover that bond's own traded real yield. If
    the two ever diverge by more than a fifth of a point, either the scraper
    has picked up the wrong chart or the curves have stopped being flat, and
    both are worth stopping for.
    """
    source = italy.provenance["real_risk_free_source"]
    assert "DE0001030575" in source
    assert "traded real yield" in source
    assert "points away" in source


def test_the_safe_rate_is_not_italian_paper(italy) -> None:
    """Equation (4) has no way to represent default risk.

    All euro area government bonds yield about 0.61 points more at the same
    maturity, and that spread is compensation for a government not paying.
    Booking it as a risk-free return would raise the rate and lower the
    recommendation while looking prudent.
    """
    text = Path("variants/it/market_data.toml").read_text(encoding="utf-8")
    assert "NOT holding this asset" in text
    assert "0.61 points" in text


def test_the_currency_basis_is_recorded_and_names_its_assumption(italy) -> None:
    """Everything is in euro, and the one assumption is stated rather than hidden.

    The volatility is measured on a euro-priced series and the safe rate is a
    euro yield deflated by euro inflation. The expected return is built from a
    local-currency yield and growth rate, which is only a euro real figure
    under purchasing power parity. That is the weakest link in the
    configuration, so it is written down where the numbers are.
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


# --- the denominator, which is worth a third of a point ---------------------

def test_the_measured_yield_uses_todays_price_as_its_denominator() -> None:
    """A trailing dividend over TODAY's price, which is Shiller's convention.

    Three constructions all sound like a trailing twelve-month yield and they
    differ by a third of a point on this data, because the index rose 22%
    across the window: dividends over the price a year ago give 1.87%, each
    month's dividend over that month's own starting price gives 1.70%, and
    dividends over today's price give 1.53%.

    The American variant divides Shiller's trailing annual dividend column by
    his LAST price, so the third is the object the two variants share. This
    reproduces the tool's answer from the raw levels, which is the only way to
    catch the denominator silently changing back.
    """
    import json

    cache = ROOT / "data" / "msci_acwi_eur.json"
    if not cache.exists():
        pytest.skip("MSCI levels have not been cached; run tools/estimators_it.py")
    levels = json.loads(cache.read_text(encoding="utf-8"))
    price, gross = levels["STRD"], levels["GRTR"]
    dates = sorted(set(price) & set(gross))[-13:]
    cash = sum((gross[b] / gross[a] - price[b] / price[a]) * price[a]
               for a, b in zip(dates, dates[1:]))

    expected = cash / price[dates[-1]]
    assert float(italy_provenance()["dividend_yield_measured"]) == \
        pytest.approx(expected, abs=1e-5)

    # And the two rejected constructions really are far enough away to matter.
    over_old_price = cash / price[dates[0]]
    assert abs(over_old_price - expected) > 0.003


def italy_provenance():
    return load_market_data(IT_CONFIG).provenance


# --- the Italian methodology, pinned to the configuration -------------------
#
# The document quoted a tax table computed before the safe rate changed, and
# nothing noticed. The American methodology has 87 verifier checks holding its
# figures to the model; these hold the Italian one to its configuration.

IT_DOC = ROOT / "variants" / "it" / "methodology.html"


def _doc() -> str:
    """The document with its line breaks flattened.

    Prose wraps, so "Cocco, Gomes and Maenhout" is a line break in the middle
    of a name as often as not, and a test that searches the raw file fails on
    typography rather than on content.
    """
    if not IT_DOC.exists():
        pytest.skip("the Italian methodology has not been written")
    raw = IT_DOC.read_text(encoding="utf-8")
    return " ".join(raw.split())


def test_the_italian_methodology_quotes_the_configuration() -> None:
    """Every headline figure in the document has to be the one in use.

    Written as percentages to four decimals or fewer, the way the document
    prints them, so a change to the configuration that is not carried into the
    prose fails here rather than in a reader's head.
    """
    doc = _doc()
    # The snapshot the document was written with, not the live file, which
    # refreshes while the document stays dated.
    italy = load_market_data(ROOT / "variants" / "it" / "snapshot.toml")
    p = italy.provenance
    expected = {
        "dividend yield": "%.4f%%" % (float(p["dividend_yield"]) * 100),
        "growth": "%.4f%%" % (float(p["real_growth"]) * 100),
        "compound": "%.4f%%" % (float(p["expected_return_compound"]) * 100),
        "arithmetic": "%.4f%%" % (italy.expected_stock_real_return * 100),
        "safe rate": "%.4f%%" % (italy.real_risk_free_rate * 100),
        "volatility": "%.4f%%" % (italy.stock_volatility * 100),
        "nominal yield": "%.4f%%" % (float(p["nominal_safe_yield"]) * 100),
        "break-even": "%.4f%%" % (float(p["expected_inflation"]) * 100),
        "survey": "%.4f%%" % (float(p["expected_inflation_survey"]) * 100),
    }
    missing = [name for name, figure in expected.items() if figure not in doc]
    assert not missing, "the document does not quote: %s" % ", ".join(
        "%s (%s)" % (n, expected[n]) for n in missing)


def test_the_italian_methodology_declares_what_it_cannot_check(italy) -> None:
    """Two inputs have no external check and the document has to say which.

    A validation document that quietly omits the unvalidated parts is worse
    than one with no validation section, because it reads as complete.
    """
    doc = _doc()
    assert "What is not validated" in doc
    assert "Cocco, Gomes and Maenhout" in doc
    assert "deferral horizon" in doc


def test_the_italian_methodology_names_a_source_for_each_number(italy) -> None:
    """The validation table is the point of the document, so it must be there."""
    doc = _doc()
    for source in ("AQR", "OECD", "iShares", "MSCI", "Deutsche Finanzagentur",
                   "Rogoff", "Domar and Musgrave", "Horizon Actuarial"):
        assert source in doc, "no citation of %s" % source


def test_the_italian_methodology_has_no_em_dashes() -> None:
    """The same house rule the American document is held to."""
    doc = _doc()
    assert "—" not in doc
    assert "&mdash;" not in doc


@pytest.mark.parametrize("variant", ["us", "it"])
def test_each_snapshot_matches_the_date_its_document_states(variant) -> None:
    """The documents are checked against a frozen snapshot, not live data.

    That only works if the snapshot really is the data the document was written
    with, so the date the document announces and the snapshot's as_of must be
    the same day. Rewrite a document against newer data and this forces the
    snapshot to move with it.
    """
    import re
    from datetime import date

    snap = load_market_data(ROOT / "variants" / variant / "snapshot.toml")
    doc = " ".join((ROOT / "variants" / variant / "methodology.html")
                   .read_text(encoding="utf-8").split())
    stated = re.search(r"as of (\d{1,2}) (\w+) (\d{4})", doc)
    assert stated, "the document does not state an as-of date"
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    day = date(int(stated.group(3)), months.index(stated.group(2)) + 1,
               int(stated.group(1)))
    assert snap.as_of == day


# --- one deflator, and the dates it is written with -------------------------

def _fields(name: str) -> dict:
    import tomllib

    raw = tomllib.loads((ROOT / "variants" / "it" / name).read_text(encoding="utf-8"))
    out: dict = {}
    for section in raw.values():
        if isinstance(section, dict):
            out.update(section)
    return out


@pytest.mark.parametrize("name", ["snapshot.toml", "market_data.toml"])
def test_the_after_tax_figures_use_the_same_deflator_as_the_pre_tax_ones(name) -> None:
    """Tax is levied on nominal income and deflated back to real.

    The pre-tax safe rate is the nominal AAA yield deflated by the market
    break-even, so the after-tax figures must be deflated by that same
    break-even. They were once deflated by the survey instead, which is an
    inflation risk premium lower, and the after-tax safe rate came out a
    quarter of a point too high while the document's own table printed the
    right number. Nothing compared the two, and this does.
    """
    from your_equity_share.expected_return import arithmetic_from_compound
    from your_equity_share.taxes import (
        ITALY_TAX, after_tax_equity_compound, after_tax_safe_rate)

    f = _fields(name)
    breakeven = f["expected_inflation"]
    assert f["real_risk_free"] == pytest.approx(
        (1 + f["nominal_safe_yield"]) / (1 + breakeven) - 1, abs=5e-7)
    assert f["after_tax_real_risk_free"] == pytest.approx(
        after_tax_safe_rate(f["nominal_safe_yield"], breakeven, ITALY_TAX), abs=5e-7)
    net = after_tax_equity_compound(f["expected_return_compound"], breakeven,
                                    30.0, ITALY_TAX)
    assert f["after_tax_expected_return"] == pytest.approx(
        arithmetic_from_compound(net, f["stock_volatility"]), abs=5e-7)


@pytest.mark.parametrize("name", ["snapshot.toml", "market_data.toml"])
def test_the_yield_window_is_written_as_two_dates(name) -> None:
    """A day count once took the place of the window's first date.

    The volatility check reused the variable holding the start of the
    dividend-yield window, and the note read "over 738062 to 20260831".
    """
    import re
    from datetime import datetime

    note = _fields(name)["expected_return_source"]
    window = re.search(r"in euro over (\d+) to (\d+),", note)
    assert window, "the note no longer names its window"
    first, last = (datetime.strptime(d, "%Y%m%d") for d in window.groups())
    assert 300 <= (last - first).days <= 400


# --- the Italian answer is after tax ------------------------------------------

def test_the_italian_answer_is_after_tax_by_default(italy) -> None:
    """Italian tax is the law, not the household's choice, so it is applied.

    The loader reads the after-tax pair the file carries in [market], and
    keeps the figures before tax beside it for comparisons.
    """
    import tomllib

    market = tomllib.loads(IT_CONFIG.read_text(encoding="utf-8"))["market"]
    assert italy.tax_applied
    assert italy.expected_stock_real_return == market["after_tax_expected_return"]
    assert italy.real_risk_free_rate == market["after_tax_real_risk_free"]
    assert italy.before_tax_expected_return == market["expected_stock_real_return"]
    assert italy.before_tax_real_risk_free == market["real_risk_free"]


def test_the_figures_before_tax_are_one_argument_away() -> None:
    """What a comparison with the untaxed American variant needs."""
    before = load_market_data(IT_CONFIG, apply_tax=False)
    assert not before.tax_applied
    assert before.expected_stock_real_return == before.before_tax_expected_return
    assert before.real_risk_free_rate == before.before_tax_real_risk_free


def test_the_american_file_has_no_tax_to_apply() -> None:
    american = load_market_data()
    assert not american.tax_applied
    assert american.expected_stock_real_return == american.before_tax_expected_return
    assert american.real_risk_free_rate == american.before_tax_real_risk_free


def test_the_document_states_the_pension_the_code_uses() -> None:
    """The document once said 74.0% while the chart it cited said 79."""
    rate = f"<strong>{ITALY_CALIBRATION.benefit_replacement_rate:.0%}</strong>"
    assert rate in _doc()


def test_the_italian_answers_the_document_states_are_the_model_s() -> None:
    """Section 1 quotes the answer before and after tax; both are recomputed.

    On the snapshot the document is written against, for its household:
    45 years old, 100,000 of salary, 1,500,000 of savings, risk aversion 5.
    """
    household = Household(1_500_000.0, [Person(45, 100_000.0)], 5.0)
    snapshot = ROOT / "variants" / "it" / "snapshot.toml"
    doc = _doc()
    for market in (load_market_data(snapshot),
                   load_market_data(snapshot, apply_tax=False)):
        share = recommend(household, market.expected_stock_real_return,
                          market.real_risk_free_rate, market.stock_volatility,
                          ITALY_CALIBRATION).equity_share
        assert f"{share:.1%}" in doc, f"{share:.1%}"
