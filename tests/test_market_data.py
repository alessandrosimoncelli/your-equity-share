"""Tests for the config loader and the refresh parsers.

Everything here runs offline. The refresh tool's network calls are isolated in
`_get`, and the parsing and validation either side of them are tested against
fixtures held in this file. A test run must never depend on a data provider.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

TMP = tempfile.mkdtemp()
FIXTURE = Path(__file__).parent / "fixture_market_data.toml"
MINIMAL = """
[market]
expected_stock_real_return = 0.05
real_risk_free = 0.025
stock_volatility = 0.185
as_of = 2026-06-02
"""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from your_equity_share.market_data import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    load_market_data,
)
from your_equity_share.providers import (  # noqa: E402
    DataUnavailable,
    parse_fred_csv,
)


# --- provider response parsing ---------------------------------------------


FRED_CSV = """observation_date,DGS3MO
2026-08-26,4.28
2026-08-27,.
2026-08-28,4.31
"""


def test_parse_fred_csv_takes_the_latest_observation() -> None:
    day, value = parse_fred_csv(FRED_CSV, "DGS3MO")
    assert day == date(2026, 8, 28)
    assert value == pytest.approx(0.0431)


def test_parse_fred_csv_skips_missing_markers() -> None:
    text = FRED_CSV + "2026-08-31,.\n"
    day, _ = parse_fred_csv(text, "DGS3MO")
    assert day == date(2026, 8, 28)


def test_parse_fred_csv_rejects_an_empty_series() -> None:
    with pytest.raises(DataUnavailable, match="no observations"):
        parse_fred_csv("observation_date,DGS3MO\n2026-08-26,.\n", "DGS3MO")


# --- where the 30-year real yield comes from --------------------------------
#
# The Treasury first, because FRED does not answer GitHub's servers, and FRED
# second, because it does answer most other places. Nothing here touches the
# network: _get is replaced by a stand-in that serves each URL from a table.

TREASURY_2026 = ('Date,"5 YR","7 YR","10 YR","20 YR","30 YR"\n'
                 "09/29/2026,2.72,2.80,2.91,3.15,3.29\n")
TREASURY_EMPTY = 'Date,"5 YR","7 YR","10 YR","20 YR","30 YR"\n'
DFII30_CSV = "observation_date,DFII30\n2026-09-28,3.28\n"


def _serve(monkeypatch, pages: dict) -> list:
    import update

    asked: list = []

    def fake_get(url: str, timeout: float = 0) -> bytes:
        asked.append(url)
        for fragment, body in pages.items():
            if fragment in url:
                if isinstance(body, Exception):
                    raise body
                return body.encode("utf-8")
        raise DataUnavailable(f"no stand-in for {url}")

    monkeypatch.setattr(update, "_get", fake_get)
    return asked


def test_the_treasury_is_asked_first_and_named_as_the_source(monkeypatch) -> None:
    import update

    asked = _serve(monkeypatch, {"treasury.gov": TREASURY_2026,
                                 "fred.stlouisfed.org": DFII30_CSV})
    day, value, source = update.fetch_real_risk_free(date(2026, 9, 30))
    assert (day, value) == (date(2026, 9, 29), pytest.approx(0.0329))
    assert source == update.TREASURY_SOURCE
    assert not any("fred" in url for url in asked)


def test_fred_answers_when_the_treasury_does_not(monkeypatch) -> None:
    import update

    _serve(monkeypatch, {
        "treasury.gov": DataUnavailable("timed out after 40s: treasury"),
        "fred.stlouisfed.org": DFII30_CSV})
    day, value, source = update.fetch_real_risk_free(date(2026, 9, 30))
    assert (day, value) == (date(2026, 9, 28), pytest.approx(0.0328))
    assert source.startswith("FRED DFII30") and "timed out" in source


def test_an_empty_new_year_reads_the_year_before(monkeypatch) -> None:
    """On 2 January the new year's file has a header and nothing else."""
    import update

    asked = _serve(monkeypatch, {"/2027/": TREASURY_EMPTY,
                                 "/2026/": TREASURY_2026})
    day, _, source = update.fetch_real_risk_free(date(2027, 1, 2))
    assert day == date(2026, 9, 29)
    assert source == update.TREASURY_SOURCE
    assert [url for url in asked if "/2027/" in url]


def test_both_failing_names_both(monkeypatch) -> None:
    import update

    _serve(monkeypatch, {
        "treasury.gov": DataUnavailable("HTTP 503 from treasury"),
        "fred.stlouisfed.org": DataUnavailable("timed out after 40s: fred")})
    with pytest.raises(DataUnavailable, match="Treasury failed.*FRED"):
        update.fetch_real_risk_free(date(2026, 9, 30))


