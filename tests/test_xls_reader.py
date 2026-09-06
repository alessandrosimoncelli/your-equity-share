"""The legacy .xls reader, tested against workbooks built here.

Shiller publishes his series as a 1997-era binary and nothing else, so reading
that format is the only way to reach the authoritative source. A 1.6 MB
workbook does not belong in a repository and would not be a test anyway, so
these build minimal ones byte by byte and read them back.

Both formats are frozen. OLE2 and BIFF8 have not changed since 2007 and will
not, which is what makes a hand-written reader a reasonable thing to maintain
and these fixtures a reasonable thing to trust.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from your_equity_share.providers import (  # noqa: E402
    DataUnavailable,
    _biff_records,
    _parse_sst,
    _rk_to_float,
    parse_shiller_xls,
    read_xls_sheet,
)

ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD


# --- building a workbook -----------------------------------------------------


def record(rid: int, payload: bytes) -> bytes:
    return struct.pack("<HH", rid, len(payload)) + payload


def sst(strings: list[str]) -> bytes:
    body = struct.pack("<II", len(strings), len(strings))
    for s in strings:
        body += struct.pack("<H", len(s)) + b"\x00" + s.encode("latin-1")
    return record(0x00FC, body)


def number(row: int, col: int, value: float) -> bytes:
    return record(0x0203, struct.pack("<HHH", row, col, 0) + struct.pack("<d", value))


def labelsst(row: int, col: int, index: int) -> bytes:
    return record(0x00FD, struct.pack("<HHHI", row, col, 0, index))


def workbook_stream(sheet_name: str, cells: bytes, strings: list[str]) -> bytes:
    """Globals substream naming one sheet, then that sheet's own substream.

    BOUNDSHEET carries the absolute offset of the sheet's BOF within the
    stream, so the length of the globals part has to be known before it is
    written. Every record here is fixed length given its payload, so it is
    computed rather than patched afterwards.
    """
    name = sheet_name.encode("latin-1")
    bof = record(0x0809, struct.pack("<HH", 0x0600, 0x0005))
    table = sst(strings)
    eof = record(0x000A, b"")
    # BOUNDSHEET payload: position (4), visibility and type (2), name length
    # (1), a flag saying whether the name is UTF-16 (1), then the name.
    boundsheet_len = 4 + 8 + len(name)
    offset = len(bof) + boundsheet_len + len(table) + len(eof)
    boundsheet = record(
        0x0085, struct.pack("<IBBBB", offset, 0, 0, len(name), 0) + name
    )
    assert len(boundsheet) == boundsheet_len
    sheet = record(0x0809, struct.pack("<HH", 0x0600, 0x0010)) + cells + eof
    return bof + boundsheet + table + eof + sheet


def ole_container(stream: bytes, stream_name: str = "Workbook") -> bytes:
    """A minimal OLE2 file holding one stream.

    The allocation table is itself stored in sectors, and one sector holds 128
    entries, so anything past about 64 KB needs more than one of them. An
    earlier version of this builder wrote exactly one and silently produced a
    corrupt file above that size, which looked like a bug in the reader.
    """
    ssz = 512
    per_sector = ssz // 4
    payload = stream + b"\x00" * (-len(stream) % ssz)
    n_data = len(payload) // ssz

    # Sectors: [FAT xN][directory][stream...]. The count of FAT sectors depends
    # on the total, which depends on it, so settle it by iteration.
    n_fat = 1
    while n_fat * per_sector < n_fat + 1 + n_data:
        n_fat += 1
    dir_sector = n_fat
    first_data = n_fat + 1

    fat = [FATSECT] * n_fat + [ENDOFCHAIN]
    fat += [first_data + i + 1 for i in range(n_data - 1)] + [ENDOFCHAIN]
    fat += [FREESECT] * (n_fat * per_sector - len(fat))
    fat_bytes = b"".join(struct.pack("<I", v) for v in fat)

    def entry(name: str, kind: int, start: int, size: int) -> bytes:
        raw = name.encode("utf-16-le") + b"\x00\x00"
        e = raw.ljust(64, b"\x00")
        e += struct.pack("<H", len(raw))
        e += bytes([kind, 1])
        e += struct.pack("<III", FREESECT, FREESECT, FREESECT)
        e += b"\x00" * 36
        e += struct.pack("<II", start, size)
        return e.ljust(128, b"\x00")

    directory = entry("Root Entry", 5, ENDOFCHAIN, 0)
    directory += entry(stream_name, 2, first_data, len(stream))
    directory = directory.ljust(ssz, b"\x00")

    header = bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 16
    header += struct.pack("<HHHH", 0x003E, 3, 0xFFFE, 9)
    header += struct.pack("<H", 6) + b"\x00" * 6
    header += struct.pack("<I", 0)            # 40 directory sector count
    header += struct.pack("<I", n_fat)        # 44 FAT sector count
    header += struct.pack("<I", dir_sector)   # 48 first directory sector
    header += struct.pack("<I", 0)            # 52 transaction signature
    header += struct.pack("<I", 4096)         # 56 mini stream cutoff
    header += struct.pack("<I", ENDOFCHAIN)   # 60 first mini FAT sector
    header += struct.pack("<I", 0)            # 64 mini FAT sector count
    header += struct.pack("<I", ENDOFCHAIN)   # 68 first DIFAT sector
    header += struct.pack("<I", 0)            # 72 DIFAT sector count
    difat = list(range(n_fat)) + [FREESECT] * (109 - n_fat)
    header += b"".join(struct.pack("<I", v) for v in difat)
    header = header.ljust(512, b"\x00")

    return header + fat_bytes + directory + payload


# --- the pieces ---------------------------------------------------------------


def test_rk_decodes_all_four_encodings() -> None:
    """RK packs a float into 32 bits: integer or truncated double, each
    optionally divided by a hundred."""
    assert _rk_to_float((1234 << 2) | 2) == 1234.0
    assert _rk_to_float((1234 << 2) | 3) == pytest.approx(12.34)
    upper = struct.unpack("<q", struct.pack("<d", 3.5))[0] >> 32
    assert _rk_to_float(upper & 0xFFFFFFFC) == pytest.approx(3.5)
    assert _rk_to_float(((-5 + (1 << 30)) << 2) | 2) == -5.0


def test_records_join_their_continuations() -> None:
    """A payload longer than 8,224 bytes is split across CONTINUE records, and
    a reader that treats those as separate records loses the tail."""
    stream = record(0x00FC, b"A" * 10) + record(0x003C, b"B" * 6) + record(0x000A, b"")
    got = list(_biff_records(stream))
    assert got[0] == (0x00FC, b"A" * 10 + b"B" * 6)
    assert got[1][0] == 0x000A


def test_shared_strings_read_back() -> None:
    body = sst(["Date", "CPI", "E"])[4:]
    assert _parse_sst(body) == ["Date", "CPI", "E"]


# --- a whole workbook ---------------------------------------------------------


def test_reads_cells_from_a_built_workbook() -> None:
    cells = number(0, 0, 1871.01) + number(0, 1, 4.44) + labelsst(1, 0, 0)
    raw = ole_container(workbook_stream("Data", cells, ["Date"]))
    got = read_xls_sheet(raw, "Data")
    assert got[(0, 0)] == pytest.approx(1871.01)
    assert got[(0, 1)] == pytest.approx(4.44)
    assert got[(1, 0)] == "Date"


def test_a_missing_sheet_is_named_in_the_error() -> None:
    raw = ole_container(workbook_stream("Data", number(0, 0, 1.0), []))
    with pytest.raises(DataUnavailable, match="Quarterly"):
        read_xls_sheet(raw, "Quarterly")


def test_something_that_is_not_a_workbook_is_refused() -> None:
    with pytest.raises(DataUnavailable, match="legacy Excel"):
        read_xls_sheet(b"Date,Price\n1871-01,4.44\n", "Data")


# --- the Shiller reader on a workbook shaped like his -------------------------


def shiller_like(months: int, growth: float = 0.02, inflation: float = 0.03) -> bytes:
    """A workbook with his column names and enough months to be usable."""
    labels = ["Date", "P", "D", "E", "CPI"]
    cells = b"".join(labelsst(7, c, i) for i, c in enumerate(range(5)))
    price = earnings = 100.0
    dividend, cpi = 3.0, 100.0
    for i in range(months):
        year, month = 1900 + i // 12, i % 12 + 1
        row = 8 + i
        cells += number(row, 0, year + month / 100.0)
        cells += number(row, 1, price) + number(row, 2, dividend)
        cells += number(row, 3, earnings) + number(row, 4, cpi)
        step = (1 + growth) ** (1 / 12) * (1 + inflation) ** (1 / 12)
        price *= step
        earnings *= step
        dividend *= step
        cpi *= (1 + inflation) ** (1 / 12)
    return ole_container(workbook_stream("Data", cells, labels))


def test_shiller_reader_deflates_and_finds_its_columns() -> None:
    history = parse_shiller_xls(shiller_like(1500))
    assert len(history) == 1500 - 119
    assert history.dates[0] == "1909-12-01"
    # Real earnings must grow at the real rate, not the nominal one.
    assert history.real_earnings_trend_growth(100) == pytest.approx(0.02, abs=2e-4)


def test_dividend_yield_is_the_ratio_in_the_last_row() -> None:
    """Both terms out of one row, so the deflator cancels and lag largely does too."""
    history = parse_shiller_xls(shiller_like(1500))
    assert history.dividend_yield == pytest.approx(0.03, abs=1e-12)
    assert history.dividend_yield == pytest.approx(
        history.real_dividends[-1] / history.real_prices[-1]
    )


def test_last_date_survives_the_round_trip_to_a_date() -> None:
    history = parse_shiller_xls(shiller_like(1500))
    assert history.last_date_as_date().isoformat() == history.last_date


def test_shiller_reader_needs_a_recognisable_header() -> None:
    cells = number(8, 0, 1871.01) + number(8, 1, 4.44)
    raw = ole_container(workbook_stream("Data", cells, []))
    with pytest.raises(DataUnavailable, match="header"):
        parse_shiller_xls(raw)


def test_shiller_reader_refuses_a_short_history() -> None:
    with pytest.raises(DataUnavailable, match="decades"):
        parse_shiller_xls(shiller_like(200))


def test_dates_are_contiguous_months() -> None:
    """real_earnings_trend_growth slices by count, so a gap would make the
    window span more calendar time than it divides by."""
    history = parse_shiller_xls(shiller_like(800))
    for earlier, later in zip(history.dates, history.dates[1:]):
        a = int(earlier[:4]) * 12 + int(earlier[5:7])
        b = int(later[:4]) * 12 + int(later[5:7])
        assert b - a == 1
