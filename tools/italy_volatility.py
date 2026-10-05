"""The Italian variant's fixed volatility, measured.

    python tools/italy_volatility.py            # uses the cached levels
    python tools/italy_volatility.py --fetch    # downloads them first

Choi, Liu and Liu's 18.5% is the annualised standard deviation of monthly log
returns in excess of the one-month Treasury, over 98 years. In a sample that long it hardly matters on which day of
the month the returns are measured: on the S&P 500 since 1928 month-end
sampling gives 18.5% and the average over every day of the month 18.8%. Over
the 25 years of world-index data in euro it matters a great deal. The crashes
of October 2008 and March 2020 were each split across two month-end returns,
so month-end to month-end gives 13.99%, the lowest of the 28 days a month
always has. That figure was used until October 2026.

Every day of the month is an equally valid place to start Choi's estimator, so
this tool runs it from each day 1 to 28 (the last trading day on or before
that date, each month), averages the 28 variances and takes the square root.
That is the volatility the Italian variant holds fixed.

The levels are MSCI's own: All Country World (892400), gross, in euro, daily,
from the service tools/refresh_italy.py reads. They are cached in data/ so the
test can recompute the constant offline; like everything in data/ they are
third-party and are not committed.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import ssl
import statistics
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "msci_acwi_eur_daily.json"

DAILY = ("https://app2.msci.com/products/service/index/indexmaster/"
         "getLevelDataForGraph?currency_symbol=EUR&index_variant=GRTR"
         "&start_date={start}&end_date={end}&data_frequency=DAILY"
         "&index_codes=892400")

# The window: every month from January 2001, the first with a full month of
# daily levels behind it, to August 2026, the last month measured when the
# figure was fixed.
FIRST = (2001, 1)
LAST = (2026, 8)
DAYS = range(1, 29)

# The 28 figures this tool measured when the volatility was fixed, day 1 to
# day 28. Derived numbers, not MSCI's levels, so they can be committed: the
# test checks the constant against them on every run, and against a fresh
# measurement wherever the daily levels are cached. Month-end alone gave
# 0.139860, below every one of them.
MEASURED = (
    0.143155, 0.146906, 0.149950, 0.154704, 0.157892, 0.156407, 0.158001,
    0.161012, 0.163713, 0.162797, 0.163285, 0.168226, 0.157253, 0.158466,
    0.161247, 0.172639, 0.164877, 0.170056, 0.178715, 0.182609, 0.181995,
    0.183180, 0.183994, 0.171919, 0.166573, 0.160336, 0.162032, 0.155664,
)
MONTH_END = 0.139860


def _context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def fetch() -> dict[str, float]:
    """Daily levels from December 2000 on, in three-year requests, which is
    what the service answers reliably."""
    levels: dict[str, float] = {}
    for year in range(2000, date.today().year + 1, 3):
        url = DAILY.format(start=f"{year}0101", end=f"{year + 2}1231")
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=90,
                                    context=_context()) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        for row in payload["indexes"]["INDEX_LEVELS"]:
            if row["level_eod"] > 0:
                levels[str(row["calc_date"])] = float(row["level_eod"])
    return levels


def monthly_volatility(levels: dict[str, float], day: int) -> float:
    """Choi's estimator, on total rather than excess returns, started on one day
    of the month: the annualised sample
    standard deviation of monthly log returns, each month's level being the
    last one on or before that day."""
    dates = sorted(levels)
    keys = [date(int(d[:4]), int(d[4:6]), int(d[6:])) for d in dates]
    points = []
    year, month = FIRST
    while (year, month) <= LAST:
        i = bisect.bisect_right(keys, date(year, month, day)) - 1
        if i < 0:
            raise ValueError(f"no level on or before {year}-{month:02d}-{day:02d}")
        points.append(levels[dates[i]])
        month += 1
        if month == 13:
            year, month = year + 1, 1
    returns = [math.log(b / a) for a, b in zip(points, points[1:])]
    return statistics.stdev(returns) * math.sqrt(12)


def volatility(levels: dict[str, float]) -> tuple[float, list[float]]:
    """The square root of the average variance over days 1 to 28."""
    by_day = [monthly_volatility(levels, day) for day in DAYS]
    return math.sqrt(statistics.fmean(v * v for v in by_day)), by_day


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true",
                        help="download the daily levels and cache them")
    args = parser.parse_args(argv[1:])

    if args.fetch or not CACHE.exists():
        levels = fetch()
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(levels), encoding="utf-8")
    levels = json.loads(CACHE.read_text(encoding="utf-8"))

    sigma, by_day = volatility(levels)
    print("MSCI All Country World, gross, in euro: monthly log returns,")
    print(f"{FIRST[0]}-{FIRST[1]:02d} to {LAST[0]}-{LAST[1]:02d}, from each day of the month")
    for day, v in zip(DAYS, by_day):
        print(f"  day {day:2d}   {v:.4%}")
    print(f"  lowest {min(by_day):.4%}, highest {max(by_day):.4%}")
    print(f"\nvolatility held fixed: {sigma:.6f}")
    sys.path.insert(0, str(ROOT / "tools"))
    import refresh_italy
    if abs(refresh_italy.ITALY_VOLATILITY - round(sigma, 6)) > 5e-7:
        print(f"refresh_italy.ITALY_VOLATILITY is {refresh_italy.ITALY_VOLATILITY}; "
              f"it should be {round(sigma, 6)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
