"""Measure the euro real safe rate, and check it against the firms.

    python tools/refresh_italy.py            report only
    python tools/refresh_italy.py --write    update config/market_data_it.toml

The Italian variant shipped with a safe rate somebody had reasoned about
rather than measured, which is the input its answer is most sensitive to.
This measures it, from two series the ECB publishes daily and quarterly, and
writes it into the configuration with its provenance.

WHY NOT update.py. That script rebuilds a whole configuration from one
American template and refuses to touch this file, for a reason it learned the
hard way: run on the Italian file once, it wrote the 30-year United States
TIPS in as the safe rate and deleted the note saying the rate was a guess.
This tool changes two lines and nothing else.

THE CONSTRUCTION, and the two judgements in it.

    real = (1 + nominal 30-year AAA) / (1 + long-run HICP expectation) - 1

The first judgement is AAA rather than all euro area government bonds. The
model's equation (4) compares equities against an asset it assumes is
riskless. The all-government curve is currently about sixty basis points
higher at thirty years, and that sixty points is compensation for the chance
that a government does not pay, which is not something the model can
represent. Taking it would be booking a credit premium as a risk-free return
and would lower the recommended equity share while pretending to be prudent.
So the safe rate here is the AAA curve, which is essentially German and Dutch
paper, and the Italian methodology says plainly that an Italian household
buying BTP is not holding this asset.

The second is the deflator. The American variant reads a real yield directly
from FRED, because TIPS trade in size at thirty years. The euro area has no
equivalent: German linkers stopped being issued in 2023 with four bonds left
outstanding, and the HICP-linked bonds that remain are Italian and French, so
their real yields carry the same credit spread the AAA choice just excluded.
Deflating a nominal AAA yield by a survey expectation avoids that, at the
cost of using a forecast rather than a traded price. The ECB's Survey of
Professional Forecasters publishes a longer-term HICP expectation quarterly,
which is the right horizon for a lifetime allocation.
"""

from __future__ import annotations

import argparse
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "market_data_it.toml"

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

    if not args.write:
        print("\n  Report only. Pass --write to update the configuration.")
        return 0

    text = CONFIG.read_text(encoding="utf-8")
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
    CONFIG.write_text(text, encoding="utf-8")
    print(f"\n  Written to {CONFIG.relative_to(ROOT)}. The safe rate is no "
          f"longer provisional.")
    print("  Re-run the expected return conversion if the volatility moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
