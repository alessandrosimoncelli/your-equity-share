"""Can a global growth rate be measured, or only borrowed?

    python tools/global_growth.py

The Italian variant needs real growth in earnings per share for a global index.
It uses the American estimator, the hundred-year trend through Shiller, and
that needs justifying because the index is not American. This is the attempt to
do better, and it is reported because it FAILED, which is the justification.

WHAT THE DATA IS. The Jorda-Schularick-Taylor Macrohistory Database, release 6:
eighteen advanced economies, annual, from 1870, free under a licence that
forbids commercial data providers from reselling it. It carries equity dividend
yields, capital gains and consumer prices, which is enough to rebuild equation
(5) on a global index instead of the S&P 500.

Dividends rather than earnings per share, because JST has no EPS. The American
methodology already prices that swap in its Table 7: dividend growth scores
2.35 root mean square error at thirty years against 2.25 for per-share earnings
growth. Worse, and not by much.

    D_t / D_{t-1} = (dp_t / dp_{t-1}) x (1 + capgain_t)

since dp is D/P and capgain is the change in P. Deflating by CPI makes it real.

WHAT IT SHOWS. The answer depends on how the countries are weighted far more
than it depends on the data, and no weighting is right:

    weights pinned at today       0.89% to 1.52%
    weights pinned at the start   1.86% to 3.04%
    GDP share, year by year       2.77% to 5.43%

That is an envelope 4.5 points wide, and keeping the war years rather than
dropping them widens it further. The American estimator moves 0.25 points
when its window changes by twenty years.

WHY IT FAILS, which matters more than that it does. A fixed basket of countries
is not an index. An index RECONSTITUTES: it drops the markets and companies
that stop paying and admits the ones that start, and that churn is most of the
difference between a survivor basket's dividend record and a real index's.
JST publishes country index returns, not the world index's constituents, so
reconstitution cannot be reproduced at all. Pinning the weights at today then
asks what today's survivors paid a century ago, which is hindsight; pinning
them at the start hands 1870 the United States at 72%, which is fiction.

TWO CORRECTIONS THIS FILE HAS ALREADY NEEDED, recorded because they are the
kind of error the construction invites.

The first version averaged growth FACTORS across countries each year and
chained the average. That is a portfolio rebalanced to fixed weights annually,
and a rebalanced portfolio compounds faster than its constituents do by roughly
half the cross-sectional variance. It was worth 0.21 points, and it made the
estimate look five times steadier than the American one, which is what gave it
away.

The second was reporting one scheme's range, 1.33% to 3.16%, as though it were
the uncertainty. It is a quarter of the uncertainty.

SO WHAT IS IT FOR. It brackets. The variant's 2.286% and AQR's 2.6% both fall
inside the envelope, which is corroboration too weak to lean on and is reported
as exactly that. The growth term is justified in config/market_data_it.toml on
other grounds: AQR publish 2.7% for United States large cap and 2.6% for Global
All Country, a tenth of a point apart, and long-run real growth in earnings per
share is a return on retained capital rather than a national characteristic.
"""

from __future__ import annotations

import math
import os
import re
import statistics
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DATASET = "JSTdatasetR6.xlsx"
JST_ENV = "JST_DATASET"
JST_URL = "https://www.macrohistory.net/database/"

# AQR, Alternative Thinking 2026 Issue 1, Exhibit 3A, as of 31 December 2025.
AQR_GLOBAL_GROWTH = 0.026
AQR_GLOBAL_YIELD = 0.016
AQR_GLOBAL_RETURN = 0.042

# The window the American variant uses, and how far it moves when that window
# is changed by twenty years. Table 9 of the methodology.
US_WINDOW_SENSITIVITY = 0.25


def dataset_candidates(override: str | None) -> list[Path]:
    if override:
        return [Path(override)]
    return [ROOT / "data" / DATASET, ROOT.parent / DATASET]


