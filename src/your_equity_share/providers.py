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
import struct
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
    "read_xls_sheet",
    "parse_shiller_xls",
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

    def last_date_as_date(self) -> date:
        """`last_date` as a date, for stamping an estimate built from this row."""
        return date.fromisoformat(self.last_date)

    @property
    def dividend_yield(self) -> float:
        """Trailing dividends over price, at the last complete month.

        Both terms come from the same row of the same file, so the ratio is
        internally consistent: one index, one deflator, one date. Pairing a
        dividend yield taken from one provider with a price taken from another
        would introduce a difference in index construction that is larger than
        the quantity being measured.
        """
        return self.real_dividends[-1] / self.real_prices[-1]

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



# --- reading a legacy .xls, with the standard library only -------------------
#
# Shiller publishes his series as a 1997-era binary .xls and nothing else, and
# Damodaran's long histories are the same. Both are authoritative and both are
# maintained; the CSV mirror this project used instead stopped carrying CPI in
# September 2023, and with it every deflated column.
#
# Two formats, both frozen since 2007, which is what makes owning a reader
# reasonable. OLE2 is the container: a header, a table of sector links, and a
# directory naming the streams. BIFF is the spreadsheet inside the "Workbook"
# stream: a flat run of [id][length][payload] records.

_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def _ole_streams(raw: bytes) -> dict[str, bytes]:
    """Every stream in an OLE2 compound file, by name."""
    if raw[:8] != _OLE_MAGIC:
        raise DataUnavailable("not a legacy Excel file")
    ssz = 1 << struct.unpack_from("<H", raw, 30)[0]
    msz = 1 << struct.unpack_from("<H", raw, 32)[0]
    n_fat = struct.unpack_from("<I", raw, 44)[0]
    dir_start = struct.unpack_from("<I", raw, 48)[0]
    cutoff = struct.unpack_from("<I", raw, 56)[0]
    mini_start = struct.unpack_from("<I", raw, 60)[0]
    difat_start = struct.unpack_from("<I", raw, 68)[0]
    n_difat = struct.unpack_from("<I", raw, 72)[0]

    def sector(i: int) -> bytes:
        off = 512 + i * ssz
        return raw[off:off + ssz]

    # The first 109 FAT sector numbers live in the header; any more are chained.
    fat_sectors = list(struct.unpack_from("<109I", raw, 76))
    nxt = difat_start
    for _ in range(n_difat):
        if nxt in (_ENDOFCHAIN, _FREESECT):
            break
        block = sector(nxt)
        fat_sectors += list(struct.unpack_from(f"<{ssz // 4 - 1}I", block, 0))
        nxt = struct.unpack_from("<I", block, ssz - 4)[0]
    fat_sectors = [s for s in fat_sectors[:n_fat] if s not in (_ENDOFCHAIN, _FREESECT)]

    fat: list[int] = []
    for s in fat_sectors:
        fat += list(struct.unpack_from(f"<{ssz // 4}I", sector(s), 0))

    def read_chain(start: int, size: int | None = None) -> bytes:
        out, seen = [], set()
        while start not in (_ENDOFCHAIN, _FREESECT) and start < len(fat):
            if start in seen:
                raise DataUnavailable("cycle in the workbook sector chain")
            seen.add(start)
            out.append(sector(start))
            start = fat[start]
        data = b"".join(out)
        return data[:size] if size is not None else data

    entries = []
    directory = read_chain(dir_start)
    for off in range(0, len(directory) - 127, 128):
        e = directory[off:off + 128]
        name_len = struct.unpack_from("<H", e, 64)[0]
        entries.append({
            "name": e[:max(0, name_len - 2)].decode("utf-16-le", "replace"),
            "type": e[66],
            "start": struct.unpack_from("<I", e, 116)[0],
            "size": struct.unpack_from("<I", e, 120)[0],
        })

    root = next((e for e in entries if e["type"] == 5), None)
    mini_data = b""
    if root and root["start"] not in (_ENDOFCHAIN, _FREESECT):
        mini_data = read_chain(root["start"])
    mini_fat: list[int] = []
    if mini_start not in (_ENDOFCHAIN, _FREESECT):
        blob = read_chain(mini_start)
        mini_fat = list(struct.unpack_from(f"<{len(blob) // 4}I", blob, 0))

    def read_mini(start: int, size: int) -> bytes:
        out = []
        while start not in (_ENDOFCHAIN, _FREESECT) and start < len(mini_fat):
            out.append(mini_data[start * msz:(start + 1) * msz])
            start = mini_fat[start]
        return b"".join(out)[:size]

    streams: dict[str, bytes] = {}
    for e in entries:
        if e["type"] != 2 or not e["name"]:
            continue
        streams[e["name"]] = (read_mini(e["start"], e["size"])
                              if e["size"] < cutoff and mini_data
                              else read_chain(e["start"], e["size"]))
    return streams


