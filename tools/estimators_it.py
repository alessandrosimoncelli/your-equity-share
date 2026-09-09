"""What the choice of estimator is worth, for a euro investor, at 30 years.

    python tools/estimators_it.py

Table 5 of the American methodology sets every candidate estimate of the
expected return side by side and shows what each one does to the same
household on the same day. The range is larger than anything else in the model,
which is the single most important thing a reader can know about it. This is
that table for the global sleeve a euro investor holds.

IT ALSO ANSWERS A HORIZON QUESTION, and that is why it exists rather than being
a translation. This tool prices a lifetime. Nearly every published forecast
prices five to ten years. Those are not the same number and the difference has
a known sign.

AQR SAY SO THEMSELVES, in the 2026 report this variant's figure comes from:

    "We present local real (inflation-adjusted) and nominal annual compound
    rates of return for a horizon of 5 to 10 years. Over such intermediate
    horizons, starting valuations tend to be useful inputs. For multi-decade
    forecast horizons their impact is diluted, so theory and long-term
    historical averages may matter more in judging expected returns."

Both halves of their estimate are built to ten years and not to thirty. The
payout half uses "a country-specific estimate of next-10-year real EPS growth".
The earnings half multiplies the cyclically adjusted earnings yield by
1 + (g x 5) explicitly "to account for earnings growth during the 10-year
window". Their number is a good ten-year number and it is being used here at
thirty.

WHICH WAY DOES THAT BIAS IT. Down, on two independent measurements, so the
error is conservative rather than flattering.

Horizon Actuarial survey ~40 professional advisors every year and group the
answers into ten-year and twenty-year horizons. Their finding, repeated across
editions: "The consensus among these 24 advisors was that returns are expected
to be lower in the short term compared to the long term", and the differences
"are also relatively large for equities". They also note, usefully for reading
any of this, that "many investment firms consider 10-year expectations to be
long-term".

Vanguard is the one firm publishing both horizons off a single model run, and
section 8.3 of the American methodology records the gap: their thirty-year
United States equity forecast sits 0.9 points above their ten-year.

So a ten-year forecast used at thirty understates the expected return, which
understates the equity share. This tool reports the estimators that carry no
horizon at all beside the ones that do, and says which is which.

WHAT IS AND IS NOT COMPUTED HERE. The American table has a row regressing
realised thirty-year returns on starting valuation. That row cannot be built
for a global index, because it needs a century of global valuations and no free
series carries them; tools/global_growth.py is the record of how badly that
goes. The rows below are the ones that can be built honestly from MSCI's own
index levels, Shiller, and the Jorda-Schularick-Taylor database, plus published
figures quoted as published.
"""

from __future__ import annotations

import json
import math
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share import Household, Person, recommend  # noqa: E402
from your_equity_share.expected_return import (  # noqa: E402
    arithmetic_from_compound,
)
from your_equity_share.human_capital import ITALY_CALIBRATION  # noqa: E402
from your_equity_share.market_data import load_market_data  # noqa: E402
from your_equity_share.providers import (  # noqa: E402
    parse_shiller_csv,
    parse_shiller_xls,
)

CONFIG = ROOT / "config" / "market_data_it.toml"
CACHE = ROOT / "data" / "msci_acwi_eur.json"

MSCI = ("https://app2.msci.com/products/service/index/indexmaster/"
        "getLevelDataForGraph?currency_symbol=EUR&index_variant={var}"
        "&start_date=19970101&end_date={end}&data_frequency=END_OF_MONTH"
        "&index_codes=892400")
HICP = ("https://data-api.ecb.europa.eu/service/data/ICP/M.U2.N.000000.4.INX"
        "?format=csvdata")
AGENT = "your-equity-share (methodology check)"

# The household Table 5 uses, so the two tables can be read against each other.
HOUSEHOLD = Household(1_500_000.0, [Person(45, 100_000.0)], 5.0)

# AQR, Alternative Thinking 2026 Issue 1, Global All Country, 31 December 2025.
AQR_COMPOUND, AQR_YIELD, AQR_GROWTH = 0.042, 0.016, 0.026