def find_dataset(override: str | None = None) -> Path | None:
    for candidate in dataset_candidates(override):
        if candidate.exists():
            return candidate
    return None


def read_rows(path: Path):
    book = zipfile.ZipFile(path)
    shared = ["".join(t.text or "" for t in si.iter(NS + "t"))
              for si in ET.fromstring(book.read("xl/sharedStrings.xml")).iter(NS + "si")]
    sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))

    def cells(row):
        out = {}
        for cell in row.iter(NS + "c"):
            column = 0
            for char in re.match(r"([A-Z]+)", cell.get("r")).group(1):
                column = column * 26 + (ord(char) - 64)
            value = cell.find(NS + "v")
            if value is not None and value.text is not None:
                out[column - 1] = (shared[int(value.text)]
                                   if cell.get("t") == "s" else value.text)
        return out

    rows = list(sheet.iter(NS + "row"))
    return rows, cells


def annual_real_dividend_growth(path: Path) -> dict[str, dict[int, float]]:
    """Per country, the year-on-year growth factor of real dividends."""
    rows, cells = read_rows(path)
    index = {name: i for i, name in cells(rows[0]).items()}
    observations: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in rows[1:]:
        cell = cells(row)
        try:
            year = int(float(cell[index["year"]]))
            iso = cell[index["iso"]]
        except (KeyError, ValueError):
            continue
        record = {}
        for field in ("cpi", "eq_dp", "eq_capgain"):
            if index.get(field) in cell:
                try:
                    record[field] = float(cell[index[field]])
                except ValueError:
                    pass
        observations[iso][year] = record

    growth: dict[str, dict[int, float]] = defaultdict(dict)
    for iso, series in observations.items():
        years = sorted(series)
        for previous, current in zip(years, years[1:]):
            before, after = series[previous], series[current]
            if not {"eq_dp", "cpi"} <= before.keys():
                continue
            if not {"eq_dp", "cpi", "eq_capgain"} <= after.keys():
                continue
            if min(before["eq_dp"], after["eq_dp"],
                   before["cpi"], after["cpi"]) <= 0:
                continue
            nominal = ((after["eq_dp"] / before["eq_dp"])
                       * (1.0 + after["eq_capgain"]))
            growth[iso][current] = nominal / (after["cpi"] / before["cpi"])
    return growth


# MSCI World country weights, 31 August 2026, from the index factsheet. They
# are only a weighting, and one of the schemes below dispenses with them
# entirely, which is the point.
WEIGHTS = {
    "USA": 72.14, "JPN": 5.78, "GBR": 3.53, "CAN": 3.30, "FRA": 2.40,
    "CHE": 2.40, "DEU": 2.30, "AUS": 1.80, "NLD": 1.30, "SWE": 0.80,
    "ITA": 0.80, "ESP": 0.70, "DNK": 0.60, "FIN": 0.20, "BEL": 0.20,
    "NOR": 0.20, "IRL": 0.15, "PRT": 0.03,
}

# In MSCI World but not in JST: Hong Kong, Singapore, Israel, New Zealand and
# Austria, about 1.1% between them. Dropped, and the weights renormalised.

WAR_YEARS = frozenset(range(1914, 1920)) | frozenset(range(1939, 1950))

# Start years. Nine rather than four, because a spread measured on four points
# is a claim about four points.
STARTS = (1870, 1880, 1890, 1900, 1910, 1920, 1930, 1950, 1960)

# Shiller says real earnings per share grew 0.52 points a year faster than real
# dividends over this history, because American payout ratios fell for a
# century as buybacks replaced dividends. JST carries dividends and the thing
# being checked is earnings, so the wedge has to be added before the comparison
# means anything. It is stable: +0.47, +0.47, +0.65 and +0.50 from 1870, 1900,
# 1920 and 1950.
EPS_WEDGE = 0.52

