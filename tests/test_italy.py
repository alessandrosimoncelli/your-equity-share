"""The Italian variant, and what it can honestly make Italian.

The Italian tool changes the equity sleeve from the S&P 500 to a global
index, the safe asset from a 30-year TIPS to a euro inflation-linked bond, and
the household from an American college graduate to an Italian private-sector
employee: Daminato and Padula's earnings process, estimated on the Bank of
Italy's household survey, and the Ragioneria Generale dello Stato's 66.4%
pension. Mortality
stays American, because it is inside Choi's fitted discount rates.

These tests keep that honest in both directions: that the Italian constants
are the published ones and sit where Choi's coefficients can take them, and
that what is still American says so. They also refuse to let a number nobody
has measured be presented as though somebody had.
"""

from __future__ import annotations

import dataclasses
import math
import re
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
from your_equity_share.human_capital import imputed_wage  # noqa: E402
from your_equity_share.market_data import load_market_data  # noqa: E402

IT_CONFIG = ROOT / "variants" / "it" / "market_data.toml"


@pytest.fixture(scope="module")
def italy():
    return load_market_data(IT_CONFIG)


# --- the one constant that can be Italian -----------------------------------

def test_the_italian_calibration_changes_the_career_and_the_pension() -> None:
    """An Italian private-sector employee in place of an American graduate.

    The calibration's 18.5% stays, but only as a default: the model is always
    handed the volatility of the asset held (16.45% for the Italian fund), and
    the discount rates read it through the log risk premium, as Choi defines
    it.
    """
    differences = {
        f.name for f in dataclasses.fields(CGM_CALIBRATION)
        if getattr(CGM_CALIBRATION, f.name) != getattr(ITALY_CALIBRATION, f.name)
    }
    assert differences == {"benefit_replacement_rate", "permanent_shock_volatility",
                           "temporary_shock_volatility", "age_profile", "benefit_cap"}


def test_the_italian_career_is_daminato_and_padula_s() -> None:
    """Table 7 of their working paper (CSEF 585), private employees, Bank of
    Italy household survey 1986 to 2008: permanent variance 0.015156,
    transitory 0.023609, and the cubic in age."""
    assert ITALY_CALIBRATION.permanent_shock_volatility == pytest.approx(math.sqrt(0.015156))
    assert ITALY_CALIBRATION.temporary_shock_volatility == pytest.approx(math.sqrt(0.023609))
    assert ITALY_CALIBRATION.age_profile == (-0.001022, 0.000613, -0.000006)


def test_the_italian_career_keeps_rising_where_the_american_one_falls() -> None:
    """The reason for the change. From 45 to 60 the expected Italian wage
    rises by more than a fifth; the American graduate's does not rise at all."""
    italian = imputed_wage(60, 45, 1.0, ITALY_CALIBRATION)
    american = imputed_wage(60, 45, 1.0, CGM_CALIBRATION)
    assert italian > 1.2
    assert american < 1.0


def test_the_italian_replacement_rate_is_the_treasury_figure() -> None:
    """66.4% net, the Ragioneria Generale dello Stato's projection for a private
    employee on the average wage retiring in 2050 at 66 years and 3 months
    with 38 years of contributions (Rapporto
    n. 27, 2026, Table 6.3.a), restated on the base the page asks for. The 66.4%
    is a share of the final net pay without the TFR; the page asks for the
    wage with the yearly TFR accrual added, about 7.5% of net pay, so the same
    pension is 0.664 / 1.075 of it. The model retires at 67.

    It was the OECD's 79% until October 2026, a figure for 48 years of
    contributions ending at 70. Italian pensions are contributory, so a
    retirement at 67 earns less, and 79% paid from 67 overstated the pension.
    """
    assert ITALY_CALIBRATION.benefit_replacement_rate == pytest.approx(0.664 / 1.075, abs=5e-4)