# AQR's own equilibrium real EPS growth for developed large cap, which their
# earnings-based anchor adds back. Their words, their number.
AQR_EQUILIBRIUM_GROWTH = 0.018


def _context():
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def _get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {"User-Agent": AGENT})
    for context in (None, _context()):
        try:
            with urllib.request.urlopen(request, timeout=60,
                                        context=context) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.URLError:
            if context is not None:
                raise
    raise SystemExit("could not reach %s" % url)


def msci_levels():
    """ACWI price and gross levels in euro, cached so this is cheap to rerun."""
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    from datetime import date
    out = {}
    for variant in ("STRD", "GRTR"):
        payload = json.loads(_get(
            MSCI.format(var=variant, end=date.today().strftime("%Y%m%d")),
            headers={"User-Agent": AGENT,
                     "Accept": "application/json, text/plain, */*",
                     "Referer": "https://www.msci.com/end-of-day-data-search"}))
        if "indexes" not in payload:
            raise SystemExit("MSCI refused: %s" % payload.get("error_message"))
        out[variant] = {str(r["calc_date"]): float(r["level_eod"])
                        for r in payload["indexes"]["INDEX_LEVELS"]}
    CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def euro_hicp():
    rows = [line.split(",") for line in _get(HICP).splitlines() if line.strip()]
    header = rows[0]
    out = {}
    for row in rows[1:]:
        record = dict(zip(header, row))
        try:
            out[record["TIME_PERIOD"]] = float(record["OBS_VALUE"])
        except (KeyError, ValueError):
            pass
    return out


def dividend_series(levels, hicp):
    """Monthly dividend cash in index points, and the real version of it.

    The gross index reinvests each dividend and the price index does not, so
    the difference between their monthly returns is that month's dividend as a
    fraction of the price at the start of the month.
    """
    price, gross = levels["STRD"], levels["GRTR"]
    dates = sorted(set(price) & set(gross))
    nominal, real = {}, {}
    for before, after in zip(dates, dates[1:]):
        paid = (gross[after] / gross[before]
                - price[after] / price[before]) * price[before]
        nominal[after] = paid
        # The deflator runs to the end of the previous year while the index
        # runs to last month, so the real series is shorter than the nominal
        # one. Keeping the two domains separate is the point: a trailing yield
        # needs no deflator and a cyclical average cannot do without one.
        key = "%s-%s" % (after[:4], after[4:6])
        if key in hicp:
            real[after] = paid / hicp[key] * 100.0
    return sorted(nominal), nominal, real


def american_growth_trend():
    for candidate in (ROOT / "data" / "shiller.xls",
                      ROOT / "data" / "shiller.csv"):
        if not candidate.exists():
            continue
        raw = candidate.read_bytes()
        history = (parse_shiller_csv(raw.decode("utf-8", "replace"))
                   if candidate.suffix.lower() == ".csv"
                   else parse_shiller_xls(raw))
        return history.real_earnings_trend_growth(100), history.dates[-1]
    return None, None


def share(compound, market):
    """The equity share this compound real return implies, all else equal."""
    mean = arithmetic_from_compound(compound, market.stock_volatility)
    return recommend(HOUSEHOLD, mean, market.real_risk_free_rate,
                     market.stock_volatility, ITALY_CALIBRATION).equity_share


