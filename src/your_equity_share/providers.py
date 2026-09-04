"""Parsing the responses of the free data providers.

Kept apart from the fetching so that every parser can be tested against a
fixture with no network. `update.py` does the fetching and calls these.

Three sources, all free and none needing a key or an account:

    FRED            the 30-year TIPS yield, a real yield directly
    Yahoo chart     daily adjusted closes, for the volatility estimate
    Damodaran       the implied equity risk premium, monthly
"""

from __future__ import annotations

import csv
import io
import math
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone

__all__ = [
    "DataUnavailable",
    "PriceSeries",
    "ShillerHistory",
    "parse_damodaran_components",
    "parse_damodaran_erp",
    "parse_fred_csv",
    "parse_multpl_current",
    "parse_price_json",
    "parse_shiller_csv",
]

# Excel stores dates as a day count from an epoch. Which epoch depends on a flag
# in the workbook, and the two are four years apart, so guessing wrong dates
# every observation four years out.
_EPOCH_1900 = date(1899, 12, 30)
_EPOCH_1904 = date(1904, 1, 1)


class DataUnavailable(Exception):
    """A provider could not be reached or returned something unusable."""


class PriceSeries:
    """Daily closes for one instrument, keyed by ISO date."""

    __slots__ = ("ticker", "closes", "adjusted")

    def __init__(self, ticker: str, closes: dict[str, float], adjusted: bool) -> None:
        self.ticker = ticker
        self.closes = closes
        self.adjusted = adjusted


def parse_price_json(text: str, ticker: str) -> PriceSeries:
    """Parse Yahoo's chart JSON, preferring the adjusted close.

    `adjclose` is adjusted for both splits and dividends, so successive ratios
    are total returns. `close` is adjusted for splits only, which leaves a small
    downward step on each ex-dividend day. Measured on five years of SPY, using
    the unadjusted series overstates annual volatility by about 4 basis points.
    Small, but there is no reason to accept it when the better series is in the
    same response.

    Rows with a null close are dropped: the provider emits them for days the
    exchange was shut, and carrying them as zeros would manufacture crashes.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        head = text.strip().splitlines()[:1]
        raise DataUnavailable(
            f"{ticker}: response is not JSON. First line: {head}"
        ) from None

    error = (payload.get("chart") or {}).get("error")
    if error:
        raise DataUnavailable(f"{ticker}: provider returned an error: {error}")

    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
    except (KeyError, IndexError, TypeError):
        raise DataUnavailable(
            f"{ticker}: response did not contain a price series"
        ) from None

    adjusted = True
    series = None
    try:
        series = result["indicators"]["adjclose"][0]["adjclose"]
    except (KeyError, IndexError, TypeError):
        adjusted = False
    if series is None:
        try:
            series = result["indicators"]["quote"][0]["close"]
            adjusted = False
        except (KeyError, IndexError, TypeError):
            raise DataUnavailable(
                f"{ticker}: response contained neither adjclose nor close"
            ) from None

    if len(stamps) != len(series):
        raise DataUnavailable(
            f"{ticker}: {len(stamps)} timestamps but {len(series)} closes"
        )

    closes: dict[str, float] = {}
    for stamp, value in zip(stamps, series):
        if value is None:
            continue
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        closes[day] = float(value)

    if not closes:
        raise DataUnavailable(f"{ticker}: no usable observations in the response")
    return PriceSeries(ticker, closes, adjusted)


def parse_fred_csv(text: str, series: str) -> tuple[date, float]:
    """Return the most recent non-missing observation of a FRED series.

    FRED writes a lone full stop for a missing day, which is common on holidays
    and at the start of a series.
    """
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise DataUnavailable(f"{series}: unexpected response from FRED")
    latest: tuple[date, float] | None = None
    for row in reader:
        if len(row) < 2:
            continue
        day, raw = row[0].strip(), row[1].strip()
        if raw in ("", "."):
            continue
        try:
            latest = (date.fromisoformat(day), float(raw) / 100.0)
        except ValueError:
            continue
    if latest is None:
        raise DataUnavailable(f"{series}: no observations in the response")
    return latest


def _sheet_path(zf: zipfile.ZipFile, wanted: str) -> str:
    """Locate a worksheet by its tab name rather than by position."""
    workbook = zf.read("xl/workbook.xml").decode("utf-8", "replace")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")

    rid = None
    for match in re.finditer(r"<sheet\b([^>]*)/?>", workbook):
        attrs = match.group(1)
        name = re.search(r'name="([^"]*)"', attrs)
        ident = re.search(r'r:id="([^"]*)"', attrs)
        if name and ident and name.group(1).strip().lower() == wanted.lower():
            rid = ident.group(1)
            break
    if rid is None:
        raise DataUnavailable(f'workbook has no sheet named "{wanted}"')

    relationship = re.search(
        rf'<Relationship[^>]*Id="{re.escape(rid)}"[^>]*/?>', rels
    )
    if relationship is None:
        raise DataUnavailable(f"workbook relationship {rid} is missing")
    target = re.search(r'Target="([^"]*)"', relationship.group(0))
    if target is None:
        raise DataUnavailable(f"workbook relationship {rid} has no target")
    path = target.group(1).lstrip("/")
    path = path if path.startswith("xl/") else f"xl/{path}"
    if "/worksheets/" not in path:
        # A tab can be a chart rather than a grid. In this workbook the tab
        # called "ERP in last 12 months" is exactly that, which is why the data
        # is read from "Last 12 months data" instead.
        raise DataUnavailable(
            f'sheet "{wanted}" is not a data worksheet, it resolves to {path}'
        )
    return path


def parse_damodaran_erp(data: bytes) -> tuple[date, float]:
    """Latest monthly implied equity risk premium for the S&P 500.

    Damodaran publishes this monthly. It is a forward-looking premium implied by
    discounting expected index cash flows back to the current level, which is a
    different construct from a historical average, and the only credible free
    source of a forward-looking number this project has found.

    The workbook uses the 1904 date system. Assuming the more common 1900 epoch
    would date every observation exactly four years early, so the flag is read
    rather than guessed.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise DataUnavailable(
            "the equity risk premium download is not a readable workbook"
        ) from None

    with archive as zf:
        workbook = zf.read("xl/workbook.xml").decode("utf-8", "replace")
        epoch = _EPOCH_1904 if 'date1904="1"' in workbook else _EPOCH_1900
        sheet = zf.read(_sheet_path(zf, "Last 12 months data")).decode(
            "utf-8", "replace"
        )

    latest: tuple[int, float] | None = None
    for row in re.finditer(r"<row\b[^>]*>(.*?)</row>", sheet, re.S):
        cells: dict[str, float] = {}
        for cell in re.finditer(r'<c\b([^>]*?)/?>(?:(.*?)</c>)?', row.group(1), re.S):
            ref = re.search(r'r="([A-Z]+)\d+"', cell.group(1))
            value = re.search(r"<v>(.*?)</v>", cell.group(2) or "", re.S)
            if ref and value and 't="s"' not in cell.group(1):
                try:
                    cells[ref.group(1)] = float(value.group(1))
                except ValueError:
                    pass
        # In this sheet: A month, B index level, C 10-year Treasury, D premium.
        if "A" in cells and "D" in cells:
            serial = int(cells["A"])
            if latest is None or serial > latest[0]:
                latest = (serial, cells["D"])

    if latest is None:
        raise DataUnavailable("no equity risk premium rows found in the workbook")

    serial, premium = latest
    if not 0.0 < premium < 0.25:
        raise DataUnavailable(
            f"implied equity risk premium of {premium:.1%} is outside any "
            f"plausible range; the workbook layout has probably changed"
        )
    from datetime import timedelta

    return epoch + timedelta(days=serial), premium