# --- the live config: identities, never market states ----------------------
#
# The snapshot's identities hold on the weekly file too. None of these is a
# state of the market: each is a relation the refresh itself must respect.

@pytest.mark.parametrize("name", ["market_data.toml", "snapshot.toml"])
def test_the_american_file_respects_its_own_construction(name) -> None:
    from your_equity_share.expected_return import (
        CALIBRATION_VOLATILITY, arithmetic_from_compound)

    data = load_market_data(Path(__file__).resolve().parents[1] / "variants" / "us" / name)
    p = data.provenance
    compound = float(p["expected_return_compound"])
    assert data.stock_volatility == CALIBRATION_VOLATILITY
    assert data.expected_stock_real_return == pytest.approx(
        arithmetic_from_compound(compound, data.stock_volatility), abs=5e-6)
    assert p["expected_return_estimates"].startswith("building blocks %.4f (used)" % compound)
    assert compound == pytest.approx(float(p["dividend_yield"]) + float(p["real_growth"]), abs=5e-6)


@pytest.mark.parametrize("name", ["market_data.toml", "snapshot.toml"])
def test_both_variants_use_one_growth_term(name) -> None:
    root = Path(__file__).resolve().parents[1] / "variants"
    us = load_market_data(root / "us" / name).provenance
    it = load_market_data(root / "it" / name).provenance
    assert float(us["real_growth"]) == pytest.approx(float(it["real_growth"]), abs=5e-6)


# --- the live config: structure only ---------------------------------------
#
# variants/us/market_data.toml is rewritten every time `python update.py` runs, so
# these tests check that it is well formed, never what its numbers are.


def test_live_config_loads() -> None:
    data = load_market_data(DEFAULT_CONFIG_PATH)
    assert data.stock_volatility > 0
    assert data.equity_risk_premium > 0


def test_live_config_holds_plausible_values() -> None:
    """Wide bounds. A refresh that lands outside these is a bug, not a market move."""
    data = load_market_data(DEFAULT_CONFIG_PATH)
    assert 0.05 < data.stock_volatility < 0.60
    assert -0.02 < data.real_risk_free_rate < 0.10
    assert 0.0 < data.expected_stock_real_return < 0.20


def test_live_config_is_not_stale_by_more_than_a_year() -> None:
    data = load_market_data(DEFAULT_CONFIG_PATH)
    assert (date.today() - data.as_of).days < 365


# --- the frozen fixture: values --------------------------------------------


def test_fixture_values() -> None:
    data = load_market_data(FIXTURE)
    assert data.expected_stock_real_return == pytest.approx(0.05)
    assert data.real_risk_free_rate == pytest.approx(0.025)
    assert data.stock_volatility == pytest.approx(0.185)
    assert data.equity_risk_premium == pytest.approx(0.025)


def test_market_section_alone_is_enough() -> None:
    """The model needs three numbers, and nothing else in the file is required."""
    path = Path(TMP) / "minimal.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    data = load_market_data(path)
    assert data.stock_volatility == pytest.approx(0.185)


def test_a_leftover_market_ticker_is_ignored() -> None:
    """A file written before the ticker was dropped still loads.

    update.py loads the existing file before it writes the new one, so a loader
    that refused the old key would stop the very refresh that removes it.
    """
    path = Path(TMP) / "oldticker.toml"
    path.write_text(MINIMAL + 'market_ticker = "SPY"\n', encoding="utf-8")
    data = load_market_data(path)
    assert data.stock_volatility == pytest.approx(0.185)
    assert data.equity_risk_premium == pytest.approx(0.025)
    assert not hasattr(data, "market_ticker")


def test_rejects_a_premium_that_is_not_positive() -> None:
    path = Path(TMP) / "bad.toml"
    path.write_text(
        MINIMAL.replace(
            "expected_stock_real_return = 0.05", "expected_stock_real_return = 0.02"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no reason to hold equities"):
        load_market_data(path)


def test_rejects_non_positive_volatility() -> None:
    path = Path(TMP) / "badvol.toml"
    path.write_text(
        MINIMAL.replace("stock_volatility = 0.185", "stock_volatility = 0.0"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be positive"):
        load_market_data(path)


def test_reports_a_missing_file() -> None:
    with pytest.raises(FileNotFoundError, match="update.py"):
        load_market_data(Path("does-not-exist.toml"))