def test_the_italian_rate_sits_inside_the_grid_choi_solved_over() -> None:
    """This is why the swap is legitimate rather than an extrapolation.

    The wage discount rate (the paper's Table 1; equation (12) of the
    methodology) takes the replacement rate as a regressor, fitted over 0.4,
    0.6 and 0.8. Italy's 61.8% is between the second and third, so the
    coefficient is being interpolated rather than used outside its range. The
    American 40% sits on the bottom edge of the same grid.
    """
    low, high = 0.4, 0.8
    assert low <= ITALY_CALIBRATION.benefit_replacement_rate <= high
    assert low <= CGM_CALIBRATION.benefit_replacement_rate <= high
    # The permanent shock is a regressor too, fitted over 10.2% to 13.0%.
    assert 0.102 <= ITALY_CALIBRATION.permanent_shock_volatility <= 0.130


# --- the market data --------------------------------------------------------

def test_the_equity_sleeve_is_global_and_the_configuration_says_so(italy) -> None:
    assert "All Country World" in italy.provenance.get("equity_index", "")


def test_the_expected_return_is_equation_five_with_no_repricing(italy) -> None:
    """A measured dividend yield compounded with a measured growth rate, and
    nothing else: 1 + R = (1 + yield)(1 + growth), with no repricing.

    This variant borrowed AQR's 4.2% whole until September 2026. It now builds
    the estimate itself, from the same three terms the American variant uses,
    so that the two answers differ by country rather than by method.
    """
    yield_ = float(italy.provenance["dividend_yield"])
    growth = float(italy.provenance["real_growth"])
    compound = float(italy.provenance["expected_return_compound"])
    assert (1 + yield_) * (1 + growth) - 1 == pytest.approx(compound, abs=5e-6)


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


def test_our_measured_yield_agrees_with_aqr_s() -> None:
    """AQR quote 1.6% gross for this index at the end of 2025, and our gross
    measurement at the snapshot has to land near it.

    Not a tolerance picked to pass: a global dividend yield is a slow and
    heavily reported quantity, so a measurement a third of a point from the
    published figure at nearly the same date would mean the gross-minus-price
    construction is wrong. Checked on the snapshot, not the weekly data: a
    20% fall in world equities lifts the yield past the band, which is the
    market moving, not the construction failing, and the refresh prints the
    distance from AQR every week.
    """
    snapshot = load_market_data(ROOT / "variants" / "it" / "snapshot.toml")
    measured = float(snapshot.provenance["dividend_yield_measured"])
    assert measured == pytest.approx(0.016, abs=0.0033)


def test_the_weekly_yield_is_plausible(italy) -> None:
    """Only a wide band on the weekly figure: since 2001 the same construction
    on the saved MSCI series has run between about 1.5% and 3.3%."""
    measured = float(italy.provenance["dividend_yield_measured"])
    assert 0.005 < measured < 0.05


def test_the_yield_used_is_net_of_withholding(italy) -> None:
    """The fund loses the withholding at source and no holder gets it back, so
    the yield the model uses is the net one, and the expected return is built
    on it: net yield plus growth, converted at the fixed volatility."""
    from your_equity_share.expected_return import arithmetic_from_compound

    p = italy.provenance
    measured, withheld = float(p["dividend_yield_measured"]), float(p["dividend_yield_withheld"])
    assert 0.001 < withheld < 0.010
    assert float(p["dividend_yield"]) == pytest.approx(measured - withheld, abs=5e-6)
    compound = (1 + float(p["dividend_yield"])) * (1 + float(p["real_growth"])) - 1
    assert float(p["expected_return_compound"]) == pytest.approx(compound, abs=5e-6)
    assert italy.expected_stock_real_return == pytest.approx(
        arithmetic_from_compound(compound, italy.stock_volatility), abs=5e-6)
    assert "net of withholding" in IT_CONFIG.read_text(encoding="utf-8").lower()


