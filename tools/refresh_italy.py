"""Measure the euro real safe rate and the global expected return.

    python tools/refresh_italy.py            report only
    python tools/refresh_italy.py --write    update config/market_data_it.toml

The Italian variant shipped with a safe rate somebody had reasoned about
rather than measured, and an expected return borrowed whole from AQR. Both are
now measured here, and this writes them into the configuration with their
provenance.

THE EXPECTED RETURN is built from equation (5), the same three terms the
American variant uses, so that the difference between a 38% American answer
and an Italian one is the country rather than the method.

  The DIVIDEND YIELD is measured, from MSCI's own index levels. The gross
  index reinvests dividends and the price index does not, so the gap between
  their returns over a month is that month's dividend as a fraction of the
  starting price, and twelve of them are a trailing yield. That is the same
  object as Shiller's dividend column over his price, which is what the
  American variant divides.

  The GROSS variant is used, not the net one, for that same reason: Shiller's
  dividend column is before withholding tax. The report prints the net yield
  beside it, because the gap is a real cost a euro investor pays on a global
  fund and an American holding domestic stock does not.

  The REAL EPS GROWTH is the American variant's own hundred-year trend
  through Shiller, used unchanged as the global rate. That needs an argument
  and AQR supply it: they publish both halves, 2.7% real EPS growth for United
  States large cap and 2.6% for Global All Country. A tenth of a point apart.
  Long-run real growth in earnings per share is a return on capital net of
  share issuance, not a national characteristic, and the one firm publishing
  both numbers measures it as very nearly the same in both places.

  So the growth term comes from the market where it can be measured over 155
  years to a quarter of a point, rather than from global data where every
  attempt moved several points. tools/global_growth.py is that attempt, and
  it reports what it found.

  The REPRICING is zero, stated, as in the American variant.

WHY NOT update.py. That script rebuilds a whole configuration from one
American template and refuses to touch this file, for a reason it learned the
hard way: run on the Italian file once, it wrote the 30-year United States
TIPS in as the safe rate and deleted the note saying the rate was a guess.
This tool changes two lines and nothing else.

THE SAFE RATE is the traded real yield of the longest euro inflation-linked
government bond, which is Bund/euro-i 2046. That is the same kind of object
the American variant reads from FRED, a government real yield set by a market
rather than built out of two other numbers, and using the same kind of object
is what makes the two answers comparable at all. Constructing it differently
would have put part of the gap between a 38% American answer and a 70%
Italian one into the method rather than into the countries.

Three compromises come with it, and the report prints all three.

  It runs about twenty years, not thirty, and shortens every year. Germany
  stopped issuing in 2023 and three bonds remain, so it is the longest euro
  linker in existence and there is nothing to roll into.

  Scarcity biases the yield DOWN: 47 billion outstanding, no new supply,
  against steady demand for euro safe assets.

  It tracks euro area HICP, not Italian. Only BTP Italia follows Italian
  inflation, at five years and retail, so the hedge is approximate in a way
  an American's TIPS is not.

THE CROSS-CHECK builds the same rate the other way, from the ECB: the AAA
euro area government curve at thirty years, deflated by the longer-term HICP
expectation in the Survey of Professional Forecasters. It is reported rather
than used, because the two bracket the answer. The traded yield is biased low
by scarcity; the deflated one is biased high, because the gap between the
market break-even and the survey expectation is an inflation risk premium and
deflating books it as return.

AAA rather than every euro area government bond, in that cross-check and in
the choice of issuer. The all-government curve yields about sixty basis points
more at the same maturity, and that spread is compensation for a government
not paying. Equation (4) cannot represent default risk, so taking it would
book a credit premium as a risk-free return, lowering the recommendation while
looking prudent. An Italian household buying BTP is not holding this asset.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "market_data_it.toml"

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


def longest_german_linker() -> tuple[str, float, float]:
    """The longest outstanding Bund/€i: its ISIN, years left and real yield.

    The page carries two charts, real yields and break-even inflation, in the
    same shape. Taking the first set of series that appears would work today
    and silently return break-evens the day the order changes, so the chart is
    selected by its axis label instead.
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
    real = [c for c in charts if c.startswith("Real yield")]
    if not real:
        raise SystemExit("no chart on the page is labelled as real yields")
    block = real[0]
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
        raise SystemExit("no real yield series found on the page")
    return max(found, key=lambda row: row[1])


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
    """Dividends paid over the last twelve months, against the price then.

    The gross index reinvests each dividend and the price index does not, so
    the difference between their monthly returns is that month's dividend
    divided by the price at the start of the month. Summing twelve of those is
    a trailing twelve-month yield built from nothing but two index levels.
    """
    price = msci_levels(ACWI, "EUR", "STRD")
    total = msci_levels(ACWI, "EUR", variant)
    dates = sorted(set(price) & set(total))
    if len(dates) < YIELD_MONTHS + 1:
        raise SystemExit("MSCI returned too few months to measure a yield")
    window = dates[-(YIELD_MONTHS + 1):]
    paid = sum(total[b] / total[a] - price[b] / price[a]
               for a, b in zip(window, window[1:]))
    return paid, window[0], window[-1]


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

    deflated = (1.0 + aaa) / (1.0 + expected_inflation) - 1.0
    real_all = (1.0 + every) / (1.0 + expected_inflation) - 1.0
    real = traded

    print(f"  {isin}, the longest euro linker      {traded:>8.4%}   "
          f"{years_left:.1f} years left")
    print(f"  USED AS THE SAFE RATE. A traded real yield, which is what the")
    print(f"  American variant reads from FRED, so the two are comparable.")
    print()
    print("  As a cross-check, the same rate built the other way:")
    print(f"  AAA euro area government, 30y, nominal   {aaa:>8.4%}   "
          f"{aaa_date}")
    print(f"  longer-term HICP expectation, ECB SPF    "
          f"{expected_inflation:>8.4%}   {spf_date}")
    print(f"  deflated                                 {deflated:>8.4%}")
    print()
    print(f"  The two bracket it, {abs(deflated - traded) * 100:.2f} points "
          f"apart. The traded yield is biased low")
    print("  by scarcity: three bonds left, no issuance since 2023. The")
    print("  deflated one is biased high, because the gap between the market")
    print("  breakeven and the survey expectation is an inflation risk")
    print("  premium being booked as return.")
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
    print("Building the expected return")
    print("=" * 68)

    gross, first, last = trailing_dividend_yield("GRTR")
    net, _, _ = trailing_dividend_yield("NETR")
    growth, growth_as_of = american_growth_trend()

    print(f"  MSCI ACWI dividend yield, EUR, 12m       {gross:>8.4%}   "
          f"{first} to {last}")
    print(f"  the same net of withholding tax          {net:>8.4%}")
    print(f"  withheld                                 "
          f"{(gross - net) * 100:>7.2f} points")
    print("  The GROSS figure is used, because Shiller's dividend column is")
    print("  gross too and the two variants have to measure the same object.")
    print("  The withholding is real and unmodelled: it is a cost a euro")
    print("  investor pays on a global fund and an American holding domestic")
    print("  stock does not.")
    print()

    if growth is None:
        print("  Shiller's workbook was not found, so the growth term and the")
        print("  expected return were not rebuilt. Run update.py first, or put")
        print("  ie_data.xls at data/shiller.xls.")
        if args.write:
            print("\n  Nothing written: refusing to write half an estimate.")
        return 0

    compound = gross + growth
    volatility = float(re.search(r"^stock_volatility = ([0-9.]+)$",
                                 CONFIG.read_text(encoding="utf-8"),
                                 re.M).group(1))
    arithmetic = arithmetic_from_compound(compound, volatility)

    print(f"  real EPS growth, {GROWTH_WINDOW_YEARS}y trend on Shiller     "
          f"{growth:>8.4%}   to {growth_as_of}")
    print("  Used as the GLOBAL rate. AQR publish 2.7% for United States")
    print("  large cap and 2.6% for Global All Country, a tenth of a point")
    print("  apart, so the growth term is taken where it can be measured.")
    print(f"  repricing                                {0.0:>8.4%}   stated")
    print(f"  compound                                 {compound:>8.4%}")
    print(f"  arithmetic, at {volatility:.2%} volatility      "
          f"{arithmetic:>8.4%}")
    print()
    print("  AQR's own Global All Country figure is 4.20% compound, so this")
    print(f"  independent build is {(compound - 0.042) * 100:+.2f} points from "
          f"theirs. Their")
    print(f"  quoted 1.6% dividend yield is {(gross - 0.016) * 100:+.2f} points "
          f"from the measured one.")

    if not args.write:
        print("\n  Report only. Pass --write to update the configuration.")
        return 0

    text = CONFIG.read_text(encoding="utf-8")
    text = re.sub(r"^expected_stock_real_return = [0-9.]+$",
                  "expected_stock_real_return = %.6f" % arithmetic,
                  text, count=1, flags=re.M)
    for field, value in (("expected_return_compound", compound),
                         ("dividend_yield", gross),
                         ("real_growth", growth),
                         ("dividend_yield_withheld", gross - net)):
        text = re.sub(r"^%s = [0-9.]+$" % field,
                      "%s = %.6f" % (field, value), text, count=1, flags=re.M)
    text = re.sub(r"^real_risk_free = [0-9.]+$",
                  "real_risk_free = %.6f" % real, text, count=1, flags=re.M)
    text = text.replace('provisional_fields = "real_risk_free"',
                        'provisional_fields = ""')
    text = re.sub(r'^real_risk_free_source = ".*"$',
                  'real_risk_free_source = "%s, Bund/euro-i, the longest '
                  'outstanding euro inflation-linked government bond, %.1f '
                  'years remaining, traded real yield %.4f%% from the German '
                  'finance agency. Cross-checked against the ECB AAA 30-year '
                  'nominal of %.4f%% on %s deflated by the ECB Survey of '
                  'Professional Forecasters longer-term HICP expectation of '
                  '%.4f%% for %s, which gives %.4f%%. The two bracket the '
                  'rate: the traded yield is biased low by scarcity, the '
                  'deflated one high by an inflation risk premium booked as '
                  'return."'
                  % (isin, years_left, traded * 100, aaa * 100, aaa_date,
                     expected_inflation * 100, spf_date, deflated * 100),
                  text, count=1, flags=re.M)
    text = re.sub(r'^expected_return_source = ".*"$',
                  'expected_return_source = "Computed here, not borrowed. A '
                  '%.4f%% trailing dividend yield of MSCI All Country World in '
                  'euro, measured over %d to %d from the gap between MSCI\'s '
                  'gross and price index levels, plus %.4f%% real growth in '
                  'earnings per share, the %d-year trend through Shiller to '
                  '%s that the American variant uses, plus zero repricing. '
                  'AQR publish 4.20%% for the same index built the same way, '
                  'so this is %+.2f points from theirs."'
                  % (gross * 100, first, last, growth * 100,
                     GROWTH_WINDOW_YEARS, growth_as_of,
                     (compound - 0.042) * 100),
                  text, count=1, flags=re.M)
    CONFIG.write_text(text, encoding="utf-8")
    print(f"\n  Written to {CONFIG.relative_to(ROOT)}: the safe rate and the "
          f"expected return.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
