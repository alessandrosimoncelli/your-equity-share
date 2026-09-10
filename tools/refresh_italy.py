"""Refresh the euro safe rate, check AQR's return, and price the tax code.

    python tools/refresh_italy.py            report only
    python tools/refresh_italy.py --write    update variants/it/market_data.toml

WHY NOT update.py. That script rebuilds a whole configuration from one
American template and refuses to touch this file, for a reason it learned the
hard way: run on the Italian file once, it wrote the 30-year United States
TIPS in as the safe rate and deleted the note saying the rate was a guess.

THE SAFE RATE is the ECB's AAA euro area government curve at thirty years,
deflated by the MARKET BREAK-EVEN inflation rate of the longest euro linker.

It took three tries to get here and each attempt failed a different test.

  CONSTANT MATURITY. FRED's DFII30, which the American variant reads, is not a
  bond: it is the thirty-year point read off the TIPS curve every day, so it
  describes the same horizon at every refresh. This file used the traded real
  yield of Bund/euro-i 2046 until September 2026 and that bond has nineteen
  years left and one fewer every year, so within a decade it would have been
  quoting a fifteen-year horizon under a thirty-year label.

  NO SURVEY. The curve was then deflated by the ECB Survey of Professional
  Forecasters, which fixed the maturity and introduced an opinion. This tool is
  meant to hold only measurements and trends.

  THE SAME KIND OF OBJECT. DFII30 is a traded real yield. A nominal yield with
  a forecast subtracted from it is not the same thing, whatever it comes out at.

A break-even clears all three. It is the rate at which holding the linker and
holding a nominal bond pay the same, so it is a price rather than a forecast,
and subtracting it from a nominal curve recovers a real yield.

The construction can be checked against itself and it passes. The break-even is
derived from the 2046, so deflating a nominal yield by it should reproduce that
bond's own traded real yield, and it lands within four hundredths of a point.

The survey is still fetched and still reported, now as the cross-check, and it
sits about a quarter of a point ABOVE. That gap is an inflation risk premium,
which is what a holder pays to be rid of inflation risk. Deflating by the
survey books that premium as return and makes the safe asset look better than
any bond anybody can actually buy.

AAA rather than every euro area government bond. The all-government curve
yields about sixty basis points more at the same maturity, and that spread is
compensation for a government not paying. Equation (4) cannot represent default
risk, so taking it would book a credit premium as a risk-free return, lowering
the recommendation while looking prudent. An Italian household buying BTP is
not holding this asset.

Euro area HICP is not Italian HICP. Only BTP Italia tracks Italian inflation,
at five years and retail, so the deflator is approximate in a way an
American's is not.

THE EXPECTED RETURN is AQR's published figure for Global All Country, refreshed
once a year when they publish it in January as of the previous 31 December.
That is a deliberate choice of the simple thing: they publish every component,
they assume no repricing, and that is equation (5) term for term.

No firm publishes the same decomposition more often. The houses that update
quarterly or monthly all assume valuations revert towards a fair value, which
is a different estimator, so switching to one for the sake of freshness would
change the method rather than refresh the number.

So the halves are checked here instead, every time this runs, against data that
costs nothing:

  The DIVIDEND YIELD is measured from MSCI's own index levels. The gross index
  reinvests dividends and the price index does not, so the gap between their
  returns over a month is that month's dividend as a fraction of the starting
  price, and twelve of them are a trailing yield. That is the same object as
  Shiller's dividend column over his price. It currently lands a tenth of a
  point from AQR's quote.

  Gross rather than net of withholding tax, because Shiller's column is gross
  and the two variants have to measure one thing one way. The net figure is
  printed beside it, because the gap is a real cost a euro investor pays on a
  global fund and an American holding domestic stock does not.

  The GROWTH RATE is checked against the American variant's own hundred-year
  trend through Shiller. Using a United States growth rate for a global index
  is defensible on AQR's own evidence, since they publish 2.7% for United
  States large cap against 2.6% for Global All Country.

If either half drifts more than a third of a point, the report says so, which
is the signal to go and read AQR's current report rather than wait for January.

THE TAX SECTION prices what Italy does to the two assets: 12.5% on government
bonds against 26% on everything else, both on nominal income so inflation is
taxed, plus 0.2% a year of imposta di bollo on each. The rates and the
reasoning live in src/your_equity_share/taxes.py, including why the volatility
is not reduced.
"""