def test_the_volatility_is_fixed_not_measured_each_week(italy) -> None:
    """The fixed long-run figure in refresh_italy.py, and nothing that the
    weekly refresh rewrites."""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    import refresh_italy

    assert italy.stock_volatility == refresh_italy.ITALY_VOLATILITY
    assert "volatility_observations" not in IT_CONFIG.read_text(encoding="utf-8")


def test_the_fixed_volatility_is_choi_s_estimator_on_every_day_of_the_month() -> None:
    """Recomputed from MSCI's daily levels when they are cached, so the
    constant cannot drift from its own definition. Month-end alone is the
    lowest of the 28 days in this window, which is why it is not used."""
    import json
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    import italy_volatility
    import refresh_italy

    # On every run: the constant is the average of the 28 recorded figures,
    # and month-end sits below all of them.
    recorded = italy_volatility.MEASURED
    assert len(recorded) == 28
    average = (sum(v * v for v in recorded) / len(recorded)) ** 0.5
    assert refresh_italy.ITALY_VOLATILITY == pytest.approx(average, abs=1e-6)
    assert italy_volatility.MONTH_END < min(recorded) < 0.15 < 0.18 < max(recorded)
    # Where the daily levels are cached, the 28 are measured again.
    if not italy_volatility.CACHE.exists():
        return
    levels = json.loads(italy_volatility.CACHE.read_text(encoding="utf-8"))
    sigma, by_day = italy_volatility.volatility(levels)
    assert refresh_italy.ITALY_VOLATILITY == pytest.approx(sigma, abs=5e-7)
    assert by_day == pytest.approx(list(recorded), abs=5e-7)


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

def test_the_answer_discriminates_rather_than_saturating() -> None:
    """With the safe rate measured, the variant is no longer a constant.

    It saturated for three of four households when the safe rate was a guess
    of 1.35%. The measured 1.71% leaves one at the cap, the household with two
    years of salary saved, which is where the American variant saturates too
    and for the same reason: the model wants leverage and the clip refuses it.
    """
    # On the snapshot the methodology quotes, not on the weekly data: whether
    # one of four households is capped is a property of the market, and a
    # market move must not stop the refresh.
    italy = load_market_data(ROOT / "variants" / "it" / "snapshot.toml")
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


def test_the_euro_safe_rate_is_below_the_american_one() -> None:
    """And that difference goes straight into the drift.

    Checked on the two snapshots the methodologies quote, which is where the
    claim is made; on the weekly data it is a state of the market, and a test
    of it would stop the refresh the day it changed.
    """
    italy = load_market_data(ROOT / "variants" / "it" / "snapshot.toml")
    american = load_market_data(ROOT / "variants" / "us" / "snapshot.toml")
    assert italy.real_risk_free_rate < american.real_risk_free_rate


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
    assert "30-year par yield" in source
    assert "constant maturity" in source.lower()


def test_the_safe_rate_deflator_is_a_price_not_a_forecast(italy) -> None:
    """No survey in the safe rate, which is the whole reason it changed.

    The deflator is the market break-even of the longest German linker: the rate
    at which holding that bond and holding a nominal bond pay the same. It is
    a price. The ECB Survey of Professional Forecasters is an opinion, and the
    tool is meant to hold measurements and trends.
    """
    source = italy.provenance["real_risk_free_source"]
    assert "break-even" in source.lower()
    # Which chart the scraper reads is tested on a fixture page in
    # tests/test_refresh_italy.py; a band around the survey could not catch
    # it, and on weekly data it was a state of the market.


def test_the_safe_rate_is_the_annual_nominal_less_the_break_even(italy) -> None:
    """Two conventions matched, then a subtraction.

    The ECB compounds its curve continuously, so the stored nominal is the
    annualised rate; the Finanzagentur defines the break-even as a simple yield
    difference, so it comes off by subtraction. The note says both.
    """
    nominal = float(italy.provenance["nominal_safe_yield"])
    breakeven = float(italy.provenance["expected_inflation"])
    assert italy.real_risk_free_rate == pytest.approx(nominal - breakeven, abs=5e-6)
    note = italy.provenance["real_risk_free_source"]
    assert "continuously compounded" in note and "simple yield difference" in note