def _biff_records(stream: bytes):
    """Walk the record stream, joining CONTINUE payloads onto their record."""
    pos, pending = 0, None
    while pos + 4 <= len(stream):
        rid, ln = struct.unpack_from("<HH", stream, pos)
        body = stream[pos + 4:pos + 4 + ln]
        pos += 4 + ln
        if rid == 0x003C and pending is not None:   # CONTINUE
            pending[1] += body
            continue
        if pending is not None:
            yield pending[0], bytes(pending[1])
        pending = [rid, bytearray(body)]
    if pending is not None:
        yield pending[0], bytes(pending[1])


def _rk_to_float(v: int) -> float:
    """RK squeezes a float into 32 bits, four different ways."""
    n = v >> 2
    if v & 2:
        out = float(n - (1 << 30) if n >= (1 << 29) else n)
    else:
        out = struct.unpack("<d", struct.pack("<q", (v & 0xFFFFFFFC) << 32))[0]
    return out / 100 if v & 1 else out


def _parse_sst(body: bytes) -> list[str]:
    """The shared string table, needed only to find the header row."""
    _total, unique = struct.unpack_from("<II", body, 0)
    pos, out = 8, []
    for _ in range(unique):
        if pos + 3 > len(body):
            break
        cch = struct.unpack_from("<H", body, pos)[0]
        flags = body[pos + 2]
        pos += 3
        rich = far = 0
        if flags & 0x08:
            rich = struct.unpack_from("<H", body, pos)[0]
            pos += 2
        if flags & 0x04:
            far = struct.unpack_from("<I", body, pos)[0]
            pos += 4
        if flags & 0x01:
            out.append(body[pos:pos + cch * 2].decode("utf-16-le", "replace"))
            pos += cch * 2
        else:
            out.append(body[pos:pos + cch].decode("latin-1", "replace"))
            pos += cch
        pos += rich * 4 + far
    return out