# What the Italian configuration uses, and what AQR publish for the same index.
CONFIG_GROWTH = 2.286
AQR_GLOBAL_GROWTH = 2.60

# The American estimator's own sensitivity: its trend moves this much when the
# window changes from ninety years to a hundred and ten.
US_WINDOW_SENSITIVITY = 0.25


def slope(points: dict[int, float]) -> float | None:
    """The annual growth rate implied by the OLS slope of the log level."""
    pairs = sorted(points.items())
    if len(pairs) < 25:
        return None
    xs = [x for x, _ in pairs]
    ys = [math.log(v) for _, v in pairs]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    return math.exp(numerator / denominator) - 1


def country_levels(growth, first_year: int, drop_wars: bool):
    """Each country's real dividend level, chained from its growth factors.

    Only countries covering the whole window are kept. One appearing halfway
    through would inject its weight at that point, which is a rebalance by
    another name and the bias this file already had once.
    """
    kept = {}
    for iso in WEIGHTS:
        if iso not in growth:
            continue
        level, index = 1.0, {}
        for year in sorted(growth[iso]):
            if year < first_year or (drop_wars and year in WAR_YEARS):
                continue
            factor = growth[iso][year]
            if not 0.2 < factor < 5.0:
                continue
            level *= factor
            index[year] = level
        years = sorted(index)
        if (years and years[0] <= first_year + 3 and years[-1] >= 2015
                and len(index) >= 25):
            kept[iso] = index
    return kept


def basket(levels, pin: str):
    """A fixed basket of the country series, normalised at one end or the other.

    Pinning at TODAY is what a cap-weighted index is: its dividend is the sum
    of its constituents' dividends and today's weights are a fact. Running that
    backwards asks what today's survivors were paying a century ago, which is
    hindsight. Pinning at the START instead hands 1870 an index that is 72%
    American. Neither is right, and the gap between them is the point.
    """
    if not levels:
        return {}
    common = sorted(set.intersection(*(set(v) for v in levels.values())))
    if not common:
        return {}
    at = common[-1] if pin == "today" else common[0]
    return {year: sum(WEIGHTS[iso] * series[year] / series[at]
                      for iso, series in levels.items())
            for year in common}


def gdp_shares(path: Path):
    """Each country's share of the sample's GDP, year by year.

    A weighting that needs to know nothing about today, as a check on whether
    knowing about today is carrying the answer. Nominal GDP in local currency
    is not comparable across countries, so it is converted at the exchange rate
    against the dollar that JST carries beside it.
    """
    rows, cells = read_rows(path)
    index = {name: i for i, name in cells(rows[0]).items()}
    if "gdp" not in index or "xrusd" not in index:
        return None
    raw: dict[int, dict[str, float]] = defaultdict(dict)
    for row in rows[1:]:
        cell = cells(row)
        try:
            year = int(float(cell[index["year"]]))
            iso = cell[index["iso"]]
            gdp = float(cell[index["gdp"]])
            rate = float(cell[index["xrusd"]])
        except (KeyError, ValueError):
            continue
        if gdp > 0 and rate > 0 and iso in WEIGHTS:
            raw[year][iso] = gdp / rate
    shares = {}
    for year, by_iso in raw.items():
        total = sum(by_iso.values())
        if total > 0:
            shares[year] = {i: v / total * 100.0 for i, v in by_iso.items()}
    return shares


def gdp_weighted(growth, shares, first_year: int, drop_wars: bool):
    """Weights follow GDP share each year, so they know nothing about today."""
    years = sorted({y for series in growth.values() for y in series})
    level, index = 1.0, {}
    for year in years:
        if year < first_year or (drop_wars and year in WAR_YEARS):
            continue
        weights = shares.get(year)
        if not weights:
            continue
        pairs = [(weights[iso], series[year])
                 for iso, series in growth.items()
                 if iso in weights and year in series
                 and 0.2 < series[year] < 5.0]
        if len(pairs) < 8:
            continue
        total = sum(w for w, _ in pairs)
        level *= sum(w * g for w, g in pairs) / total
        index[year] = level
    return index


