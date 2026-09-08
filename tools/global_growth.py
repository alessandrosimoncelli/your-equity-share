"""Build a global real dividend growth rate, and find out if it can be used.

    python tools/global_growth.py

The Italian variant takes AQR's expected return rather than computing its own,
and the reason given was that no global equivalent of Shiller's series exists.
That was an assertion. This tests it.

WHAT THE DATA IS. The Jordà-Schularick-Taylor Macrohistory Database, release
6: eighteen advanced economies, annual, from 1870, free under a licence that
forbids commercial data providers from reselling it. It carries equity
dividend yields, capital gains and consumer prices, which is enough to rebuild
equation (5) on a global index instead of the S&P 500.

Dividends rather than earnings per share, because JST has no EPS. The American
methodology already prices that swap in its Table 7: dividend growth scores
2.35 root mean square error at thirty years against 2.25 for per-share
earnings growth. Worse, and not by much.

    D_t / D_{t-1} = (dp_t / dp_{t-1}) x (1 + capgain_t)

since dp is D/P and capgain is the change in P. Deflating by CPI makes it real.

WHAT IT SHOWS, which is why the Italian variant still uses AQR's number. The
estimate moves 1.82 points depending on which start year you pick, even under
the most robust construction available: a median across countries so no single
hyperinflation carries the aggregate, with the war years dropped. The American
estimator moves 0.25 points when its window changes by twenty years. A global
series spanning two world wars, several currency reforms and a few closed
exchanges cannot be pinned the way one uninterrupted market can, and an
estimate that swings almost two points on a choice nobody can justify is a
choice wearing the clothes of a measurement.

So this is not the Italian variant's expected return. It is the check on it,
and the check passes: AQR's 2.6% falls inside the range this independent
reconstruction produces from free data.
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


def trend(growth, first_year: int, robust: bool, drop_wars: bool):
    """Chain a global index from the cross-country growth, then fit its slope.

    A median across countries rather than a mean, when robust, so that one
    country's currency reform cannot carry the aggregate. Germany's dividend
    index does things across 1923 and 1948 that are history rather than
    economics, and a mean lets that through.
    """
    years = sorted({y for series in growth.values() for y in series})
    level, index = 1.0, {}
    for year in years:
        if year < first_year:
            continue
        if drop_wars and (1914 <= year <= 1919 or 1939 <= year <= 1949):
            continue
        factors = [s[year] for s in growth.values()
                   if year in s and 0.2 < s[year] < 5.0]
        if len(factors) < 8:
            continue
        level *= statistics.median(factors) if robust else sum(factors) / len(factors)
        index[year] = level

    points = sorted(index.items())
    if len(points) < 25:
        return None
    xs = [y for y, _ in points]
    ys = [math.log(v) for _, v in points]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    return math.exp(numerator / denominator) - 1


def main() -> int:
    path = find_dataset(os.environ.get(JST_ENV))
    if path is None:
        print("The Jordà-Schularick-Taylor dataset was not found.")
        print("  looked in: %s"
              % ", ".join(str(c) for c in dataset_candidates(None)))
        print(f"  Download {DATASET} from {JST_URL} and put it at one of those")
        print(f"  paths, or point {JST_ENV} at it.")
        return 0

    print("Global real dividend growth, from %s" % path.name)
    print("=" * 74)
    growth = annual_real_dividend_growth(path)
    years = sorted({y for s in growth.values() for y in s})
    print("  %d countries, %d to %d\n" % (len(growth), years[0], years[-1]))

    windows = (1870, 1920, 1950, 1970)
    print("%-38s %8s %8s %8s %8s" % ("construction", *windows))
    spreads = {}
    for robust in (False, True):
        for drop_wars in (False, True):
            label = ("%s across countries%s"
                     % ("median" if robust else "mean",
                        ", wars dropped" if drop_wars else ""))
            values = [trend(growth, first, robust, drop_wars) for first in windows]
            shown = ["%.2f%%" % (v * 100) if v is not None else "   -"
                     for v in values]
            real = [v * 100 for v in values if v is not None]
            spreads[label] = max(real) - min(real)
            print("%-38s %8s %8s %8s %8s" % (label, *shown))

    best = min(spreads, key=spreads.get)
    spread = spreads[best]
    print()
    print("  The most stable construction is the %s," % best)
    print("  and it still moves %.2f points depending on the start year." % spread)
    print("  The American estimator moves %.2f points when its window changes"
          % US_WINDOW_SENSITIVITY)
    print("  by twenty years, so this is roughly %.0f times as sensitive to a"
          % (spread / US_WINDOW_SENSITIVITY))
    print("  choice nobody can justify. That is why the Italian variant uses")
    print("  AQR's figure and treats this as the check on it rather than the")
    print("  other way round.")

    low = min(v for v in (trend(growth, f, True, True) for f in windows)
              if v is not None)
    high = max(v for v in (trend(growth, f, True, True) for f in windows)
               if v is not None)
    inside = low <= AQR_GLOBAL_GROWTH <= high
    print()
    print("  This reconstruction, robust, spans   %.2f%% to %.2f%%"
          % (low * 100, high * 100))
    print("  AQR's global real EPS growth         %.2f%%"
          % (AQR_GLOBAL_GROWTH * 100))
    print("  %s" % ("AQR sits inside the range, so the borrowed number is "
                    "corroborated" if inside else
                    "AQR sits OUTSIDE the range, which needs explaining"))
    return 0 if inside else 1


if __name__ == "__main__":
    raise SystemExit(main())
