"""Parsing the free providers' responses.

Offline. Every fixture is built here, including a minimal xlsx assembled in
memory, so a test run never depends on a provider being up.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest

from your_equity_share.providers import (
    DataUnavailable,
    parse_damodaran_erp,
    parse_fred_csv,
    parse_price_json,
)


# --- Yahoo chart ------------------------------------------------------------


def _chart(close=None, adjclose=None, stamps=None, error=None):
    stamps = stamps if stamps is not None else [1767312000, 1767571200, 1767657600]
    indicators = {}
    if close is not None:
        indicators["quote"] = [{"close": close}]
    if adjclose is not None:
        indicators["adjclose"] = [{"adjclose": adjclose}]
    if error is not None:
        return json.dumps({"chart": {"error": error, "result": None}})
    return json.dumps(
        {
            "chart": {
                "error": None,
                "result": [{"timestamp": stamps, "indicators": indicators}],
            }
        }
    )


def test_prefers_the_adjusted_close() -> None:
    """Adjusted for dividends as well as splits, so ratios are total returns."""
    text = _chart(close=[100.0, 101.0, 102.0], adjclose=[90.0, 91.0, 92.0])
    series = parse_price_json(text, "SPY")
    assert series.adjusted is True
    assert list(series.closes.values()) == [90.0, 91.0, 92.0]


def test_falls_back_to_the_unadjusted_close_and_says_so() -> None:
    """Some instruments return no adjclose. Usable, but the caller must know."""
    series = parse_price_json(_chart(close=[100.0, 101.0, 102.0]), "X")
    assert series.adjusted is False
    assert list(series.closes.values()) == [100.0, 101.0, 102.0]


def test_dates_come_back_as_iso_strings() -> None:
    series = parse_price_json(_chart(adjclose=[1.0, 2.0, 3.0]), "SPY")
    assert sorted(series.closes) == ["2026-01-02", "2026-01-05", "2026-01-06"]


def test_null_closes_are_dropped_not_zeroed() -> None:
    """A shut exchange. Treating the gap as zero would invent a total loss."""
    series = parse_price_json(_chart(adjclose=[100.0, None, 102.0]), "SPY")
    assert len(series.closes) == 2
    assert 0.0 not in series.closes.values()


def test_rejects_a_bot_check_page() -> None:
    with pytest.raises(DataUnavailable, match="not JSON"):
        parse_price_json("<!DOCTYPE html><html><head>", "SPY")


def test_surfaces_a_provider_error() -> None:
    with pytest.raises(DataUnavailable, match="provider returned an error"):
        parse_price_json(_chart(error={"code": "Not Found"}), "NOSUCH")


def test_rejects_mismatched_lengths() -> None:
    with pytest.raises(DataUnavailable, match="timestamps but"):
        parse_price_json(_chart(adjclose=[1.0], stamps=[1, 2, 3]), "SPY")


def test_rejects_a_response_with_no_price_series_at_all() -> None:
    with pytest.raises(DataUnavailable, match="neither adjclose nor close"):
        parse_price_json(_chart(), "SPY")


def test_rejects_an_all_null_series() -> None:
    with pytest.raises(DataUnavailable, match="no usable observations"):
        parse_price_json(_chart(adjclose=[None, None, None]), "SPY")


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