def main() -> int:
    path = find_dataset(os.environ.get(JST_ENV))
    if path is None:
        print("The Jorda-Schularick-Taylor dataset was not found.")
        print("  looked in: %s"
              % ", ".join(str(c) for c in dataset_candidates(None)))
        print(f"  Download {DATASET} from {JST_URL} and put it at one of those")
        print(f"  paths, or point {JST_ENV} at it.")
        return 0

    print("Global real dividend growth, from %s" % path.name)
    print("=" * 78)
    growth = annual_real_dividend_growth(path)
    years = sorted({y for s in growth.values() for y in s})
    covered = sum(w for iso, w in WEIGHTS.items() if iso in growth)
    print("  %d countries, %d to %d, covering %.1f%% of MSCI World by weight"
          % (len(growth), years[0], years[-1], covered))
    print("  War years are dropped throughout: 1914 to 1919 and 1939 to 1949.\n")

    shares = gdp_shares(path)
    schemes = [
        ("weights pinned at today",
         lambda first: slope(basket(country_levels(growth, first, True),
                                    "today"))),
        ("weights pinned at the start",
         lambda first: slope(basket(country_levels(growth, first, True),
                                    "start"))),
    ]
    if shares:
        schemes.append(("GDP share, year by year",
                        lambda first: slope(gdp_weighted(growth, shares,
                                                         first, True))))

    print("  %-28s %s" % ("weighting scheme",
                          " ".join("%6d" % s for s in STARTS)))
    envelope = []
    for label, estimate in schemes:
        values = [estimate(first) for first in STARTS]
        real = [v * 100 for v in values if v is not None]
        envelope += real
        print("  %-28s %s   %.2f to %.2f"
              % (label,
                 " ".join("%6s" % ("%.2f" % (v * 100) if v is not None else "-")
                          for v in values),
                 min(real), max(real)))

    width = max(envelope) - min(envelope)
    print()
    print("  The envelope is %.2f%% to %.2f%%, which is %.1f points wide."
          % (min(envelope), max(envelope), width))
    print("  The American estimator moves %.2f points when its window changes"
          % US_WINDOW_SENSITIVITY)
    print("  by twenty years, so the weighting choice alone is %.0f times as"
          % (width / US_WINDOW_SENSITIVITY))
    print("  large as that, and no weighting here is the right one.")
    print()
    print("  A fixed basket of countries is not an index. An index")
    print("  reconstitutes, dropping what stops paying and admitting what")
    print("  starts, and JST publishes country index returns rather than the")
    print("  world index's constituents, so that cannot be reproduced.")
    print()
    print("  These are DIVIDEND growth. Adding the %+.2f point wedge Shiller"
          % EPS_WEDGE)
    print("  measures between real earnings per share and real dividends:")
    low, high = min(envelope) + EPS_WEDGE, max(envelope) + EPS_WEDGE
    print("    as earnings per share             %.2f%% to %.2f%%" % (low, high))
    print("    this variant uses                 %.3f%%   %s"
          % (CONFIG_GROWTH, "inside" if low <= CONFIG_GROWTH <= high
             else "OUTSIDE"))
    print("    AQR publish                       %.2f%%   %s"
          % (AQR_GLOBAL_GROWTH, "inside" if low <= AQR_GLOBAL_GROWTH <= high
             else "OUTSIDE"))
    print()
    print("  Both sit inside, which is corroboration too weak to lean on. The")
    print("  growth term is justified in config/market_data_it.toml on other")
    print("  grounds, and this file is the record of what the alternative")
    print("  turned out to be worth.")
    return 0 if low <= CONFIG_GROWTH <= high else 1


if __name__ == "__main__":
    raise SystemExit(main())