def test_the_safe_rate_reproduces_a_bond_that_exists() -> None:
    """The construction has to agree with itself, and this is that check.

    The break-even is derived from the Bund/euro-i 2046, so deflating a
    nominal yield by it should recover that bond's own traded real yield. If
    the two ever diverge by more than a fifth of a point, either the scraper
    has picked up the wrong chart or the curves have stopped being flat, and
    both are worth stopping for.
    """
    # Read from the snapshot, which records the check and the bond it used.
    # The weekly refresh no longer repeats the check, and it takes whichever
    # linker is longest outstanding, so a new issue would change the bond in
    # the live file without anything being wrong.
    snapshot = load_market_data(ROOT / "variants" / "it" / "snapshot.toml")
    note = snapshot.provenance["real_risk_free_source"]
    assert "DE0001030575" in note
    gap = float(re.search(r"lands ([0-9.]+) points away", note).group(1))
    assert gap < 0.2


def test_the_safe_rate_is_not_italian_paper(italy) -> None:
    """Equation (4) has no way to represent default risk.

    All euro area government bonds yielded 0.56 points more at the same
    maturity, and that spread is compensation for a government not paying.
    Booking it as a risk-free return would raise the rate and lower the
    recommendation while looking prudent.
    """
    text = IT_CONFIG.read_text(encoding="utf-8")
    assert "NOT holding this asset" in text
    assert "0.56 points" in text


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
    """The Italian pension, on its own, raises the share.

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
    # The snapshot's window, which the cache was saved for; the weekly file
    # moves on every month and is checked by the refresh itself.
    snapshot = load_market_data(ROOT / "variants" / "it" / "snapshot.toml")
    dates = sorted(d for d in set(price) & set(gross) if str(d) <= "20260831")[-13:]
    cash = sum((gross[b] / gross[a] - price[b] / price[a]) * price[a]
               for a, b in zip(dates, dates[1:]))

    expected = cash / price[dates[-1]]
    assert float(snapshot.provenance["dividend_yield_measured"]) == \
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
    assert "Leaving tax out" in doc


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
def test_the_files_state_the_market_before_tax(name) -> None:
    """The model reads market figures as they are (Italian methodology,
    section 8), so the files carry no after-tax figure and no regime."""
    f = _fields(name)
    assert not [k for k in f if "after_tax" in k or k == "tax_regime"]
    assert f["real_risk_free"] == pytest.approx(
        f["nominal_safe_yield"] - f["expected_inflation"], abs=5e-7)


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

def test_the_italian_answer_is_before_tax_like_the_american() -> None:
    """One way of reading the market in both variants: the figures as stated."""
    import tomllib

    for variant in ("us", "it"):
        path = ROOT / "variants" / variant / "market_data.toml"
        market = tomllib.loads(path.read_text(encoding="utf-8"))["market"]
        loaded = load_market_data(path)
        assert loaded.expected_stock_real_return == market["expected_stock_real_return"]
        assert loaded.real_risk_free_rate == market["real_risk_free"]


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
    market = load_market_data(ROOT / "variants" / "it" / "snapshot.toml")
    american = load_market_data(ROOT / "variants" / "us" / "snapshot.toml")
    doc = _doc()
    share = recommend(household, market.expected_stock_real_return,
                      market.real_risk_free_rate, market.stock_volatility,
                      ITALY_CALIBRATION).equity_share
    us = recommend(household, american.expected_stock_real_return,
                   american.real_risk_free_rate, american.stock_volatility,
                   CGM_CALIBRATION).equity_share
    assert f"between a {us:.1%} American answer and a {share:.1%} Italian one" in doc
    # The American career with the OECD's Italian 79%, as the variant had it:
    # Social Security's maximum is no part of that counterfactual.
    graduate = dataclasses.replace(CGM_CALIBRATION, benefit_replacement_rate=0.79,
                                   benefit_cap=None)
    with_79 = recommend(household, market.expected_stock_real_return,
                        market.real_risk_free_rate, market.stock_volatility,
                        graduate).equity_share
    assert f"held {with_79:.1%}; with these, {share:.1%}" in doc


# --- section 10, why the answer is so often 100% ----------------------------
#
# Every figure in the section is recomputed from the two snapshots the
# documents are written against, and the households the pages open with are
# read from the pages' own source. A change to a default, a calibration or the
# market data that is not carried into the prose fails here.

US_PAGE = ROOT / "src" / "web" / "index.html"
IT_TABLE = ROOT / "src" / "web" / "it" / "translation.toml"


def _snapshots() -> dict:
    """The two snapshots, as functions from a household's ages to the
    (expected return, safe rate, volatility) its model reads. The ages do not
    change it, since neither variant applies tax; the shape is kept so each
    test reads one way."""
    loaded = {"it": load_market_data(ROOT / "variants" / "it" / "snapshot.toml"),
              "us": load_market_data(ROOT / "variants" / "us" / "snapshot.toml")}
    return {name: (lambda ages, m=m: (m.expected_stock_real_return,
                                      m.real_risk_free_rate, m.stock_volatility))
            for name, m in loaded.items()}


def _opening(page: str) -> tuple[int, float, float, float]:
    """Age, salary, savings and risk answer a page opens with.

    The Italian salary and savings are whatever the translation table swaps
    in, because that is where the build takes them from; everything else is
    the English page's.
    """
    import re

    source = US_PAGE.read_text(encoding="utf-8")
    age = int(re.search(r'id="age"[^>]*value="(\d+)"', source).group(1))
    gamma = float(re.search(r"const DEFAULT_GAMMA = ([\d.]+);", source).group(1))
    if page == "it":
        table = IT_TABLE.read_text(encoding="utf-8")
        pay = re.search(r"it = '''id=\"wage\" value=\"(\d+)\">'''", table)
        savings = re.search(r"it = '''id=\"wealth\" value=\"(\d+)\">'''", table)
    else:
        pay = re.search(r'id="wage" value="(\d+)"', source)
        savings = re.search(r'id="wealth" value="(\d+)"', source)
    return age, float(pay.group(1)), float(savings.group(1)), gamma


def _share(market, calibration, age, pay, savings, gamma) -> float:
    return recommend(Household(savings, [Person(age, pay)], gamma), *market([age]),
                     calibration).equity_share


def _shapley(players, value) -> dict:
    """Each player's average marginal contribution over every order."""
    import itertools

    totals = dict.fromkeys(players, 0.0)
    orders = list(itertools.permutations(players))
    for order in orders:
        have: frozenset = frozenset()
        for player in order:
            totals[player] += value(have | {player}) - value(have)
            have = have | {player}
    return {player: total / len(orders) for player, total in totals.items()}


