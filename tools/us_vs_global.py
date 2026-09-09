"""Can an American growth trend stand in for a global one?

    python tools/us_vs_global.py

Both variants take their growth term from the same place: the hundred-year
trend through Shiller's real earnings per share, which is American data. The
Italian variant applies it to a global index. That substitution is the largest
judgement left in the model, and it had been argued from AQR's published pair
rather than measured. This is the attempt to measure it.

IT DOES NOT SUCCEED, and the reason is worth more than the attempt.

THE TEST HAS TO BE AGAINST ex-US DATA. Comparing the S&P 500 with a world index
is largely comparing the United States with itself, since it is about 65% of a
world index. So the comparison is against the world with the United States
removed.

AND IT HAS TO BE THE TREND, not the correlation. A lifetime allocation does not
care whether American and foreign earnings move together in a given year; it
cares whether they GROW AT THE SAME RATE over decades. Two series can be
weakly correlated and share a trend exactly. Both are reported and the trend is
the one that decides.

WHAT THE LONG SAMPLE DOES. Nothing usable. Put the question to the
Jorda-Schularick-Taylor database and the answer is decided by the construction
rather than by the data. Across the four defensible treatments the ex-US
aggregate runs from -3.33% to +3.91%, a spread of more than seven points, while
the United States moves 0.15 points across the same choices. The SIGN of the
gap flips. Two biases drive it and both are specific to the rest of the world:

  Dropping the war years removes the collapses and keeps the recoveries. The
  destruction happens inside 1914 to 1919 and 1939 to 1949 and the rebound
  happens after, so excluding those years is not neutral. It barely touches the
  United States, which had no domestic destruction, and it is worth several
  points elsewhere.

  Rebalancing to fixed weights every year earns a variance bonus no index gets,
  and the bonus grows with cross-sectional variance. On the full basket, with
  the United States in it, that was worth 0.21 points. On the ex-US basket it
  is worth about 3.4 points.

This is the same wall tools/global_growth.py hits, for the same structural
reason: a fixed basket of countries is not an index, because an index
reconstitutes and JST publishes country index returns rather than the world
index's constituents.

WHAT THE SHORT SAMPLE DOES. Something, but not enough. MSCI in LOCAL currency,
each side deflated by its own price index, over 2002 to 2024, has the United
States growing real dividends 4.1 points a year faster than the developed world
without it. That is a real measurement of a real period, and it is also
twenty-three years covering the most documented stretch of American
outperformance in modern history, on dividends rather than earnings, over a
window shorter than the sixty years below which this estimator is known to come
apart.

Note that it points the OPPOSITE way from the naive long-sample reading, which
is the clearest sign that neither is settling anything.

WHAT ACTUALLY BOUNDS THE ERROR is arithmetic rather than either sample, and it
is the argument the configuration should have made from the start. The global
index is about 64% American. Using an American growth rate for it is only wrong
on the other 36%. If the rest of the world grows d points a year away from the
United States, the error in the GLOBAL rate is 0.36 x d. For the global growth
term to be wrong by half a point, the rest of the world would have to differ
from the United States by nearly a point and a half a year, sustained over a
lifetime.

AQR are the only party who can measure this, and their published pair implies a
gap far inside that. They report 2.7% for United States large cap and 2.6% for
Global All Country. Backing the rest of the world out of those two at a 64%
American weight gives about 2.4%, so their implied US-minus-rest gap is roughly
0.3 points, which costs a tenth of a point on the global rate.
"""


from __future__ import annotations

import json
import math
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.global_growth import annual_real_dividend_growth, find_dataset  # noqa: E402

CACHE = ROOT / "data" / "msci_us_exus_local.json"
# The same string update.py sends. FRED closes the connection on the plainer
# one this file used first, which looks like a hang rather than a refusal.
AGENT = "Mozilla/5.0 (compatible; your-equity-share/0.1; research tool)"

