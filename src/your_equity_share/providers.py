"""Parsing the responses of the free data providers.

Kept apart from the fetching so that every parser can be tested against a
fixture with no network. `update.py` does the fetching and calls these.

The sources, all free and none needing a key or an account:

    Treasury        the 30-year real yield, from its daily real yield curve
    FRED            the same yield as DFII30, when the Treasury fails
    Shiller         the long monthly history the expected return is built from
"""

from __future__ import annotations

import csv
import io
import math
import struct
from dataclasses import dataclass
from datetime import date, datetime

__all__ = [
    "DataUnavailable",
    "ShillerHistory",
    "parse_fred_csv",
    "parse_treasury_real_yield_csv",
    "read_xls_sheet",
    "parse_shiller_xls",
]


class DataUnavailable(Exception):
    """A provider could not be reached or returned something unusable."""


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


def parse_treasury_real_yield_csv(
    text: str, column: str = "30 YR"
) -> tuple[date, float] | None:
    """Return the latest value of one tenor of the Treasury's real yield curve.

    The file is the Treasury's Daily Treasury Par Real Yield Curve Rates for
    one calendar year: newest day first, dates written month/day/year, yields
    in percent. FRED's DFII30 is this curve's 30-year point, republished
    through the Federal Reserve's H.15 release.

    Returns None when the year has no observation yet, as on its first
    business day, so the caller can read the year before. A file without the
    column is a changed format rather than an empty year, and raises.
    """
    reader = csv.reader(io.StringIO(text))
    header = [cell.strip() for cell in next(reader, [])]
    if "Date" not in header or column not in header:
        raise DataUnavailable(
            f"Treasury real yield curve: no {column!r} column in the response"
        )
    at, col = header.index("Date"), header.index(column)
    latest: tuple[date, float] | None = None
    for row in reader:
        if len(row) <= max(at, col) or not row[col].strip():
            continue
        try:
            day = datetime.strptime(row[at].strip(), "%m/%d/%Y").date()
            value = float(row[col]) / 100.0
        except ValueError:
            continue
        if latest is None or day > latest[0]:
            latest = (day, value)
    return latest


@dataclass(frozen=True)
class ShillerHistory:
    """Robert Shiller's monthly S&P COMPOSITE series, cleaned.

    Composite, not the S&P 500, and the difference is worth stating because
    calling it the S&P 500 is the usual shorthand and it is wrong for most of
    the history. Shiller splices three indices:

        1871 to 1926   Cowles and Associates, Common Stock Indexes, 2nd ed.
        1926 to 1957   Standard and Poor 90
        1957 onward    Standard and Poor 500

    THE MONTHLY EARNINGS ARE INTERPOLATED. Since 1926 they are computed from
    S&P four-quarter totals and interpolated linearly to months; before 1926
    they are Cowles figures interpolated from annual data. So a hundred years
    of monthly earnings is about four hundred quarterly observations wearing a
    monthly dress. That does not bias a trend through them, but any standard
    error computed from the monthly count would overstate the precision by
    roughly the square root of three, which is why this project reports the
    estimator's sensitivity to its window rather than a standard error.

    One convenient accident: the hundred-year window the growth trend uses
    currently runs from July 1926, so it begins at the Cowles boundary and
    rests on Standard and Poor data almost entirely. The reconstructed era is
    in the file but not in the estimate.

    DOES THE 1957 SPLICE MATTER. It was worth asking and the answer is no,
    measured rather than argued:

        1926-07 to 2026-06   S&P 90 then 500, the window in use   2.2860%
        1957-03 to 2026-06   S&P 500 only                         2.2741%
        1926-07 to 1957-02   S&P 90 only                          2.3005%
        1880-12 to 1926-06   Cowles only                          1.1882%

    The two Standard and Poor eras grow at the same rate to within three
    hundredths of a point and there is no level break across the join. Refit
    the whole estimator on S&P 500 data alone and it gives 2.2835% against
    2.2860%, a difference of THREE THOUSANDTHS of a point, bought at the price
    of thirty-one years of sample.

    That price is not nominal. The trend is stable from about seventy years
    upward and comes apart below sixty: 2.28% at 69 years, 2.48% at 60, 3.11%
    at 50 and 3.98% at 40, as the window shortens onto the recent earnings
    boom. Across 90 to 110 years it moves 0.133 points; across 60 to 80 it
    moves 0.265. So the long window is measurably the better estimator and the
    splice it spans is measurably harmless.

    The Cowles era is the one that genuinely differs, at 1.19%, which is why
    it being outside the window is worth stating rather than assuming.

    Only months carrying a real price, a real dividend and a CAPE are kept, so
    the three lists are aligned and every entry is usable. That is also why the
    cleaned series starts a decade after the raw one: CAPE needs ten years of
    prior earnings behind it. Recent months often lack fundamentals even when a
    price exists, and those are dropped rather than carried as zeros.
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
        whatever the cycle was doing in each of them. Table 9 of the American
        methodology measures both on the current file: the trend moves far less
        with the window, and the few months the published series runs behind
        move it by about a basis point and a half.

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


# --- reading a legacy .xls, with the standard library only -------------------
#
# Shiller publishes his series as a 1997-era binary .xls and nothing else. It
# is authoritative and maintained; the CSV mirror this project once used
# stopped carrying CPI in September 2023, and with it every deflated column.
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
    # than zero-filled, because a zero here would divide by zero wherever the
    # ratio is inverted.
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