def test_the_100_percent_table_is_the_model_s() -> None:
    """Table 8: the savings, in years of pay, below which the answer is 100%.

    Merton's share b of total wealth needs b * (H + W) of stocks, which all
    of W covers only once W reaches b * H / (1 - b).
    """
    doc = _doc()
    markets = _snapshots()

    def threshold(market, calibration, age, gamma):
        r = recommend(Household(1.0, [Person(age, 1.0)], gamma), *market([age]),
                      calibration)
        b = r.merton_share
        return b * r.human_capital / (1.0 - b)

    default_column, american_column = [], []
    for age in (25, 35, 45, 55, 65):
        cells = [threshold(markets["it"], ITALY_CALIBRATION, age, g)
                 for g in (3.0, 5.0, 8.0)]
        american = threshold(markets["us"], CGM_CALIBRATION, age, 5.0)
        default_column.append(cells[1])
        american_column.append(american)
        row = (f'<tr><td>{age}</td>'
               + "".join(f'<td class="num">{c:.1f}</td>' for c in cells)
               + f'<td class="num">{american:.1f}</td></tr>')
        assert row in doc, row
    for column in (default_column, american_column):
        stated = f"{min(column):.1f} to {max(column):.1f} years"
        assert stated in doc, stated


def test_the_opening_household_is_the_model_s() -> None:
    """The household the Italian page opens with, figure by figure."""
    doc = _doc()
    age, pay, savings, gamma = _opening("it")
    r = recommend(Household(savings, [Person(age, pay)], gamma),
                  *_snapshots()["it"]([age]), ITALY_CALIBRATION)
    assert r.equity_share == 1.0, "the section explains a 100% answer"
    stocks = r.merton_share * (r.human_capital + savings)
    for stated in (
        f"is {age} years old, earns {pay:,.0f} euro a year after tax, has "
        f"{savings:,.0f} saved and answers {gamma:.0f} for risk",
        f"worth {r.human_capital:,.0f} euro, {r.human_capital / pay:.1f} years of pay",
        f"together is {r.merton_share:.1%}, which is {stocks:,.0f} euro of stocks "
        f"against {savings:,.0f} to invest",
        f"would hold {r.uncapped_share:.0%} of the savings",
    ):
        assert stated in doc, stated