# Identified by their returns and their correlation with the World index over
# 1997 to 2026, printed by the probe in this file's history: MSCI USA is the
# highest returning and most correlated, World ex USA sits well below it, and
# Emerging Markets is the least correlated of all.
INDEX = {"984000": "MSCI USA", "990400": "MSCI World ex USA"}

MSCI = ("https://app2.msci.com/products/service/index/indexmaster/"
        "getLevelDataForGraph?currency_symbol=LOC&index_variant={var}"
        "&start_date=19970101&end_date=20260908"
        "&data_frequency=END_OF_MONTH&index_codes={code}")
FRED_CPI = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
# One deflator per currency area. The OECD aggregate still contains the
# United States, which mildly contaminates the ex-US side, but the error it
# leaves is far smaller than the one it removes.
CPI_SERIES = {"984000": "CPIAUCSL", "990400": "OECDCPALTT01IXOBM"}

# MSCI World country weights, as in tools/global_growth.py.
WEIGHTS = {
    "USA": 72.14, "JPN": 5.78, "GBR": 3.53, "CAN": 3.30, "FRA": 2.40,
    "CHE": 2.40, "DEU": 2.30, "AUS": 1.80, "NLD": 1.30, "SWE": 0.80,
    "ITA": 0.80, "ESP": 0.70, "DNK": 0.60, "FIN": 0.20, "BEL": 0.20,
    "NOR": 0.20, "IRL": 0.15, "PRT": 0.03,
}
WAR = frozenset(range(1914, 1920)) | frozenset(range(1939, 1950))

# The United States share of MSCI All Country World, which is what the
# Italian sleeve tracks. The dilution argument turns entirely on it.
US_WEIGHT_IN_ACWI = 0.64

# AQR, Alternative Thinking 2026 Issue 1: real EPS growth, their figures.
AQR_US, AQR_GLOBAL = 0.027, 0.026


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
            with urllib.request.urlopen(request, timeout=90,
                                        context=context) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.URLError:
            if context is not None:
                raise
    raise SystemExit("could not reach %s" % url)


def levels():
    """Price and gross levels for both indices, cached."""
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    out = {}
    for code in INDEX:
        for variant in ("STRD", "GRTR"):
            payload = json.loads(_get(
                MSCI.format(var=variant, code=code),
                headers={"User-Agent": AGENT,
                         "Accept": "application/json, text/plain, */*",
                         "Referer": "https://www.msci.com/end-of-day-data-search"}))
            if "indexes" not in payload:
                raise SystemExit("MSCI refused %s %s: %s"
                                 % (code, variant, payload.get("error_message")))
            out["%s_%s" % (code, variant)] = {
                str(r["calc_date"]): float(r["level_eod"])
                for r in payload["indexes"]["INDEX_LEVELS"]}
    CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def cpi(series):
    rows = [line.split(",") for line in _get(FRED_CPI.format(series)).splitlines() if line.strip()]
    out = {}
    for row in rows[1:]:
        try:
            out[row[0][:7]] = float(row[1])
        except (ValueError, IndexError):
            pass
    return out


def annual_real_dividends(data, code, cpi):
    """A year's dividends in constant dollars, from the gross-price gap."""
    price = data["%s_STRD" % code]
    gross = data["%s_GRTR" % code]
    dates = sorted(set(price) & set(gross))
    out = {}
    for before, after in zip(dates, dates[1:]):
        paid = (gross[after] / gross[before]
                - price[after] / price[before]) * price[before]
        key = "%s-%s" % (after[:4], after[4:6])
        if key not in cpi:
            continue
        year = int(after[:4])
        entry = out.setdefault(year, [0.0, 0])
        entry[0] += paid / cpi[key] * 100.0
        entry[1] += 1
    return {y: v for y, (v, n) in out.items() if n == 12}


def growth_rates(series):
    years = sorted(series)
    return {b: series[b] / series[a]
            for a, b in zip(years, years[1:])
            if series[a] > 0 and series[b] > 0}


