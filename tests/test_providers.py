"""Parsing the free providers' responses.

Offline. Every fixture is built here, so a test run never depends on a
provider being up.
"""

from __future__ import annotations

from datetime import date

import pytest

from your_equity_share.providers import (
    DataUnavailable,
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