def test_the_three_reasons_quote_the_model() -> None:
    """The market, career and savings figures the three reasons cite."""
    doc = _doc()
    markets = _snapshots()
    it, us = markets["it"]([45]), markets["us"]([45])

    def drift(m):
        return math.log(1 + m[0]) - math.log(1 + m[1])

    def merton(m):
        return recommend(Household(1.0, [Person(45, 1.0)], 5.0), *m,
                         ITALY_CALIBRATION).merton_share

    def years(m, calibration):
        return recommend(Household(1.0, [Person(45, 1.0)], 5.0), *m,
                         calibration).human_capital

    _, it_pay, it_savings, _ = _opening("it")
    _, us_pay, us_savings, _ = _opening("us")
    for stated in (
        f"drift of {drift(it) * 100:.2f} points a year in euro",
        f"against {drift(us) * 100:.2f} in the United States",
        f"{us[1]:.2%} real on 30-year TIPS",
        f"low, {it[1]:.2%}.",
        f"{it[2]:.2%} a year against {us[2]:.2%} for the whole American market",
        f"the share is {merton(it):.1%} in Italy against {merton(us):.1%}",
        f"human capital at 45 from {years(us, CGM_CALIBRATION):.1f} years of pay "
        f"to {years(it, CGM_CALIBRATION):.1f}",
        f"human capital at 45 from {years(us, CGM_CALIBRATION):.1f} years of pay "
        f"to {years(us, ITALY_CALIBRATION):.1f}, and with the euro market as "
        f"well, to {years(it, ITALY_CALIBRATION):.1f}",
        f"opens on savings of {it_savings / it_pay:.1f} years of pay, "
        f"{it_savings:,.0f} euro against {it_pay:,.0f} of salary",
        f"the American page on {us_savings / us_pay:.0f} years, "
        f"{us_savings:,.0f} dollars against {us_pay:,.0f}",
    ):
        assert stated in doc, stated