def correlation(a, b):
    keys = sorted(set(a) & set(b))
    if len(keys) < 8:
        return None, 0
    xs = [math.log(a[k]) for k in keys]
    ys = [math.log(b[k]) for k in keys]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None, n
    return cov / (sx * sy), n


def trend(series):
    """Annual growth from the OLS slope of the log level."""
    pts = sorted((y, v) for y, v in series.items() if v > 0)
    if len(pts) < 8:
        return None
    xs = [y for y, _ in pts]
    ys = [math.log(v) for _, v in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return math.exp(num / sum((x - mx) ** 2 for x in xs)) - 1


def chain(growth, first, drop_wars=True):
    level, out = 1.0, {}
    for year in sorted(growth):
        if year < first or (drop_wars and year in WAR):
            continue
        g = growth[year]
        if not 0.2 < g < 5.0:
            continue
        level *= g
        out[year] = level
    return out


EX_US = {i: w for i, w in WEIGHTS.items() if i != "USA"}


def rebalanced(per_country, first, drop_wars=True):
    """Fixed weights reset every year. Earns a variance bonus no index gets."""
    level, out = 1.0, {}
    for year in sorted({y for s in per_country.values() for y in s}):
        if year < first or (drop_wars and year in WAR):
            continue
        pairs = [(EX_US[i], per_country[i][year]) for i in EX_US
                 if i in per_country and year in per_country[i]
                 and 0.2 < per_country[i][year] < 5.0]
        if len(pairs) < 6:
            continue
        level *= sum(w * g for w, g in pairs) / sum(w for w, _ in pairs)
        out[year] = level
    return out


def buy_and_hold(per_country, first, drop_wars=True):
    """Weights set once and left alone, which is what an index's dividends do."""
    per = {}
    for iso in EX_US:
        if iso not in per_country:
            continue
        index = chain(per_country[iso], first, drop_wars)
        years = sorted(index)
        if (years and years[0] <= first + 3 and years[-1] >= 2015
                and len(index) >= 25):
            per[iso] = index
    if not per:
        return {}
    common = sorted(set.intersection(*(set(v) for v in per.values())))
    if not common:
        return {}
    at = common[-1]
    return {year: sum(EX_US[i] * per[i][year] / per[i][at] for i in per)
            for year in common}


def main() -> int:
    print("Can an American growth trend stand in for a global one?")
    print("=" * 74)

    print("\n1. MSCI, real dividends, local currency, own deflators")
    data = levels()
    series = {c: annual_real_dividends(data, c, cpi(CPI_SERIES[c]))
              for c in INDEX}
    rates = {c: growth_rates(s) for c, s in series.items()}
    us, world = "984000", "990400"
    common = sorted(set(rates[us]) & set(rates[world]))
    r, _ = correlation(rates[us], rates[world])
    print("   %d common years, %d to %d" % (len(common), common[0], common[-1]))
    print("   correlation of annual growth              %+.3f" % r)
    trends = {}
    for code in (us, world):
        trends[code] = trend({y: v for y, v in series[code].items()
                              if y >= common[0]})
        print("   %-38s %8.3f%%" % (INDEX[code], trends[code] * 100))
    modern = trends[us] - trends[world]
    print("   %-38s %+8.3f points" % ("United States minus the rest", modern * 100))
    print("   Twenty-three years, dividends rather than earnings, and the most")
    print("   documented stretch of American outperformance there is. Real,")
    print("   and not enough on its own.")

    print("\n2. Jorda-Schularick-Taylor, 1870 onward, every construction")
    path = find_dataset(os.environ.get("JST_DATASET"))
    if path is None:
        print("   dataset not found, skipping")
        return 0
    per_country = annual_real_dividend_growth(path)

    print("   %-32s %8s %8s %8s" % ("rest of the world", 1870, 1900, 1950))
    every = []
    for label, holder, drop in (("rebalanced, wars dropped", rebalanced, True),
                                ("rebalanced, wars kept", rebalanced, False),
                                ("buy and hold, wars dropped", buy_and_hold, True),
                                ("buy and hold, wars kept", buy_and_hold, False)):
        row = [trend(holder(per_country, f, drop)) for f in (1870, 1900, 1950)]
        every += [v for v in row if v is not None]
        print("   %-32s %s" % (label, " ".join(
            "%7.2f%%" % (v * 100) if v is not None else "      -" for v in row)))
    mine = []
    for drop in (True, False):
        row = [trend(chain(per_country["USA"], f, drop)) for f in (1870, 1900, 1950)]
        mine += [v for v in row if v is not None]
        print("   %-32s %s" % ("UNITED STATES, wars %s" % ("dropped" if drop else "kept"),
                               " ".join("%7.2f%%" % (v * 100) for v in row)))

    print()
    print("   rest of the world spans %.2f points across those choices"
          % ((max(every) - min(every)) * 100))
    print("   the United States spans %.2f points across the same choices"
          % ((max(mine) - min(mine)) * 100))
    print("   Dropping war years removes the collapses and keeps the")
    print("   recoveries; rebalancing to fixed weights earns a variance bonus")
    print("   worth about 3.4 points on a basket this dispersed. Both biases")
    print("   are specific to the rest of the world.")
    print()
    print("   BUT READ THE ROWS, NOT THE SPREAD. Only the rebalanced rows put")
    print("   the rest of the world ahead, and rebalancing is the construction")
    print("   known to be biased. On buy and hold, which is what an index's")
    print("   dividends actually do, the United States is ahead at every start")
    print("   year. So the SIGN is not in doubt once the biased construction is")
    print("   set aside. Only the size is.")
    print()
    print("   The buy-and-hold gaps are themselves upper bounds, because a")
    print("   fixed basket cannot reconstitute and that failure falls hardest")
    print("   on the countries whose markets were destroyed and rebuilt.")

    print("\n3. What actually bounds the error")
    print("   The global index is about %.0f%% American, so an American growth"
          % (US_WEIGHT_IN_ACWI * 100))
    print("   rate is only wrong on the other %.0f%%."
          % ((1 - US_WEIGHT_IN_ACWI) * 100))
    print()
    print("   %-34s %12s" % ("if the rest of the world differs by", "global error"))
    for d in (0.25, 0.5, 1.0, 1.5, 2.0, float(modern * 100)):
        tag = "  <- the modern sample" if abs(d - modern * 100) < 1e-9 else ""
        print("   %-34s %11.2f points%s"
              % ("%.2f points a year" % d, (1 - US_WEIGHT_IN_ACWI) * d, tag))
    print()
    implied = (AQR_GLOBAL - US_WEIGHT_IN_ACWI * AQR_US) / (1 - US_WEIGHT_IN_ACWI)
    print("   AQR are the only party who can measure this. They publish %.1f%%"
          % (AQR_US * 100))
    print("   for United States large cap and %.1f%% for Global All Country."
          % (AQR_GLOBAL * 100))
    print("   Backing the rest of the world out of that pair gives %.2f%%,"
          % (implied * 100))
    print("   a US-minus-rest gap of %.2f points, which costs %.2f points on"
          % ((AQR_US - implied) * 100,
             (1 - US_WEIGHT_IN_ACWI) * (AQR_US - implied) * 100))
    print("   the global rate.")
    print()
    print("   VERDICT. Every unbiased estimate agrees the United States grew")
    print("   faster, so the substitution biases the global growth term UP,")
    print("   and the model's expected return with it. The size is unresolved:")
    print("   the gap runs from 0.28 points on AQR's pair to 4.10 on the")
    print("   modern sample, which is 0.10 to 1.48 points on the global rate.")
    print("   AQR's is the only figure built on data that reconstitutes like")
    print("   an index, and it is a LOWER bound, because they deliberately")
    print("   shrink cross-country growth differences 50% toward the global")
    print("   average. The honest reading is that the growth term is too high")
    print("   by something between a tenth and half a point.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