@dataclass(frozen=True)
class ShillerHistory:
    """Robert Shiller's monthly S&P 500 series, cleaned.

    Only months carrying a real price, a real dividend and a CAPE are kept, so
    the three lists are aligned and every entry is usable. Recent months often
    lack fundamentals even when a price exists, and those are dropped rather
    than carried as zeros.
    """

    dates: tuple[str, ...]
    real_prices: tuple[float, ...]
    real_dividends: tuple[float, ...]
    real_earnings: tuple[float, ...]
    cape: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.dates)

    @property
    def last_date(self) -> str:
        """The most recent month carrying usable fundamentals.

        Worth surfacing. The published series runs months behind the market:
        prices arrive promptly, the earnings needed for a cyclically adjusted
        ratio do not, and the feed has at times stopped updating the derived
        columns altogether while still appending price rows.
        """
        return self.dates[-1]

    def real_earnings_trend_growth(self, years: int) -> float:
        """Real growth in earnings per share, as the trend through the window.

        Preferred over the point-to-point rate. Both describe the same century,
        but a point-to-point rate is decided by two months and inherits
        whatever the cycle was doing in each of them. Measured on this data:

            varying the window 90 to 110 years   point to point 1.27%, trend 0.25%
            moving the end date back 0 to 36mo   point to point 0.82%, trend 0.015%

        The second line is the one that matters here. The published series runs
        months behind, and with a trend estimate three years of lag costs about
        a basis point, so the staleness stops being a problem worth solving.

        Ordinary least squares on log earnings against time, annualised.
        """
        months = years * 12
        if len(self.real_earnings) <= months:
            raise DataUnavailable(
                f"only {len(self.real_earnings) // 12} years of earnings, "
                f"need {years}"
            )
        window = self.real_earnings[-months:]
        bad = [d for d, e in zip(self.dates[-months:], window) if e <= 0]
        if bad:
            raise DataUnavailable(
                f"{len(bad)} month(s) of non-positive real earnings inside the "
                f"{years} year window, first at {bad[0]}"
            )
        n = len(window)
        xs = range(n)
        ys = [math.log(v) for v in window]
        mean_x = (n - 1) / 2.0
        mean_y = sum(ys) / n
        sxx = sum((x - mean_x) ** 2 for x in xs)
        sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        return math.exp((sxy / sxx) * 12.0) - 1.0

    def real_earnings_growth(self, years: int) -> float:
        """Annualised real growth in earnings per share over the last `years`.

        The window is taken from the end of the series and must be contiguous.
        An earlier version filtered non-positive earnings out first and then
        sliced by count, which would have silently reached further back than
        the window it claimed while still dividing by the claimed number of
        months, overstating the growth rate. Nothing is filtered now: a
        non-positive month inside the window is an error, not something to
        step over.
        """
        months = years * 12
        if len(self.real_earnings) <= months:
            raise DataUnavailable(
                f"only {len(self.real_earnings) // 12} years of earnings, "
                f"need {years}"
            )
        window = self.real_earnings[-months:]
        bad = [d for d, e in zip(self.dates[-months:], window) if e <= 0]
        if bad:
            raise DataUnavailable(
                f"{len(bad)} month(s) of non-positive real earnings inside the "
                f"{years} year window, first at {bad[0]}; the growth rate would "
                f"not describe the period it claims"
            )
        return (window[-1] / window[0]) ** (12.0 / (len(window) - 1)) - 1.0