def test_the_split_of_the_extra_equity_is_the_model_s() -> None:
    """Table 9, by the Shapley value, for both columns.

    The two pages open on the same savings, five years of pay, so both columns
    move an American household to the Italian one in the same two steps: the
    first is the pages' opening household, the second the reference household
    of section 1.
    """
    doc = _doc()
    markets = _snapshots()
    age, us_pay, us_savings, gamma = _opening("us")
    _, it_pay, it_savings, _ = _opening("it")
    # The section says the savings are no part of the difference.
    assert round(it_savings / it_pay, 6) == round(us_savings / us_pay, 6)

    def opening(have):
        return _share(markets["it" if "market" in have else "us"],
                      ITALY_CALIBRATION if "career" in have else CGM_CALIBRATION,
                      age, 1.0, us_savings / us_pay, gamma)

    def reference(have):
        return _share(markets["it" if "market" in have else "us"],
                      ITALY_CALIBRATION if "career" in have else CGM_CALIBRATION,
                      45, 100_000.0, 1_500_000.0, 5.0)

    italian = frozenset({"market", "career"})
    first = _shapley(("market", "career"), opening)
    second = _shapley(("market", "career"), reference)
    rows = (
        ("American answer", f"{opening(frozenset()):.1%}",
         f"{reference(frozenset()):.1%}"),
        ("1. The euro market", f"{first['market'] * 100:+.1f}",
         f"{second['market'] * 100:+.1f}"),
        ("2. The Italian career and pension", f"{first['career'] * 100:+.1f}",
         f"{second['career'] * 100:+.1f}"),
        ("Italian answer", f"{opening(italian):.1%}",
         f"{reference(italian):.1%}"),
    )
    for label, a, b in rows:
        row = (f'<tr><td>{label}</td><td class="num">{a}</td>'
               f'<td class="num">{b}</td></tr>')
        assert row in doc, row

    # What the prose says about them: "about four fifths of the extra equity is
    # the market" for both, and for the opening households "neither change
    # alone takes the American answer to 100%, and the two together take it
    # past it".
    for split in (first, second):
        assert round(5 * split["market"] / sum(split.values())) == 4
    assert all(opening(frozenset({one})) < 1.0 for one in ("market", "career"))
    assert opening(italian) == 1.0
    # The rounded rows add up to the rounded totals, so a reader's sum works.
    for split, start, end in ((first, opening(frozenset()), opening(italian)),
                              (second, reference(frozenset()), reference(italian))):
        shown = sum(round(v * 100, 1) for v in split.values())
        assert abs(shown - (round(end * 100, 1) - round(start * 100, 1))) < 0.1 + 1e-9


# --- section 8, why tax is left out ------------------------------------------

def test_the_tax_table_is_the_check_s_output() -> None:
    """Table 7 is tools/tax_check.py on this document's snapshot, row by row,
    and the sentences beside it say what the table says."""
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "tools"))
    import tax_check

    doc = _doc()
    laws, means, costs = [], [], []
    for years in tax_check.YEARS:
        law = tax_check.law_ratio(years)
        mean_only = tax_check.mean_only_ratio(years)
        cost = tax_check.cost_of_ignoring(years)
        loss = tax_check.loss_probability(years)
        laws.append(law)
        means.append(mean_only)
        costs.append(cost)
        row = (f'<tr><td class="num">{years}</td><td class="num">{law:.3f}</td>'
               f'<td class="num">{mean_only:.3f}</td><td class="num">{cost:.2f}</td>'
               f'<td class="num">{loss:.1%}</td></tr>')
        assert row in doc, row
    assert round(1 - laws[0], 2) == 0.25                      # "about a quarter"
    assert abs((1 - laws[1]) - 1 / 9) < 0.01                 # "about a ninth"
    assert all(1 - law < 0.1 for law in laws[2:])            # "under a tenth beyond"
    assert costs[0] < 2 and max(costs[1:]) < 0.5             # "under 2", "under half"
    # "about three tenths against the law's quarter ... nearer to it than
    # leaving tax out", and "between two and a little over four times what
    # the law does" from seven years.
    assert round(1 - means[0], 1) == 0.3 and laws[0] - means[0] < 1 - laws[0]
    ratios = [(1 - m) / (1 - l) for m, l in zip(means[1:], laws[1:])]
    assert min(ratios) >= 2 and 4 < max(ratios) < 4.25
    assert f"by {round((1 - max(means)) * 100)}% to {round((1 - min(means)) * 100)}%" in doc
    for gamma in (3.0, 8.0):                                 # "within a hundredth"
        for years, law in zip(tax_check.YEARS, laws):
            assert abs(tax_check.law_ratio(years, gamma) - law) < 0.01