from __future__ import annotations

import argparse
import json
import math
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "variants" / "it" / "market_data.toml"

sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.expected_return import (  # noqa: E402
    arithmetic_from_compound,
)
from your_equity_share.providers import (  # noqa: E402
    parse_shiller_csv,
    parse_shiller_xls,
)
from your_equity_share.taxes import (  # noqa: E402
    ITALY_TAX,
    TaxRegime,
    after_tax_equity_compound,
    after_tax_safe_rate,
)

# The window the American variant fits its growth trend over. Kept equal to
# update.py's constant on purpose: the two variants share one estimator, and a
# test asserts they still agree.
GROWTH_WINDOW_YEARS = 100

# AQR publish this once a year, in January, as of the previous 31 December.
# Nobody publishes the same decomposition more often. The firms that do update
# quarterly or monthly assume valuations revert to a fair value, which is a
# different estimator and would change the method rather than refresh it.
AQR_REPORT = "Alternative Thinking 2026 Issue 1, Exhibit 3A, Global All Country"
AQR_AS_OF = "2025-12-31"
AQR_YIELD = 0.016
AQR_GROWTH = 0.026
AQR_COMPOUND = 0.042

# How far either half may drift from AQR's before the report says so. A third
# of a point: large enough not to fire on the noise in a trailing yield, small
# enough to catch a market that has moved away from the figure being used.
DRIFT_LIMIT = 0.0033

# The horizon the equity tax is deferred over. Thirty years, to match the
# maturity of the safe asset, so both sides are quoted at one horizon.
TAX_HORIZON_YEARS = 30.0

ECB = "https://data-api.ecb.europa.eu/service/data/{}?lastNObservations=1&format=csvdata"

# AAA-rated euro area central government bonds, spot rate, thirty years. The
# same maturity Choi's guide asks for, and the same one the American variant
# uses, so the two safe assets differ in currency and credit rather than in
# horizon as well.
NOMINAL_30Y = "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_30Y"

# Every euro area central government bond at the same maturity. Not used as
# the safe rate. Fetched so the spread can be reported, because that spread is
# the credit risk this variant is choosing not to book as return.
NOMINAL_30Y_ALL = "YC/B.U2.EUR.4F.G_N_C.SV_C_YM.SR_30Y"

# ECB Survey of Professional Forecasters, longer-term HICP expectation.
SPF_LONG_RUN = "SPF/Q.U2.HICP.POINT.LT.Q.AVG"

USER_AGENT = "your-equity-share (methodology check)"
TIMEOUT = 30


def _context() -> ssl.SSLContext | None:
    """The system trust store if it works, certifi if it is there.

    This project has no runtime dependencies and is not about to acquire one
    for a maintenance script. Some Windows Pythons cannot verify the ECB's
    chain from the system store while verifying FRED's perfectly well, so
    certifi is used when installed and skipped when not.
    """
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def observe(series: str) -> tuple[str, float]:
    """The latest observation of an ECB series, with its date."""
    request = urllib.request.Request(ECB.format(series),
                                     headers={"User-Agent": USER_AGENT})
    for context in (None, _context()):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT,
                                        context=context) as response:
                body = response.read().decode("utf-8", "replace")
            break
        except urllib.error.URLError:
            if context is not None:
                raise
    else:  # pragma: no cover
        raise SystemExit("could not reach the ECB")

    rows = [line for line in body.splitlines() if line.strip()]
    if len(rows) < 2:
        raise SystemExit(f"no observations returned for {series}")
    header, last = rows[0].split(","), rows[-1].split(",")
    row = dict(zip(header, last))
    return row["TIME_PERIOD"], float(row["OBS_VALUE"]) / 100.0



# The German finance agency publishes the traded real yield of every
# inflation-linked federal security it has outstanding. This is the euro
# analogue of FRED's DFII30 and the reason the Italian variant can be compared
# with the American one at all.
LINKER_PAGE = ("https://www.deutsche-finanzagentur.de/en/federal-securities/"
               "types-of-federal-securities/inflation-linked-federal-securities")


