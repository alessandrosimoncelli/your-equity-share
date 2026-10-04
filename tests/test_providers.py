"""Parsing the free providers' responses.

Offline. Every fixture is built here, including a minimal xlsx assembled in
memory, so a test run never depends on a provider being up.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from your_equity_share.providers import (
    DataUnavailable,
    parse_damodaran_components,
    parse_damodaran_erp,
    parse_fred_csv,
    parse_treasury_real_yield_csv,
)


# --- FRED -------------------------------------------------------------------


FRED = "observation_date,DFII30\n2026-08-26,2.95\n2026-08-27,.\n2026-08-28,2.98\n"


def test_fred_takes_the_latest_observation_and_converts_to_a_fraction() -> None:
    day, value = parse_fred_csv(FRED, "DFII30")
    assert day == date(2026, 8, 28)
    assert value == pytest.approx(0.0298)


def test_fred_skips_the_missing_day_marker() -> None:
    day, _ = parse_fred_csv(FRED + "2026-08-31,.\n", "DFII30")
    assert day == date(2026, 8, 28)


def test_fred_rejects_an_empty_series() -> None:
    with pytest.raises(DataUnavailable, match="no observations"):
        parse_fred_csv("observation_date,DFII30\n2026-08-26,.\n", "DFII30")


# --- Treasury real yield curve ---------------------------------------------

# The Treasury's own layout: newest day first, month/day/year, quoted headers.
TREASURY = ('Date,"5 YR","7 YR","10 YR","20 YR","30 YR"\n'
            "09/29/2026,2.72,2.80,2.91,3.15,3.29\n"
            "09/28/2026,2.73,2.80,2.90,3.14,3.28\n"
            "09/25/2026,2.64,2.73,2.83,3.08,3.22\n")


def test_treasury_takes_the_newest_day_whatever_the_row_order() -> None:
    """The file lists the newest day first; the parser must not rely on it."""
    day, value = parse_treasury_real_yield_csv(TREASURY)
    assert day == date(2026, 9, 29)
    assert value == pytest.approx(0.0329)
    rows = TREASURY.splitlines()
    reversed_file = "\n".join([rows[0], *reversed(rows[1:])]) + "\n"
    assert parse_treasury_real_yield_csv(reversed_file)[0] == date(2026, 9, 29)


def test_treasury_reads_the_tenor_it_is_asked_for() -> None:
    day, value = parse_treasury_real_yield_csv(TREASURY, "10 YR")
    assert day == date(2026, 9, 29)
    assert value == pytest.approx(0.0291)


def test_treasury_skips_a_day_with_no_thirty_year_value() -> None:
    gap = TREASURY.replace("09/29/2026,2.72,2.80,2.91,3.15,3.29",
                           "09/29/2026,2.72,2.80,2.91,3.15,")
    assert parse_treasury_real_yield_csv(gap)[0] == date(2026, 9, 28)


def test_an_empty_year_is_none_so_the_caller_can_read_the_last_one() -> None:
    """On the first business day of a year its file has a header and no rows."""
    assert parse_treasury_real_yield_csv(TREASURY.splitlines()[0] + "\n") is None


def test_a_file_without_the_column_is_a_changed_format_not_an_empty_year() -> None:
    with pytest.raises(DataUnavailable, match="30 YR"):
        parse_treasury_real_yield_csv('Date,"5 YR"\n09/29/2026,2.72\n')


# --- Damodaran workbook -----------------------------------------------------


def _workbook(serial: int, premium: float, date1904: bool = True,
              sheet_name: str = "Last 12 months data") -> bytes:
    """A minimal xlsx with the shape the real one has."""
    flag = ' date1904="1"' if date1904 else ""
    workbook = (
        '<?xml version="1.0"?><workbook '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<workbookPr{flag}/><sheets>"
        '<sheet name="Historical ERP" sheetId="1" r:id="rId1"/>'
        f'<sheet name="{sheet_name}" sheetId="2" r:id="rId3"/>'
        '<sheet name="ERP in last 12 months" sheetId="3" r:id="rId2"/>'
        "</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0"?><Relationships>'
        '<Relationship Id="rId1" Type="x/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="x/chartsheet" Target="chartsheets/sheet1.xml"/>'
        '<Relationship Id="rId3" Type="x/worksheet" Target="worksheets/sheet2.xml"/>'
        "</Relationships>"
    )
    rows = (
        f'<row r="13"><c r="A13"><v>{serial - 31}</v></c>'
        f'<c r="D13"><v>0.0399</v></c></row>'
        f'<row r="14"><c r="A14" s="5"><v>{serial}</v></c>'
        f'<c r="B14"><v>7686</v></c><c r="C14"><v>0.0475</v></c>'
        f'<c r="D14" s="3"><v>{premium}</v></c></row>'
    )
    sheet2 = f'<?xml version="1.0"?><worksheet><sheetData>{rows}</sheetData></worksheet>'

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
        zf.writestr("xl/worksheets/sheet2.xml", sheet2)
        zf.writestr("xl/chartsheets/sheet1.xml", "<chartsheet/>")
    return buffer.getvalue()


def test_reads_the_latest_premium() -> None:
    day, premium = parse_damodaran_erp(_workbook(44804, 0.0409))
    assert premium == pytest.approx(0.0409)
    assert day == date(2026, 9, 1)


def test_uses_the_1904_epoch_when_the_flag_is_set() -> None:
    """The trap. Assuming the usual epoch dates every row four years early."""
    with_1904 = parse_damodaran_erp(_workbook(44804, 0.04, date1904=True))[0]
    with_1900 = parse_damodaran_erp(_workbook(44804, 0.04, date1904=False))[0]
    assert with_1904.year - with_1900.year == 4
    assert with_1904 == date(2026, 9, 1)
    assert with_1900 == date(2022, 8, 31)


def test_takes_the_data_sheet_not_the_chart_of_the_same_subject() -> None:
    """The tab called "ERP in last 12 months" is a chart, not a grid."""
    data = _workbook(44804, 0.0409)
    assert parse_damodaran_erp(data)[1] == pytest.approx(0.0409)


def test_reports_a_missing_data_sheet_clearly() -> None:
    with pytest.raises(DataUnavailable, match="no sheet named"):
        parse_damodaran_erp(_workbook(44804, 0.04, sheet_name="Renamed Tab"))


def test_rejects_an_implausible_premium() -> None:
    """A layout change would otherwise be adopted silently."""
    with pytest.raises(DataUnavailable, match="outside any plausible range"):
        parse_damodaran_erp(_workbook(44804, 7686.0))
    with pytest.raises(DataUnavailable, match="outside any plausible range"):
        parse_damodaran_erp(_workbook(44804, -0.02))


def test_rejects_something_that_is_not_a_workbook() -> None:
    with pytest.raises(DataUnavailable, match="not a readable workbook"):
        parse_damodaran_erp(b"<html>404</html>")


def test_takes_the_most_recent_row_regardless_of_order() -> None:
    day, premium = parse_damodaran_erp(_workbook(44804, 0.0409))
    assert premium == pytest.approx(0.0409)  # row 14, not row 13's 0.0399


# --- the payout components, which had no test at all ------------------------
#
# Found by tools/mutate.py: parse_damodaran_components was never called by the
# suite, so every constant and every operator in it was free to be wrong. The
# mutant that exposed it turned `epoch + timedelta(days=serial)` into
# `epoch - timedelta(...)`, which dates the observation 1781 instead of 2026
# and would let the staleness check pass on data two centuries stale.

def _components(serial: int, index: float, trailing: float, smoothed: float,
                date1904: bool = True) -> bytes:
    """A workbook with the Historical ERP sheet actually populated.

    The sibling fixture leaves that sheet empty because the premium comes from
    a different tab. Columns are the ones the parser reads: A the date serial,
    B the index level, E the ten-year average cash returned, F the trailing
    twelve months of it.
    """
    flag = ' date1904="1"' if date1904 else ""
    workbook = (
        '<?xml version="1.0"?><workbook '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<workbookPr{flag}/><sheets>"
        '<sheet name="Historical ERP" sheetId="1" r:id="rId1"/>'
        "</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0"?><Relationships>'
        '<Relationship Id="rId1" Type="x/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    # An older row first, and deliberately out of order, so the parser has to
    # pick by serial rather than by position.
    rows = (
        f'<row r="9"><c r="A9"><v>{serial}</v></c><c r="B9"><v>{index}</v></c>'
        f'<c r="E9"><v>{smoothed * index}</v></c>'
        f'<c r="F9"><v>{trailing * index}</v></c></row>'
        f'<row r="10"><c r="A10"><v>{serial - 400}</v></c>'
        f'<c r="B10"><v>{index / 2}</v></c>'
        f'<c r="E10"><v>{index / 2 * 0.03}</v></c>'
        f'<c r="F10"><v>{index / 2 * 0.04}</v></c></row>'
    )
    sheet = f'<?xml version="1.0"?><worksheet><sheetData>{rows}</sheetData></worksheet>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


def test_reads_the_payout_yields_from_the_latest_row() -> None:
    """F over B and E over B, taken from the row with the highest serial."""
    day, trailing, smoothed = parse_damodaran_components(
        _components(44804, 7686.0, 0.0263, 0.0241))
    assert trailing == pytest.approx(0.0263)
    assert smoothed == pytest.approx(0.0241)
    assert day == date(2026, 9, 1)


def test_the_payout_date_is_not_merely_a_number() -> None:
    """The date has to move the right way and land in the right century.

    This is the assertion the suite was missing. Adding the serial to the epoch
    gives 2026; subtracting it gives 1781, and nothing else in the file would
    have noticed the difference.
    """
    day = parse_damodaran_components(_components(44804, 7686.0, 0.026, 0.024))[0]
    assert day.year == 2026
    assert day > date(2000, 1, 1)


def test_the_payout_epoch_flag_is_read_rather_than_assumed() -> None:
    """The two Excel epochs are four years apart and the workbook says which."""
    with_1904 = parse_damodaran_components(
        _components(44804, 7686.0, 0.026, 0.024, date1904=True))[0]
    with_1900 = parse_damodaran_components(
        _components(44804, 7686.0, 0.026, 0.024, date1904=False))[0]
    assert with_1904 == date(2026, 9, 1)
    assert with_1900 == date(2022, 8, 31)


def test_the_later_row_wins_even_when_it_is_not_last() -> None:
    """The fixture puts the newer row first on purpose."""
    day = parse_damodaran_components(_components(44804, 7686.0, 0.026, 0.024))[0]
    assert day == date(2026, 9, 1)


def test_rejects_payout_yields_that_cannot_be_right() -> None:
    """A layout change shows up as an absurd yield, not as a plausible one."""
    with pytest.raises(DataUnavailable):
        parse_damodaran_components(_components(44804, 7686.0, 0.45, 0.02))
    with pytest.raises(DataUnavailable):
        parse_damodaran_components(_components(44804, 7686.0, 0.02, -0.01))


def test_rejects_a_workbook_with_no_payout_rows() -> None:
    """Rows without the four columns the parser needs are not payout rows.

    Built rather than edited: patching the bytes of a finished zip corrupts its
    checksum, and the test then passes for the wrong reason.
    """
    workbook = (
        '<?xml version="1.0"?><workbook '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<workbookPr date1904="1"/><sheets>'
        '<sheet name="Historical ERP" sheetId="1" r:id="rId1"/>'
        "</sheets></workbook>"
    )
    rels = ('<?xml version="1.0"?><Relationships>'
            '<Relationship Id="rId1" Type="x/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>')
    sheet = ('<?xml version="1.0"?><worksheet><sheetData>'
             '<row r="9"><c r="C9"><v>1</v></c><c r="D9"><v>2</v></c></row>'
             "</sheetData></worksheet>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    with pytest.raises(DataUnavailable):
        parse_damodaran_components(buffer.getvalue())
