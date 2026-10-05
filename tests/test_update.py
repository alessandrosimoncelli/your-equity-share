"""update.py run end to end, with every source stubbed and the files in a
temporary folder.

The tests on the committed market files check what a refresh wrote last time,
and a push never runs one, so a refresh that annualised the safe rate twice,
or saved a history it then refused, would only have shown on a Monday. These
run the whole of update.main on made-up sources whose answers are known.
"""

from __future__ import annotations

import math
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import update  # noqa: E402
from your_equity_share.expected_return import arithmetic_from_compound  # noqa: E402
from your_equity_share.market_data import load_market_data  # noqa: E402
from your_equity_share.providers import DataUnavailable, ShillerHistory  # noqa: E402

QUOTE = 0.0329          # the Treasury's 30-year real yield, as quoted
DIVIDEND_YIELD = 0.011
GROWTH = 0.023          # exact, because the earnings below grow log-linearly
SHILLER_URL = "https://example.invalid/ie_data.xls"


def history(last: date, months: int = 1400) -> ShillerHistory:
    """A century and more of months ending at `last`, real earnings growing
    at exactly GROWTH a year and the last dividend at DIVIDEND_YIELD."""
    dates, earnings = [], []
    year, month = last.year, last.month
    for i in range(months):
        dates.append(f"{year:04d}-{month:02d}-01")
        earnings.append(math.exp(-i * math.log(1 + GROWTH) / 12))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    dates.reverse()
    earnings.reverse()
    prices = [100.0 * e for e in earnings]
    return ShillerHistory(
        dates=tuple(dates),
        real_prices=tuple(prices),
        real_dividends=tuple(DIVIDEND_YIELD * p for p in prices),
        real_earnings=tuple(earnings),
        # Varying, because a cross-check regresses returns on it.
        cape=tuple(25.0 + 10.0 * math.sin(i / 37.0) for i in range(len(dates))),
    )


def months_before(day: date, n: int) -> date:
    total = day.year * 12 + day.month - 1 - n
    return date(total // 12, total % 12 + 1, 1)


@pytest.fixture
def refresh(tmp_path, monkeypatch):
    """Run update.main on a copy of the live American file. Returns a function
    taking the history to serve and the provenance to store first."""
    config = tmp_path / "market_data.toml"
    shutil.copy(ROOT / "variants" / "us" / "market_data.toml", config)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(update, "DATA_DIR", data_dir)
    monkeypatch.setattr(update, "_TO_KEEP", {})
    yesterday = date.today() - timedelta(days=1)

    def fake_get(url, timeout=0):
        if "daily-treasury-rates.csv" in url:
            return (f'Date,"5 YR","10 YR","20 YR","30 YR"\n'
                    f'{yesterday:%m/%d/%Y},2.10,2.40,2.90,{QUOTE * 100:.2f}\n').encode()
        for series, value in (("DTB3", "3.90"), ("T10YIE", "2.35")):
            if f"id={series}" in url:
                return f"observation_date,{series}\n{yesterday},{value}\n".encode()
        if url == SHILLER_URL:
            return b"the workbook"
        raise DataUnavailable(f"not stubbed: {url}")

    monkeypatch.setattr(update, "_get", fake_get)
    monkeypatch.setattr(update, "discover_shiller_url", lambda: SHILLER_URL)

    def run(served: ShillerHistory, stored_history: date) -> int:
        """Store `stored_history` as the published vintage, then refresh."""
        text = re.sub(r'^history_as_of = ".*"$', f'history_as_of = "{stored_history}"',
                      config.read_text(encoding="utf-8"), flags=re.M)
        config.write_text(text, encoding="utf-8")
        monkeypatch.setattr(update, "parse_shiller_xls", lambda raw: served)
        return update.main(["update.py", "--config", str(config)])

    run.config, run.data_dir = config, data_dir
    return run


def test_a_refresh_annualises_once_and_compounds_the_two_terms(refresh) -> None:
    last = months_before(date.today(), 3)
    assert refresh(history(last), stored_history=months_before(date.today(), 6)) == 0

    data = load_market_data(refresh.config)
    p = data.provenance
    # The quote is kept as quoted, and the model reads it annualised, once.
    assert float(p["real_risk_free_quoted"]) == pytest.approx(QUOTE)
    assert data.real_risk_free_rate == pytest.approx((1 + QUOTE / 2) ** 2 - 1, abs=5e-7)
    # Both terms are recorded, and the estimate is their compound.
    assert float(p["dividend_yield"]) == pytest.approx(DIVIDEND_YIELD, abs=5e-7)
    assert float(p["real_growth"]) == pytest.approx(GROWTH, abs=5e-7)
    compound = float(p["expected_return_compound"])
    assert compound == pytest.approx((1 + DIVIDEND_YIELD) * (1 + GROWTH) - 1, abs=5e-6)
    assert data.expected_stock_real_return == pytest.approx(
        arithmetic_from_compound(compound, data.stock_volatility), abs=5e-6)
    assert p["history_as_of"] == last.isoformat()
    # An accepted history is kept for tools/analysis.py and the Italian refresh.
    assert (refresh.data_dir / "shiller.xls").read_bytes() == b"the workbook"


def test_an_older_vintage_is_refused_and_left_off_the_disk(refresh) -> None:
    stored = months_before(date.today(), 3)
    assert refresh(history(months_before(date.today(), 4)), stored_history=stored) == 1
    # Nothing written: the file still holds the newer vintage it had.
    assert f'history_as_of = "{stored}"' in refresh.config.read_text(encoding="utf-8")
    assert not (refresh.data_dir / "shiller.xls").exists()


def test_a_history_over_a_year_old_is_refused(refresh) -> None:
    old = months_before(date.today(), 14)
    assert refresh(history(old), stored_history=months_before(date.today(), 20)) == 1
    assert not (refresh.data_dir / "shiller.xls").exists()