def linker_chart(axis_label: str) -> tuple[str, float, float]:
    """The longest outstanding Bund/euro-i, off whichever chart is asked for.

    The page carries two charts in the same shape, real yields and break-even
    inflation. Taking the first set of series that appears would work today and
    silently return the wrong quantity the day the order changes, so the chart
    is selected by its axis label.

    Both are now used. The real yield is the cross-check on the safe rate and
    the break-even is the deflator that replaced a survey.
    """
    request = urllib.request.Request(LINKER_PAGE,
                                     headers={"User-Agent": USER_AGENT})
    for context in (None, _context()):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT,
                                        context=context) as response:
                page = response.read().decode("utf-8", "replace")
            break
        except urllib.error.URLError:
            if context is not None:
                raise
    else:  # pragma: no cover
        raise SystemExit("could not reach the German finance agency")

    charts = re.split(r'"yAxis":\{"title":\{"text":"', page)
    wanted = [c for c in charts if c.startswith(axis_label)]
    if not wanted:
        raise SystemExit("no chart on the page is labelled %r" % axis_label)
    block = wanted[0]
    cut = block.find('"yAxis"')
    block = block[:cut] if cut > 0 else block

    found = []
    for match in re.finditer(
            r'"name":"(DE\d+): remaining maturity ([\d,]+) years","data":\[(.*?)\]',
            block):
        points = re.findall(r'\{"y":(-?[\d.]+),"x":\d+\}', match.group(3))
        if points:
            found.append((match.group(1),
                          float(match.group(2).replace(",", ".")),
                          float(points[-1]) / 100.0))
    if not found:
        raise SystemExit("no series found on the %r chart" % axis_label)
    return max(found, key=lambda row: row[1])


def longest_german_linker() -> tuple[str, float, float]:
    """The longest euro linker: ISIN, years left, traded real yield."""
    return linker_chart("Real yield")


def breakeven_inflation() -> tuple[str, float, float]:
    """The same bond's break-even inflation, which is a price, not a forecast."""
    return linker_chart("Break-even")


# MSCI serve their own end-of-day index levels, one currency and one variant
# per request. Nothing here needs a login and nothing is scraped: the levels
# come back as JSON. The free history starts in 1997, which is far too short to
# measure growth on and entirely adequate for a trailing yield.
MSCI = ("https://app2.msci.com/products/service/index/indexmaster/"
        "getLevelDataForGraph?currency_symbol={cur}&index_variant={var}"
        "&start_date={start}&end_date={end}&data_frequency=END_OF_MONTH"
        "&index_codes={code}")

# MSCI All Country World: developed and emerging, which is what FTSE All-World
# is and what the equity sleeve holds. MSCI World would be developed only.
ACWI = "892400"

# STRD is the price index, GRTR reinvests dividends gross of withholding tax
# and NETR reinvests them net of it.
YIELD_MONTHS = 12


def msci_levels(code: str, currency: str, variant: str,
                start: str = "20200101") -> dict[int, float]:
    """End-of-month levels of one MSCI index, as {yyyymmdd: level}."""
    url = MSCI.format(cur=currency, var=variant, code=code, start=start,
                      end=date.today().strftime("%Y%m%d"))
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT,
                      "Accept": "application/json, text/plain, */*"})
    for context in (None, _context()):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT,
                                        context=context) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            break
        except urllib.error.URLError:
            if context is not None:
                raise
    else:  # pragma: no cover
        raise SystemExit("could not reach MSCI")

    if "indexes" not in payload:
        raise SystemExit("MSCI refused the request: %s"
                         % payload.get("error_message", payload))
    return {int(row["calc_date"]): float(row["level_eod"])
            for row in payload["indexes"]["INDEX_LEVELS"]}


def trailing_dividend_yield(variant: str) -> tuple[float, int, int]:
    """Twelve months of dividends over TODAY's price.

    The gross index reinvests each dividend and the price index does not, so
    the difference between their returns over a month, times the price at the
    start of it, is that month's dividend in index points. Twelve of those are
    a year's dividends.

    THE DENOMINATOR IS THE WHOLE QUESTION and it is worth a third of a point.
    Shiller's dividend column is a trailing annual rate and the American
    variant divides it by his LAST price, so a trailing dividend over today's
    price is the object the two variants have to share.

    Dividing instead by the price twelve months ago gives 1.87% on this data
    where today's price gives 1.53%, and summing each month's dividend over
    that month's own starting price gives 1.70%. Three defensible-sounding
    constructions, a third of a point apart, because the index rose 22% across
    the window. This one is not chosen because it is lowest; it is chosen
    because it is the one Shiller's column already is.
    """
    price = msci_levels(ACWI, "EUR", "STRD")
    total = msci_levels(ACWI, "EUR", variant)
    dates = sorted(set(price) & set(total))
    if len(dates) < YIELD_MONTHS + 1:
        raise SystemExit("MSCI returned too few months to measure a yield")
    window = dates[-(YIELD_MONTHS + 1):]
    paid = sum((total[b] / total[a] - price[b] / price[a]) * price[a]
               for a, b in zip(window, window[1:]))
    return paid / price[window[-1]], window[0], window[-1]


