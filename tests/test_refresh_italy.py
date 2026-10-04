"""The Italian refresh, run end to end with its sources stubbed.

Every other Italian test compares numbers already stored with each other, so a
refresh that wrote wrong but consistent numbers would pass them all. These run
tools/refresh_italy.py itself on a copy of the market file, with the ECB, the
German finance agency, MSCI and Shiller replaced by fixed answers, and check
what it writes against values computed here from those answers.
"""

from __future__ import annotations

import math
import shutil
import sys
import tomllib
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import refresh_italy  # noqa: E402
from your_equity_share.expected_return import arithmetic_from_compound  # noqa: E402

PAR_CC = 0.038          # the ECB's 30-year par yield, continuously compounded
ALL_CC = 0.045
BREAKEVEN = 0.0228
TRADED = 0.0160
SURVEY = 0.0204
GROSS, NET = 0.0156, 0.0122
GROWTH = 0.02286


def _stub(monkeypatch, tmp_path, *, par=PAR_CC, breakeven_date=date(2026, 9, 30),
          msci_end=20260930, linker_years=19.5):
    config = tmp_path / "market_data.toml"
    shutil.copy(ROOT / "variants" / "it" / "market_data.toml", config)
    monkeypatch.setattr(refresh_italy, "CONFIG", config)

    def observe(series):
        if series == refresh_italy.NOMINAL_30Y:
            return "2026-10-01", par
        if series == refresh_italy.NOMINAL_30Y_ALL:
            return "2026-10-01", ALL_CC
        return "2026-Q3", SURVEY

    monkeypatch.setattr(refresh_italy, "observe", observe)
    monkeypatch.setattr(refresh_italy, "breakeven_inflation",
                        lambda: ("DE0001030575", linker_years, BREAKEVEN, breakeven_date))
    monkeypatch.setattr(refresh_italy, "longest_german_linker",
                        lambda: ("DE0001030575", linker_years, TRADED, breakeven_date))
    monkeypatch.setattr(refresh_italy, "trailing_dividend_yield",
                        lambda variant: (GROSS if variant == "GRTR" else NET, 20250930, msci_end))
    monkeypatch.setattr(refresh_italy, "american_growth_trend",
                        lambda: (GROWTH, "2026-06-01"))
    return config


def _written(config: Path) -> dict:
    raw = tomllib.loads(config.read_text(encoding="utf-8"))
    return {**raw["market"], **raw["provenance"]}


def test_the_refresh_writes_what_its_sources_imply(monkeypatch, tmp_path) -> None:
    config = _stub(monkeypatch, tmp_path)
    assert refresh_italy.main(["refresh_italy.py", "--write"]) == 0
    f = _written(config)
    nominal = math.expm1(PAR_CC)
    assert f["nominal_safe_yield"] == pytest.approx(nominal, abs=5e-7)
    assert f["real_risk_free"] == pytest.approx(nominal - BREAKEVEN, abs=5e-7)
    assert f["dividend_yield"] == pytest.approx(NET, abs=5e-7)
    assert f["dividend_yield_withheld"] == pytest.approx(GROSS - NET, abs=5e-7)
    compound = 1.0122 * 1.02286 - 1    # (1 + net yield)(1 + growth) - 1, by hand
    assert f["expected_return_compound"] == pytest.approx(compound, abs=5e-7)
    assert f["expected_stock_real_return"] == pytest.approx(
        arithmetic_from_compound(compound, refresh_italy.ITALY_VOLATILITY), abs=5e-7)
    assert str(f["as_of"]) == "2026-10-01"
    assert "30-year par yield" in f["real_risk_free_source"]


def test_a_negative_rate_is_written_and_then_overwritten(monkeypatch, tmp_path) -> None:
    """A pattern without the minus sign once wrote the first negative rate and
    then never matched again."""
    config = _stub(monkeypatch, tmp_path, par=0.012)
    assert refresh_italy.main(["refresh_italy.py", "--write"]) == 0
    assert _written(config)["real_risk_free"] < 0
    monkeypatch.setattr(refresh_italy, "observe",
                        lambda s: ("2026-10-01", PAR_CC) if s == refresh_italy.NOMINAL_30Y
                        else (("2026-10-01", ALL_CC) if s == refresh_italy.NOMINAL_30Y_ALL
                              else ("2026-Q3", SURVEY)))
    assert refresh_italy.main(["refresh_italy.py", "--write"]) == 0
    assert _written(config)["real_risk_free"] == pytest.approx(math.expm1(PAR_CC) - BREAKEVEN, abs=5e-7)


@pytest.mark.parametrize("kwargs", [
    {"breakeven_date": date(2026, 9, 1)},   # a break-even a month older than the curve
    {"msci_end": 20260630},                  # an MSCI window three months old
    {"linker_years": 9.5},                   # an inflation leg too short for a lifetime
])
def test_stale_or_unfit_inputs_are_refused(monkeypatch, tmp_path, kwargs) -> None:
    config = _stub(monkeypatch, tmp_path, **kwargs)
    before = config.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        refresh_italy.main(["refresh_italy.py", "--write"])
    assert config.read_text(encoding="utf-8") == before


def test_a_cross_check_that_fails_does_not_stop_the_refresh(monkeypatch, tmp_path) -> None:
    config = _stub(monkeypatch, tmp_path)

    def broken():
        raise SystemExit("no chart")

    monkeypatch.setattr(refresh_italy, "longest_german_linker", broken)
    assert refresh_italy.main(["refresh_italy.py", "--write"]) == 0
    assert "Checked against itself" not in _written(config)["real_risk_free_source"]


def test_no_premium_no_write(monkeypatch, tmp_path) -> None:
    """A safe rate above the expected return: the loader would refuse the
    file, so the refresh must refuse to write it."""
    config = _stub(monkeypatch, tmp_path, par=0.09)
    before = config.read_text(encoding="utf-8")
    assert refresh_italy.main(["refresh_italy.py", "--write"]) == 1
    assert config.read_text(encoding="utf-8") == before


def test_the_chart_is_chosen_by_its_label_not_its_place(monkeypatch) -> None:
    """The Finanzagentur page carries two charts of the same shape, real yields
    and break-evens. Taking the first set of series would work until the order
    changed and then deflate by a real yield, about 0.6 points off. This page
    puts the real-yield chart first, on purpose."""
    import io
    import urllib.request

    def chart(label, rows):
        series = ",".join(
            '{"name":"%s: remaining maturity %s years","data":[{"y":%s,"x":1790719200000},'
            '{"y":%s,"x":1790805600000}]}' % (isin, years, first, last)
            for isin, years, first, last in rows)
        return '"yAxis":{"title":{"text":"%s"}},"series":[%s]' % (label, series)

    page = "<html>" + chart("Real yield", [("DE0001030575", "19,5", 1.60, 1.64),
                                           ("DE0001030583", "8,5", 1.10, 1.12)]) \
        + chart("Break-even", [("DE0001030575", "19,5", 2.21, 2.23),
                               ("DE0001030583", "8,5", 2.05, 2.07)]) + "</html>"

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: Response(page.encode("utf-8")))
    isin, years, value, when = refresh_italy.breakeven_inflation()
    assert (isin, years) == ("DE0001030575", 19.5)
    assert value == pytest.approx(0.0223)
    assert when == date(2026, 10, 1)
    _, _, real, _ = refresh_italy.longest_german_linker()
    assert real == pytest.approx(0.0164)