def parse_shiller_csv(text: str) -> ShillerHistory:
    """Parse the Shiller dataset as published in CSV form."""
    reader = csv.DictReader(io.StringIO(text))
    required = {"Date", "Real Price", "Real Dividend", "Real Earnings", "PE10"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise DataUnavailable(
            f"Shiller data is missing columns; got {reader.fieldnames}"
        )

    dates, prices, dividends, earnings, cape = [], [], [], [], []
    for row in reader:
        try:
            price = float(row["Real Price"])
            dividend = float(row["Real Dividend"])
            earning = float(row["Real Earnings"])
            ratio = float(row["PE10"])
        except (TypeError, ValueError):
            continue
        if price <= 0 or dividend <= 0 or ratio <= 0:
            continue
        dates.append(row["Date"])
        prices.append(price)
        dividends.append(dividend)
        earnings.append(earning)
        cape.append(ratio)

    if len(dates) < 600:
        raise DataUnavailable(
            f"only {len(dates)} usable months of Shiller data, expected decades"
        )
    return ShillerHistory(
        tuple(dates), tuple(prices), tuple(dividends), tuple(earnings), tuple(cape)
    )


def parse_multpl_current(html: str, label: str) -> float:
    """The current value from a multpl.com page.

    The page states its figure in a block marked "current". Scraping is
    fragile by nature, so the result is range-checked by the caller and the
    whole fetch is optional: the tool falls back to the last CAPE in Shiller's
    own history if this fails.
    """
    match = re.search(r'id="current"[^>]*>(.*?)</div>', html, re.S)
    if match is None:
        raise DataUnavailable(f"{label}: no current value found on the page")
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    number = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if number is None:
        raise DataUnavailable(f"{label}: could not read a number from the page")
    return float(number.group(1))


def parse_damodaran_components(data: bytes) -> tuple[date, float, float]:
    """Index level, trailing payout yield and cyclically adjusted payout yield.

    From the historical sheet of the same workbook the premium comes from.
    Column B is the index, F the trailing twelve month cash returned to
    shareholders, which is dividends *and* buybacks, and E a ten-year average
    of the same. Returns (month, F/B, E/B).
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise DataUnavailable("the workbook download is not readable") from None

    with archive as zf:
        workbook = zf.read("xl/workbook.xml").decode("utf-8", "replace")
        epoch = _EPOCH_1904 if 'date1904="1"' in workbook else _EPOCH_1900
        sheet = zf.read(_sheet_path(zf, "Historical ERP")).decode("utf-8", "replace")

    best: tuple[int, float, float] | None = None
    for row in re.finditer(r"<row\b[^>]*>(.*?)</row>", sheet, re.S):
        cells: dict[str, float] = {}
        for cell in re.finditer(r"<c\b([^>]*?)/?>(?:(.*?)</c>)?", row.group(1), re.S):
            ref = re.search(r'r="([A-Z]+)\d+"', cell.group(1))
            value = re.search(r"<v>(.*?)</v>", cell.group(2) or "", re.S)
            if ref and value and 't="s"' not in cell.group(1):
                try:
                    cells[ref.group(1)] = float(value.group(1))
                except ValueError:
                    pass
        if {"A", "B", "E", "F"} <= cells.keys() and cells["B"] > 0:
            serial = int(cells["A"])
            if best is None or serial > best[0]:
                best = (serial, cells["F"] / cells["B"], cells["E"] / cells["B"])

    if best is None:
        raise DataUnavailable("no payout rows found in the workbook")
    serial, trailing, smoothed = best
    if not 0.0 < trailing < 0.20 or not 0.0 < smoothed < 0.20:
        raise DataUnavailable(
            f"payout yields of {trailing:.1%} and {smoothed:.1%} are implausible; "
            f"the workbook layout has probably changed"
        )
    from datetime import timedelta

    return epoch + timedelta(days=serial), trailing, smoothed
