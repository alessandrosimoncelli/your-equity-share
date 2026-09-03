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
import json
import re
import zipfile
from datetime import date, datetime, timezone

__all__ = [
    "DataUnavailable",
    "PriceSeries",
    "parse_damodaran_erp",
    "parse_fred_csv",
    "parse_price_json",
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