def main() -> int:
    market = load_market_data(CONFIG)
    levels = msci_levels()
    hicp = euro_hicp()
    dates, nominal, real = dividend_series(levels, hicp)
    price = levels["STRD"]

    growth, growth_as_of = american_growth_trend()
    if growth is None:
        print("Shiller's workbook was not found; run update.py first.")
        return 0

    last = dates[-1]
    # Over TODAY's price, which is Shiller's convention and therefore
    # the American variant's. See refresh_italy.trailing_dividend_yield:
    # the denominator is worth a third of a point on this data.
    trailing = sum(nominal[d] for d in dates[-12:]) / price[dates[-1]]

    # Cyclically adjusted: ten years of real dividends averaged, restated at
    # the prices of the anchor month, over the price in that month. The
    # dividend analogue of 1/CAPE, and the only cyclical measure available,
    # since no free source carries a global earnings history.
    #
    # Anchored at the last month carrying BOTH a price and a deflator, which
    # is not the last month of the index. Restating a ten-year average in
    # today's money needs today's CPI, and the euro HICP release lags.
    anchor = max(real)
    anchor_cpi = hicp["%s-%s" % (anchor[:4], anchor[4:6])]
    window = [d for d in sorted(real)
              if d >= "%d%s" % (int(anchor[:4]) - 10, anchor[4:])]
    average_real = sum(real[d] for d in window) / (len(window) / 12.0)
    cyclical = average_real * anchor_cpi / 100.0 / price[anchor]

    print("What the choice of estimator is worth, for a euro investor")
    print("=" * 78)
    print("  MSCI All Country World, euro, %s to %s" % (dates[0], last))
    print("  trailing 12-month dividend yield     %7.4f%%" % (trailing * 100))
    print("  cyclically adjusted, %d years        %7.4f%%   to %s"
          % (len(window) // 12, cyclical * 100, anchor))
    print("  real EPS growth, 100y Shiller trend  %7.4f%%   to %s"
          % (growth * 100, growth_as_of))
    print("  safe rate, ECB 30y AAA deflated      %7.4f%%"
          % (market.real_risk_free_rate * 100))
    print("  volatility, VWCE five years          %7.4f%%"
          % (market.stock_volatility * 100))
    print()

    anchor = cyclical * (1 + AQR_EQUILIBRIUM_GROWTH * 5) + AQR_EQUILIBRIUM_GROWTH
    rows = [
        ("Cyclically adjusted yield plus growth", cyclical + growth, "none"),
        ("AQR's earnings anchor, dividend form", anchor, "10y"),
        ("Dividend yield plus long-run growth", trailing + growth, "none"),
        ("AQR published, Global All Country", AQR_COMPOUND, "5 to 10y"),
        ("Dividend yield alone, no growth", trailing, "none"),
    ]
    rows.sort(key=lambda r: -r[1])

    print("  %-40s %9s %8s %8s" % ("estimate of the expected real return",
                                   "compound", "horizon", "equity"))
    for label, value, horizon in rows:
        mark = "  <- used" if abs(value - AQR_COMPOUND) < 1e-9 else ""
        print("  %-40s %8.2f%% %8s %7.1f%%%s"
              % (label, value * 100, horizon, share(value, market) * 100, mark))

    spread = max(r[1] for r in rows) - min(r[1] for r in rows)
    shares = [share(r[1], market) for r in rows]
    print()
    print("  The estimates span %.2f points and the answers span %.0f points."
          % (spread * 100, (max(shares) - min(shares)) * 100))
    print("  Nothing else in the model moves the recommendation that far.")

    print()
    print("  ON THE HORIZON. AQR state their figure is for five to ten years,")
    print("  and that \"for multi-decade forecast horizons\" the impact of")
    print("  starting valuations \"is diluted, so theory and long-term")
    print("  historical averages may matter more\". Both halves of their")
    print("  estimate are built to ten years. The rows marked \"none\" carry no")
    print("  horizon at all: a yield plus a long-run growth rate with no")
    print("  repricing is the same number whatever the holding period, which")
    print("  is why this variant can use one at thirty years and cannot")
    print("  strictly use a ten-year forecast there.")
    print()
    print("  The mismatch is CONSERVATIVE. Horizon Actuarial find across ~40")
    print("  advisors that returns are expected to be lower over ten years")
    print("  than over twenty, and Vanguard's own thirty-year forecast sits")
    print("  0.9 points above their ten-year. A ten-year number used at thirty")
    print("  therefore understates the expected return and the equity share.")
    print("  Adding Vanguard's 0.9 points to AQR's %.2f%% would give %.2f%%"
          % (AQR_COMPOUND * 100, AQR_COMPOUND * 100 + 0.9))
    print("  and %.1f%% equities, against %.1f%% as it stands."
          % (share(AQR_COMPOUND + 0.009, market) * 100,
             share(AQR_COMPOUND, market) * 100))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
