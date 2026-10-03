"""Refresh the euro safe rate and the expected return, and check AQR's.

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

Two conventions are matched before the subtraction. The ECB publishes its
curve CONTINUOUSLY COMPOUNDED ("The continuous method is used to compound
interest rates", ECB technical notes on the euro area yield curves), so the
spot rate is annualised first, because the model reads annual rates. The
Finanzagentur defines its break-even as a SIMPLE YIELD DIFFERENCE between the
linker and the nominal Bund nearest in maturity, so it is subtracted, not
divided out.

The construction can be checked against itself. The break-even is derived from
the 2046, so subtracting it from a nominal yield should come close to that
bond's own traded real yield. It does, within about a tenth of a point; the
rest is maturity, a thirty-year nominal leg against a nineteen-year inflation
leg.

The survey is still fetched and still reported, as the cross-check. When it
sits below the break-even the gap is an inflation risk premium, which a
deflation by the survey would book as return; when it sits above, the
break-even's own liquidity premium is the likelier reason. Either way the
safe rate rests on the price, not on the forecast.

AAA rather than every euro area government bond. The all-government curve
yields about sixty basis points more at the same maturity, and that spread is
compensation for a government not paying. Equation (4) cannot represent default
risk, so taking it would book a credit premium as a risk-free return, lowering
the recommendation while looking prudent. An Italian household buying BTP is
not holding this asset.

Euro area HICP is not Italian HICP. Only BTP Italia tracks Italian inflation,
at five years and retail, so the deflator is approximate in a way an
American's is not.

THE EXPECTED RETURN is built here, by the construction the American variant
uses, and AQR's published figure is the cross-check rather than the estimate.

This file took AQR's 4.20% whole until September 2026. What ended that is
their own sentence about it: "We present local real (inflation-adjusted) and
nominal annual compound rates of return for a horizon of 5 to 10 years. For
multi-decade forecast horizons their impact is diluted, so theory and long-term
historical averages may matter more in judging expected returns." Both halves
of their number are built to ten years and this model prices a lifetime.

A current yield plus a long-run growth rate with no repricing carries no
horizon at all, because nothing in it forecasts when anything happens. It is
the same number at ten years or at thirty, and Table 7 of the American
methodology shows it is also the one with the lowest error at thirty.

  The DIVIDEND YIELD is measured from MSCI's own index levels. The gross index
  reinvests dividends and the price index does not, so the gap between their
  returns over a month is that month's dividend, and twelve of those over
  TODAY's price are a trailing yield. Over today's price because that is the
  denominator Shiller's column already has: the three plausible denominators
  differ by a third of a point.

  NET of withholding tax, from MSCI's net index. Withholding is taken at the
  source before the dividend reaches the fund, so no Italian holder, taxed or
  exempt, ever receives it: it is a property of the fund, like its price, not
  the household's own tax (which the model leaves out, taxes.py). An American
  holding domestic stock pays none, so Shiller's gross column is the same
  measurement for the American variant. The gross figure is kept for the
  comparison with AQR, who publish gross.

  The GROWTH RATE is the American variant's own hundred-year trend through
  Shiller, used unchanged. tools/us_vs_global.py measures what that
  substitution costs and finds it biases the growth term up by a tenth to half
  a point.

AQR's two halves are still fetched and compared on every run. If either drifts
more than a third of a point from ours, the report says so, which is the signal
that one of the two has moved and their current report is worth reading.

Tax is not applied: the model reads the figures before tax, as Choi does, and
src/your_equity_share/taxes.py says why.
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
from datetime import date, datetime, timezone
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

# The volatility is FIXED, not re-measured each week. Choi, Liu and Liu treat
# it as one long-run constant (18.5%, monthly CRSP, 1926 to 2024), and a
# trailing five-year window turned it into a lumpy regime variable: when the
# 2020 crash left the window in February and March 2025 the answer for an
# uncapped household jumped about nine points in five weeks with no change in
# long-run risk. This is the same convention on the fund's own index: the
# annualised standard deviation of monthly log returns of MSCI All Country
# World in euro, gross, December 2000 to August 2026 (Italian methodology,
# section 6). It is written once and refreshed only by hand.
ITALY_VOLATILITY = 0.139860

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


def linker_chart(axis_label: str) -> tuple[str, float, float, date]:
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
        points = re.findall(r'\{"y":(-?[\d.]+),"x":(\d+)\}', match.group(3))
        if points:
            # x is milliseconds since 1970, stamped at midnight Frankfurt
            # time, which is late the evening before in UTC; half a day on
            # lands it on the right date.
            when = datetime.fromtimestamp(int(points[-1][1]) / 1000 + 43200,
                                          timezone.utc).date()
            found.append((match.group(1),
                          float(match.group(2).replace(",", ".")),
                          float(points[-1][0]) / 100.0, when))
    if not found:
        raise SystemExit("no series found on the %r chart" % axis_label)
    return max(found, key=lambda row: row[1])


def longest_german_linker() -> tuple[str, float, float, date]:
    """The longest euro linker: ISIN, years left, traded real yield."""
    return linker_chart("Real yield")


def breakeven_inflation() -> tuple[str, float, float, date]:
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


# The ECB curve and the break-even are read on different pages. Their dates
# can differ by a weekend or a holiday, not by weeks.
BREAKEVEN_MAX_LAG_DAYS = 10


def optional(fetch, *args):
    """A cross-check the model does not read: None when its source fails, so
    an outage there is reported instead of stopping the refresh."""
    try:
        return fetch(*args)
    except (SystemExit, urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help="write the measured rate into the configuration")
    args = parser.parse_args(argv[1:])

    print("Measuring the euro real safe rate")
    print("=" * 68)

    aaa_date, aaa_continuous = observe(NOMINAL_30Y)
    # The ECB quotes its Svensson curve continuously compounded; the model
    # reads annual rates, so annualise before anything else touches them.
    aaa = math.expm1(aaa_continuous)
    isin, breakeven_years, breakeven, breakeven_date = breakeven_inflation()
    # A chart that stopped updating would deflate today's nominal yield by an
    # old break-even under a fresh date, so the two have to be days apart at
    # most, not weeks.
    lag = abs((date.fromisoformat(aaa_date) - breakeven_date).days)
    if lag > BREAKEVEN_MAX_LAG_DAYS:
        raise SystemExit(
            "the break-even is dated %s and the ECB curve %s, %d days apart; "
            "refusing to deflate one by the other" % (breakeven_date, aaa_date, lag))

    # Cross-checks only. The model reads none of them, so a source that fails
    # here is reported and skipped rather than allowed to stop the refresh.
    every_obs = optional(observe, NOMINAL_30Y_ALL)
    spf = optional(observe, SPF_LONG_RUN)
    linker = optional(longest_german_linker)
    spf_date, survey_inflation = spf if spf else (None, None)
    traded, years_left = (linker[2], linker[1]) if linker else (None, None)

    # The deflator is the MARKET's inflation rate, not a forecaster's. It is
    # the break-even of the longest euro linker: the rate at which holding the
    # linker and holding a nominal bond pay the same. A price, and the only
    # inflation number here that nobody had to form a view to produce. The
    # Finanzagentur publishes it as a simple yield difference, so it comes off
    # by subtraction. The survey is a forecast, so it is divided out.
    deflated = aaa - breakeven
    real = deflated

    print(f"  AAA euro area government, 30y, nominal   {aaa:>8.4%}   "
          f"{aaa_date}, {aaa_continuous:.4%} continuously compounded")
    print(f"  break-even inflation, {isin}   "
          f"{breakeven:>8.4%}   {breakeven_years:.1f} years")
    print(f"  less the break-even                      {deflated:>8.4%}")
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
    print("  Cross-checks, not used:")
    if linker:
        print(f"  {isin} traded real yield          {traded:>8.4%}   "
              f"{years_left:.1f} years left")
        print(f"    {(deflated - traded) * 100:+.3f} points from the safe rate. The "
              f"break-even comes from that bond,")
        print("    so the two should be close; the rest is a 30-year nominal leg")
        print("    against a shorter inflation leg.")
    else:
        print("  the traded real yield of the longest linker: unavailable")
    if spf:
        surveyed = (1.0 + aaa) / (1.0 + survey_inflation) - 1.0
        print(f"  ECB SPF longer-term HICP expectation     "
              f"{survey_inflation:>8.4%}   {spf_date}")
        print(f"  the same curve deflated by THAT instead   {surveyed:>8.4%}   "
              f"{(surveyed - deflated) * 100:+.2f} points")
        print("    The safe rate rests on the break-even because it is a price;")
        print("    the survey is an opinion.")
    else:
        print("  the ECB SPF longer-term expectation: unavailable")
    if every_obs:
        all_date, every_continuous = every_obs
        every = math.expm1(every_continuous)
        print(f"  every euro area government, 30y, nominal {every:>8.4%}   "
              f"{all_date}")
        print(f"  the same, less the break-even            {every - breakeven:>8.4%}")
        print(f"  credit spread not booked as return       "
              f"{(every - aaa) * 100:>7.2f} points")
    else:
        print("  the all-government 30-year curve: unavailable")
    print()
    us_rate = re.search(r"^real_risk_free = (-?[0-9.]+)$",
                        (ROOT / "variants" / "us" / "market_data.toml")
                        .read_text(encoding="utf-8"), re.M)
    print("  For comparison, the American variant's safe asset is the 30-year")
    print("  TIPS at %s real. A euro household is offered a materially"
          % ("%.2f%%" % (float(us_rate.group(1)) * 100) if us_rate
             else "its own rate"))
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
            # Non-zero, because a scheduled run that was asked to refresh and
            # did not has failed, and exiting 0 here made that look fine.
            return 1
        return 0

    # Net of the withholding the fund suffers at source, which no holder
    # receives: see the module docstring.
    compound = net + growth
    volatility = ITALY_VOLATILITY
    arithmetic = arithmetic_from_compound(compound, volatility)

    print("  Built here, by the American variant's own construction, because")
    print("  that construction carries no horizon and this model prices a")
    print("  lifetime. See the module docstring.")
    print(f"    dividend yield, MSCI ACWI EUR, net     {net:>8.4%}   "
          f"{first} to {last}")
    print(f"      the same gross, as AQR quote it      {gross:>8.4%}")
    print(f"    real EPS growth, {GROWTH_WINDOW_YEARS}y Shiller trend  "
          f"{growth:>8.4%}   to {growth_as_of}")
    print(f"    repricing                              {0.0:>8.4%}   stated")
    print(f"    compound                               {compound:>8.4%}")
    print(f"    arithmetic, at the fixed {volatility:.2%} volatility "
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
    print(f"    their compound, gross                  "
          f"{AQR_COMPOUND:>8.4%}   {(AQR_COMPOUND - gross - growth) * 100:>+6.2f} "
          f"against ours gross")
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

    if not args.write:
        print("\n  Report only. Pass --write to update the configuration.")
        return 0

    text = CONFIG.read_text(encoding="utf-8")
    # Stamp the file, or the page reports the date of the last HAND edit
    # forever. The as-of date is the ECB curve's own observation date, which
    # is the newest input and the one the safe rate is read off.
    text = re.sub(r"^as_of = .*$", "as_of = %s" % aaa_date, text,
                  count=1, flags=re.M)
    text = re.sub(r'^generated_at = ".*"$', 'generated_at = "%s"'
                  % datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  text, count=1, flags=re.M)
    text = re.sub(r'^generated_by = ".*"$',
                  'generated_by = "tools/refresh_italy.py"', text,
                  count=1, flags=re.M)
    numbers = (
        ("expected_stock_real_return", arithmetic),
        ("real_risk_free", real),
        ("expected_return_compound", compound),
        ("dividend_yield", net),
        ("real_growth", growth),
        ("dividend_yield_measured", gross),
        ("dividend_yield_withheld", gross - net),
        ("expected_inflation", breakeven),
        # A quarterly survey: when it does not answer, last quarter's stays.
        ("expected_inflation_survey", survey_inflation),
        ("nominal_safe_yield", aaa),
    )
    for field, value in numbers:
        if value is None:
            continue
        # Signed, and exactly once: a pattern without the minus wrote the
        # first negative rate and then never matched again.
        text, hits = re.subn(r"^%s = -?[0-9.]+$" % field,
                             "%s = %.6f" % (field, value), text, count=1,
                             flags=re.M)
        if hits != 1:
            raise SystemExit(f"{CONFIG.name} has no line for {field}")
    text = text.replace('provisional_fields = "real_risk_free"',
                        'provisional_fields = ""')
    text = re.sub(r'^real_risk_free_source = ".*"$',
                  lambda _: 'real_risk_free_source = "%s"' % safe_rate_note(
                      aaa_continuous, aaa_date, breakeven, isin, breakeven_years,
                      traded, survey_inflation, spf_date),
                  text, count=1, flags=re.M)
    text = re.sub(r'^expected_return_source = ".*"$',
                  lambda _: 'expected_return_source = "%s"' % expected_return_note(
                      gross, net, first, last, growth, growth_as_of),
                  text, count=1, flags=re.M)
    CONFIG.write_text(text, encoding="utf-8")
    print(f"\n  Written to {CONFIG.relative_to(ROOT)}: the safe rate and the "
          f"expected return.")
    return 0


def safe_rate_note(aaa_continuous: float, aaa_date, breakeven: float, isin: str,
                   breakeven_years: float, traded: float, survey: float,
                   spf_date) -> str:
    """The provenance sentence for the safe rate, with its own arithmetic."""
    aaa = math.expm1(aaa_continuous)
    real = aaa - breakeven
    checks = ""
    if traded is not None:
        checks += (
            " Checked against itself: the break-even comes from that bond, so "
            "this should come close to its traded real yield of %.4f%%, and it "
            "lands %.3f points away, the rest being a thirty-year nominal leg "
            "against a shorter inflation leg."
            % (traded * 100, abs(real - traded) * 100))
    if survey is not None:
        surveyed = (1.0 + aaa) / (1.0 + survey) - 1.0
        checks += (
            " The ECB Survey of Professional Forecasters expects %.4f%% for %s; "
            "deflated by that instead the rate would be %.4f%%, %+.2f points away."
            % (survey * 100, spf_date, surveyed * 100, (surveyed - real) * 100))
    return (
        "ECB AAA euro area central government bond curve, 30-year spot rate, "
        "%.4f%% continuously compounded on %s, which is %.4f%% a year, less the "
        "MARKET break-even inflation rate of %.4f%% on %s, the longest euro "
        "inflation-linked government bond at %.1f years, which gives %.4f%%. "
        "Subtracted because the Finanzagentur defines the break-even as a "
        "simple yield difference; annualised first because the ECB compounds "
        "continuously and the model reads annual rates. It clears three bars "
        "at once: constant maturity, which is what FRED's DFII30 is and a "
        "single bond cannot be; no survey, because a break-even is the rate at "
        "which the linker and a nominal bond pay the same and is therefore a "
        "price; and the same kind of object as DFII30, a traded real yield "
        "rather than a nominal yield with an opinion subtracted.%s"
        % (aaa_continuous * 100, aaa_date, aaa * 100, breakeven * 100, isin,
           breakeven_years, real * 100, checks))


def expected_return_note(gross: float, net: float, first, last, growth: float,
                         growth_as_of) -> str:
    """The provenance sentence for the expected return."""
    return (
        "Built here, by the construction the American variant uses, because "
        "that construction carries no horizon and this model prices a "
        "lifetime: a %.4f%% trailing dividend yield of MSCI All Country World "
        "in euro over %s to %s, NET of the withholding tax the fund suffers at "
        "source (%.4f%% gross), measured from the gap between MSCI net and "
        "price index levels and divided by the price at the end, plus %.4f%% "
        "real growth in earnings per share, the %d-year OLS trend through "
        "Shiller to %s, plus zero repricing. Cross-checked against AQR, %s, as "
        "of %s, who quote gross: their dividend yield of %.1f%% is %+.2f "
        "points from our gross figure and their real EPS growth of %.1f%% is "
        "%+.2f points from ours. Theirs is the check and not the estimate "
        "because they state it is for a horizon of 5 to 10 years, while Table "
        "7 of the American methodology shows this construction is the one that "
        "wins at 30."
        % (net * 100, first, last, gross * 100, growth * 100,
           GROWTH_WINDOW_YEARS, growth_as_of, AQR_REPORT, AQR_AS_OF,
           AQR_YIELD * 100, (AQR_YIELD - gross) * 100,
           AQR_GROWTH * 100, (AQR_GROWTH - growth) * 100))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