def read_xls_sheet(raw: bytes, wanted: str) -> dict[tuple[int, int], float | str]:
    """One worksheet of a legacy .xls, as {(row, column): value}.

    Formula cells are read from their cached result, which is what Excel wrote
    the last time it recalculated. Nothing in this project relies on one: the
    Shiller columns used here are all typed in rather than computed.
    """
    streams = _ole_streams(raw)
    book = streams.get("Workbook") or streams.get("Book")
    if book is None:
        raise DataUnavailable(
            f"no workbook stream in the file; found {sorted(streams)}"
        )

    sheets: list[tuple[str, int]] = []
    sst: list[str] = []
    for rid, body in _biff_records(book):
        if rid == 0x0085:                                    # BOUNDSHEET
            offset = struct.unpack_from("<I", body, 0)[0]
            cch, flags = body[6], body[7]
            name = (body[8:8 + cch * 2].decode("utf-16-le", "replace")
                    if flags & 1 else body[8:8 + cch].decode("latin-1", "replace"))
            sheets.append((name, offset))
        elif rid == 0x00FC:                                  # SST
            sst = _parse_sst(body)
        elif rid == 0x000A and sheets:                       # EOF of the globals
            break

    start = next((o for n, o in sheets if n.strip().lower() == wanted.lower()), None)
    if start is None:
        raise DataUnavailable(
            f'no sheet named "{wanted}"; found {[n for n, _ in sheets]}'
        )

    cells: dict[tuple[int, int], float | str] = {}
    for rid, body in _biff_records(book[start:]):
        if rid == 0x000A:                                    # EOF of this sheet
            break
        if rid == 0x0203 and len(body) >= 14:                # NUMBER
            r, c = struct.unpack_from("<HH", body, 0)
            cells[(r, c)] = struct.unpack_from("<d", body, 6)[0]
        elif rid == 0x027E and len(body) >= 10:              # RK
            r, c = struct.unpack_from("<HH", body, 0)
            cells[(r, c)] = _rk_to_float(struct.unpack_from("<I", body, 6)[0])
        elif rid == 0x00BD and len(body) >= 10:              # MULRK
            r, c0 = struct.unpack_from("<HH", body, 0)
            for i in range((len(body) - 6) // 6):
                v = struct.unpack_from("<I", body, 4 + i * 6 + 2)[0]
                cells[(r, c0 + i)] = _rk_to_float(v)
        elif rid == 0x00FD and len(body) >= 10:              # LABELSST
            r, c = struct.unpack_from("<HH", body, 0)
            idx = struct.unpack_from("<I", body, 6)[0]
            if idx < len(sst):
                cells[(r, c)] = sst[idx]
        elif rid == 0x0006 and len(body) >= 20:              # FORMULA
            r, c = struct.unpack_from("<HH", body, 0)
            if struct.unpack_from("<H", body, 12)[0] != 0xFFFF:
                cells[(r, c)] = struct.unpack_from("<d", body, 6)[0]
    return cells


def parse_shiller_xls(data: bytes) -> "ShillerHistory":
    """Shiller's own workbook, from raw columns rather than formula results.

    Only Date, P, D, E and CPI are read. Everything real is deflated here, the
    same way his own sheet does it, which means the result never depends on a
    cached formula value or on a column he might rename. Where a column changes
    position the header row still finds it.
    """
    cells = read_xls_sheet(data, "Data")

    def number(row: int, col: int) -> float | None:
        v = cells.get((row, col))
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", "").strip())
            except ValueError:
                return None
        return None

    # The header is a stack of stanzas; the last line of it carries the short
    # names. Find the row holding both "Date" and "CPI".
    wanted = {"date": None, "p": None, "d": None, "e": None, "cpi": None}
    header_row = None
    for row in range(0, 30):
        labels = {}
        for (r, c), v in cells.items():
            if r == row and isinstance(v, str):
                labels[v.strip().lower()] = c
        if "date" in labels and "cpi" in labels:
            header_row = row
            for key in wanted:
                wanted[key] = labels.get(key)
            break
    if header_row is None or any(v is None for v in wanted.values()):
        raise DataUnavailable(
            f"could not find Date/P/D/E/CPI in the workbook header; got {wanted}"
        )

    dates: list[str] = []
    prices: list[float] = []
    dividends: list[float] = []
    earnings: list[float] = []
    cpis: list[float] = []
    for row in sorted({r for r, _ in cells if r > header_row}):
        stamp = number(row, wanted["date"])
        price = number(row, wanted["p"])
        dividend = number(row, wanted["d"])
        earning = number(row, wanted["e"])
        cpi = number(row, wanted["cpi"])
        if None in (stamp, price, dividend, earning, cpi):
            continue
        if price <= 0 or dividend <= 0 or cpi <= 0:
            continue
        year = int(stamp)
        month = int(round((stamp - year) * 100))
        if not 1 <= month <= 12:
            continue
        dates.append(f"{year:04d}-{month:02d}-01")
        prices.append(price)
        dividends.append(dividend)
        earnings.append(earning)
        cpis.append(cpi)

    if len(dates) < 600:
        raise DataUnavailable(
            f"only {len(dates)} usable months in the workbook, expected decades"
        )

    # Deflate to the latest month's dollars, which is Shiller's own convention.
    base = cpis[-1]
    real_prices = tuple(p * base / c for p, c in zip(prices, cpis))
    real_dividends = tuple(d * base / c for d, c in zip(dividends, cpis))
    real_earnings = tuple(e * base / c for e, c in zip(earnings, cpis))

    # The cyclically adjusted ratio needs ten years of earnings behind it, so
    # the first ten years cannot carry one. Those months are dropped rather
    # than zero-filled, which is what the CSV parser does: a fallback source
    # has to hand downstream code the same shape as the one it replaces, and
    # a zero here divides by zero in the valuation regression.
    cape: list[float] = []
    for i in range(119, len(real_prices)):
        mean = sum(real_earnings[i - 119:i + 1]) / 120.0
        if mean <= 0:
            raise DataUnavailable(
                f"non-positive average earnings ending {dates[i]}"
            )
        cape.append(real_prices[i] / mean)

    return ShillerHistory(
        tuple(dates[119:]),
        real_prices[119:],
        real_dividends[119:],
        real_earnings[119:],
        tuple(cape),
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