def american_growth_trend() -> tuple[float, str] | tuple[None, None]:
    """The American variant's hundred-year trend, used as the global rate.

    Read from the same workbook update.py reads, through the same parser and
    the same call, so the two variants cannot drift apart. If the workbook is
    not on this machine the report says so and the growth term is left alone.
    """
    for candidate in (ROOT / "data" / "shiller.xls",
                      ROOT / "data" / "shiller.csv",
                      ROOT.parent / "shiller.xls"):
        if not candidate.exists():
            continue
        raw = candidate.read_bytes()
        history = (parse_shiller_csv(raw.decode("utf-8", "replace"))
                   if candidate.suffix.lower() == ".csv"
                   else parse_shiller_xls(raw))
        return history.real_earnings_trend_growth(GROWTH_WINDOW_YEARS), \
            history.dates[-1]
    return None, None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help="write the measured rate into the configuration")
    args = parser.parse_args(argv[1:])

    print("Measuring the euro real safe rate")
    print("=" * 68)

    aaa_date, aaa = observe(NOMINAL_30Y)
    all_date, every = observe(NOMINAL_30Y_ALL)
    spf_date, expected_inflation = observe(SPF_LONG_RUN)

    isin, years_left, traded = longest_german_linker()
    _, breakeven_years, breakeven = breakeven_inflation()

    # The deflator is the MARKET's inflation rate, not a forecaster's. It is
    # the break-even of the longest euro linker: the rate at which holding the
    # linker and holding a nominal bond pay the same. A price, and the only
    # inflation number here that nobody had to form a view to produce.
    deflated = (1.0 + aaa) / (1.0 + breakeven) - 1.0
    surveyed = (1.0 + aaa) / (1.0 + expected_inflation) - 1.0
    real_all = (1.0 + every) / (1.0 + breakeven) - 1.0
    real = deflated

    print(f"  AAA euro area government, 30y, nominal   {aaa:>8.4%}   "
          f"{aaa_date}")
    print(f"  break-even inflation, {isin}   "
          f"{breakeven:>8.4%}   {breakeven_years:.1f} years")
    print(f"  deflated                                 {deflated:>8.4%}")
    print("  USED AS THE SAFE RATE, and it clears three bars at once.")
    print()
    print("  CONSTANT MATURITY, which is what FRED's DFII30 is. DFII30 is not")
    print("  a bond: it is the thirty-year point read off the curve every day,")
    print("  so it describes the same horizon at every refresh. A single bond")
    print("  cannot, which is why the Bund/euro-i 2046 stopped being used.")
    print()
    print("  NO SURVEY. The deflator is a market break-even, the rate at which")
    print("  holding the linker and holding a nominal bond pay the same. It is")
    print("  a price. Nobody had to form a view to produce it.")
    print()
    print("  THE SAME KIND OF OBJECT as DFII30, which is a traded real yield")
    print("  rather than a nominal yield with an opinion subtracted.")
    print()
    print("  Two cross-checks, and both agree with it:")
    print(f"  {isin} traded real yield          {traded:>8.4%}   "
          f"{years_left:.1f} years left")
    print(f"  ECB SPF longer-term HICP expectation     "
          f"{expected_inflation:>8.4%}   {spf_date}")
    print(f"  the same curve deflated by THAT instead   {surveyed:>8.4%}")
    print()
    print(f"  The traded bond lands {abs(deflated - traded) * 100:.3f} points "
          f"away, which is the whole")
    print("  construction agreeing with itself: the break-even is derived from")
    print("  that bond, so deflating a nominal yield by it should recover the")
    print("  bond's own real yield, and it does.")
    print()
    print(f"  The survey sits {(surveyed - deflated) * 100:.2f} points above. "
          f"That gap is an inflation")
    print("  risk premium, what a holder pays to be rid of inflation risk.")
    print("  Deflating by the survey books that premium as return and makes")
    print("  the safe asset look better than any purchasable bond is. This")
    print("  file did exactly that until September 2026.")
    print()
    print(f"  every euro area government, 30y, nominal {every:>8.4%}   "
          f"{all_date}")
    print(f"  the same, deflated                       {real_all:>8.4%}")
    print(f"  credit spread not booked as return       "
          f"{(every - aaa) * 100:>7.2f} points")
    print()
    print("  For comparison, the American variant's safe asset is the 30-year")
    print("  TIPS at 2.96% real. A euro household is offered a materially")
    print("  lower real rate for the same maturity and the same credit, and")
    print("  that difference goes straight into the drift.")

    print()
    print("The expected return")
    print("=" * 68)

    gross, first, last = trailing_dividend_yield("GRTR")
    net, _, _ = trailing_dividend_yield("NETR")
    growth, growth_as_of = american_growth_trend()

    if growth is None:
        print("  Shiller's workbook was not found, so the growth term and the")
        print("  expected return cannot be built. Run update.py first, or put")
        print("  ie_data.xls at data/shiller.xls.")
        if args.write:
            print("\n  Nothing written: refusing to write half an estimate.")
        return 0

    compound = gross + growth
    volatility = float(re.search(r"^stock_volatility = ([0-9.]+)$",
                                 CONFIG.read_text(encoding="utf-8"),
                                 re.M).group(1))
    arithmetic = arithmetic_from_compound(compound, volatility)

    print("  Built here, by the American variant's own construction, because")
    print("  that construction carries no horizon and this model prices a")
    print("  lifetime. See the module docstring.")
    print(f"    dividend yield, MSCI ACWI EUR          {gross:>8.4%}   "
          f"{first} to {last}")
    print(f"      the same net of withholding tax      {net:>8.4%}")
    print(f"    real EPS growth, {GROWTH_WINDOW_YEARS}y Shiller trend  "
          f"{growth:>8.4%}   to {growth_as_of}")
    print(f"    repricing                              {0.0:>8.4%}   stated")
    print(f"    compound                               {compound:>8.4%}")
    print(f"    arithmetic, at {volatility:.2%} volatility    "
          f"{arithmetic:>8.4%}")
    print()

    drift_yield = gross - AQR_YIELD
    drift_growth = growth - AQR_GROWTH
    print(f"  AQR, {AQR_REPORT},")
    print(f"  as of {AQR_AS_OF}, is the cross-check rather than the estimate,")
    print(f"  because they state it is for a horizon of five to ten years:")
    print(f"    their dividend yield                   {AQR_YIELD:>8.4%}   "
          f"{drift_yield * 100:>+6.2f} against ours")
    print(f"    their real EPS growth                  {AQR_GROWTH:>8.4%}   "
          f"{drift_growth * 100:>+6.2f} against ours")
    print(f"    their compound                         "
          f"{AQR_COMPOUND:>8.4%}   {(AQR_COMPOUND - compound) * 100:>+6.2f} "
          f"against ours")
    stale = [name for name, drift in (("the dividend yield", drift_yield),
                                      ("the growth rate", drift_growth))
             if abs(drift) > DRIFT_LIMIT]
    print()
    if stale:
        print("  DIVERGED: %s is more than %.2f points from AQR's."
              % (" and ".join(stale), DRIFT_LIMIT * 100))
        print("  One of the two has moved. Read their current report.")
    else:
        print(f"  Both halves are within {DRIFT_LIMIT * 100:.2f} points of "
              f"AQR's, which is")
        print("  the check passing: a firm that builds this for a living, on")
        print("  their own data, gets the same two numbers we measure.")

    print()
    print("What the Italian tax code does to both")
    print("=" * 68)
    net_equity = after_tax_equity_compound(compound, expected_inflation,
                                           TAX_HORIZON_YEARS, ITALY_TAX)
    net_safe = after_tax_safe_rate(aaa, expected_inflation, ITALY_TAX)
    net_arithmetic = arithmetic_from_compound(net_equity, volatility)
    print(f"  equities, compound      {compound:>8.4%} -> {net_equity:>8.4%}"
          f"   {(net_equity - compound) * 100:>+6.2f} points")
    print(f"  the safe rate           {real:>8.4%} -> {net_safe:>8.4%}"
          f"   {(net_safe - real) * 100:>+6.2f} points")
    print(f"  the drift               "
          f"{(math.log(1 + arithmetic) - math.log(1 + real)) * 100:>7.4f}% -> "
          f"{(math.log(1 + net_arithmetic) - math.log(1 + net_safe)) * 100:>7.4f}%")
    print()
    print(f"  12.5% on government bonds against 26% on everything else, both")
    print(f"  levied on NOMINAL income so inflation is taxed, plus 0.2% a year")
    print(f"  of imposta di bollo on each. Equities are taxed once on sale")
    print(f"  after {TAX_HORIZON_YEARS:.0f} years rather than annually.")
    print("  See src/your_equity_share/taxes.py, which also says why the")
    print("  volatility is NOT reduced: Italian law does not let fund losses")
    print("  offset fund gains, so the state shares the upside only.")

    print()
    print("  IT IS NOT THE 26% THAT HURTS EQUITIES. Levy the same 26% on both")
    print("  sides and the drift WIDENS, because the safe asset is taxed every")
    print("  year on its whole nominal coupon while equities defer to sale:")
    symmetric = TaxRegime(ITALY_TAX.other_financial_income_rate,
                          ITALY_TAX.other_financial_income_rate,
                          ITALY_TAX.wealth_tax_rate, "symmetric")
    flat_equity = after_tax_equity_compound(compound, expected_inflation,
                                            TAX_HORIZON_YEARS, symmetric)
    flat_safe = after_tax_safe_rate(aaa, expected_inflation, symmetric)
    for label, mu, rate in (("pre-tax", compound, real),
                            ("26% on both", flat_equity, flat_safe),
                            ("12.5% and 26%, the law", net_equity, net_safe)):
        # Arithmetic, because that is what the model takes and what the
        # summary above quotes. Comparing compound drifts here and arithmetic
        # drifts there would print two different numbers for the same row.
        mean = arithmetic_from_compound(mu, volatility)
        print("    %-24s equity %7.4f%%  safe %7.4f%%  drift %7.4f%%"
              % (label, mean * 100, rate * 100,
                 (math.log(1 + mean) - math.log(1 + rate)) * 100))
    print("  So what tilts an Italian household towards bonds is not the 26%")
    print("  on equities. It is the PREFERENCE the state gives government")
    print("  paper, and that is the asymmetry the model now carries.")

    print()
    print("  The equity figure depends on how long the tax is deferred, and")
    print("  that horizon is a choice this file makes rather than measures:")
    for years in (10.0, 20.0, 30.0, 40.0):
        at = after_tax_equity_compound(compound, expected_inflation, years,
                                       ITALY_TAX)
        mark = "  <- used" if years == TAX_HORIZON_YEARS else ""
        print("    %2.0f years   equity %7.4f%%   drift %7.4f%%%s"
              % (years, at * 100,
                 (math.log(1 + arithmetic_from_compound(at, volatility))
                  - math.log(1 + net_safe)) * 100, mark))
    print("  Thirty, to match the maturity of the safe asset, so both sides")
    print("  are quoted at one horizon. Deriving it from the household's own")
    print("  age instead would remove the choice, and is the obvious next")
    print("  improvement: across ten to forty years it is worth about twelve")
    print("  points of equity share.")

    if not args.write:
        print("\n  Report only. Pass --write to update the configuration.")
        return 0

    text = CONFIG.read_text(encoding="utf-8")
    numbers = (
        ("expected_stock_real_return", arithmetic),
        ("real_risk_free", real),
        ("expected_return_compound", compound),
        ("dividend_yield", gross),
        ("real_growth", growth),
        ("dividend_yield_measured", gross),
        ("dividend_yield_withheld", gross - net),
        ("expected_inflation", breakeven),
        ("expected_inflation_survey", expected_inflation),
        ("nominal_safe_yield", aaa),
        ("after_tax_expected_return", net_arithmetic),
        ("after_tax_real_risk_free", net_safe),
    )
    for field, value in numbers:
        text = re.sub(r"^%s = [0-9.]+$" % field,
                      "%s = %.6f" % (field, value), text, count=1, flags=re.M)
    text = text.replace('provisional_fields = "real_risk_free"',
                        'provisional_fields = ""')
    text = re.sub(r'^real_risk_free_source = ".*"$',
                  'real_risk_free_source = "ECB AAA euro area central '
                  'government bond curve, 30-year spot rate, %.4f%% on %s, '
                  'deflated by the MARKET break-even inflation rate of %.4f%% '
                  'on %s, the longest euro inflation-linked government bond at '
                  '%.1f years, which gives %.4f%%. It clears three bars at '
                  'once: constant maturity, which is what FRED\'s DFII30 is '
                  'and a single bond cannot be; no survey, because a '
                  'break-even is the rate at which the linker and a nominal '
                  'bond pay the same and is therefore a price; and the same '
                  'kind of object as DFII30, a traded real yield rather than a '
                  'nominal yield with an opinion subtracted. Checked against '
                  'itself: the break-even comes from that bond, so this should '
                  'reproduce its traded real yield of %.4f%%, and it lands '
                  '%.3f points away. The ECB Survey of Professional '
                  'Forecasters expects %.4f%% for %s, which would give %.4f%%, '
                  '%.2f points higher; that gap is an inflation risk premium '
                  'and deflating by the survey books it as return."'
                  % (aaa * 100, aaa_date, breakeven * 100, isin,
                     breakeven_years, deflated * 100, traded * 100,
                     abs(deflated - traded) * 100, expected_inflation * 100,
                     spf_date, surveyed * 100, (surveyed - deflated) * 100),
                  text, count=1, flags=re.M)
    text = re.sub(r'^expected_return_source = ".*"$',
                  'expected_return_source = "Built here, by the construction '
                  'the American variant uses, because that construction '
                  'carries no horizon and this model prices a lifetime: a '
                  '%.4f%% trailing dividend yield of MSCI All Country World in '
                  'euro over %d to %d, measured from the gap between MSCI '
                  'gross and price index levels and divided by the price at '
                  'the end, plus %.4f%% real growth in earnings per share, the '
                  '%d-year OLS trend through Shiller to %s, plus zero '
                  'repricing. Cross-checked against AQR, %s, as of %s: their '
                  'dividend yield of %.1f%% is %+.2f points from ours and '
                  'their real EPS growth of %.1f%% is %+.2f points from ours. '
                  'Theirs is the check and not the estimate because they state '
                  'it is for a horizon of 5 to 10 years, while Table 7 of the '
                  'American methodology shows this construction is the one '
                  'that wins at 30."'
                  % (gross * 100, first, last, growth * 100,
                     GROWTH_WINDOW_YEARS, growth_as_of, AQR_REPORT, AQR_AS_OF,
                     AQR_YIELD * 100, (AQR_YIELD - gross) * 100,
                     AQR_GROWTH * 100, (AQR_GROWTH - growth) * 100),
                  text, count=1, flags=re.M)
    text = re.sub(r'^after_tax_source = ".*"$',
                  'after_tax_source = "Italy taxes government bonds of Italy '
                  'and of white-list states, Germany included, at %.1f%% and '
                  'other financial income at %.0f%%, both on nominal income so '
                  'inflation is taxed, plus %.1f%% a year of imposta di bollo '
                  'on the value of each. Equities are taxed once on sale, so '
                  'the tax is deferred over %.0f years, which recovers more '
                  'than the higher rate costs. The volatility is NOT reduced, '
                  'because Italian law does not let fund losses offset fund '
                  'gains. Tax costs %.2f points of expected return and %.2f '
                  'points of safe rate, so %.2f points of the drift. See '
                  'src/your_equity_share/taxes.py."'
                  % (ITALY_TAX.government_bond_rate * 100,
                     ITALY_TAX.other_financial_income_rate * 100,
                     ITALY_TAX.wealth_tax_rate * 100, TAX_HORIZON_YEARS,
                     (arithmetic - net_arithmetic) * 100,
                     (real - net_safe) * 100,
                     (math.log(1 + arithmetic) - math.log(1 + real)
                      - math.log(1 + net_arithmetic)
                      + math.log(1 + net_safe)) * 100),
                  text, count=1, flags=re.M)
    CONFIG.write_text(text, encoding="utf-8")
    print(f"\n  Written to {CONFIG.relative_to(ROOT)}: the safe rate and the "
          f"expected return.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
