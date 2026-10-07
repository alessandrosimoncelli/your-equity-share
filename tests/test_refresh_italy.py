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
BREAKEVEN = 0.0228
GROSS, NET = 0.0156, 0.0122
GROWTH = 0.02286


# The linker's own traded real yield, two hundredths of a point from the
# rate the stubbed sources give, as on the snapshot.
TRADED = math.expm1(PAR_CC) - BREAKEVEN + 0.0002


def _stub(monkeypatch, tmp_path, *, par=PAR_CC, breakeven_date=date(2026, 9, 30),
          msci_end=20260930, linker_years=19.5, net_window=None, traded=TRADED):
    config = tmp_path / "market_data.toml"
    shutil.copy(ROOT / "variants" / "it" / "market_data.toml", config)
    monkeypatch.setattr(refresh_italy, "CONFIG", config)

    def observe(series):
        assert series == refresh_italy.NOMINAL_30Y, series
        return "2026-10-01", par

    monkeypatch.setattr(refresh_italy, "observe", observe)
    monkeypatch.setattr(refresh_italy, "linker_page", lambda: "")
    monkeypatch.setattr(refresh_italy, "breakeven_inflation",
                        lambda page=None: ("DE0001030575", linker_years, BREAKEVEN, breakeven_date))
    monkeypatch.setattr(refresh_italy, "traded_real_yield",
                        lambda page=None: ("DE0001030575", linker_years, traded, breakeven_date))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    def trailing(variant):
        if variant == "NETR" and net_window:
            return (NET, *net_window)
        return (GROSS if variant == "GRTR" else NET, 20250930, msci_end)

    monkeypatch.setattr(refresh_italy, "trailing_dividend_yield", trailing)
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
    monkeypatch.setattr(refresh_italy, "observe", lambda s: ("2026-10-01", PAR_CC))
    assert refresh_italy.main(["refresh_italy.py", "--write"]) == 0
    assert _written(config)["real_risk_free"] == pytest.approx(math.expm1(PAR_CC) - BREAKEVEN, abs=5e-7)


@pytest.mark.parametrize("kwargs", [
    {"breakeven_date": date(2026, 9, 1)},   # a break-even a month older than the curve
    {"msci_end": 20260630},                  # an MSCI window three months old
    {"linker_years": 9.5},                   # an inflation leg too short for a lifetime
    {"net_window": (20250331, 20260331)},    # net levels half a year behind the gross
])
def test_stale_or_unfit_inputs_are_refused(monkeypatch, tmp_path, kwargs) -> None:
    config = _stub(monkeypatch, tmp_path, **kwargs)
    before = config.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        refresh_italy.main(["refresh_italy.py", "--write"])
    assert config.read_text(encoding="utf-8") == before


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
    # and the check reads the other chart, by its label too, off the same
    # download when one is handed over
    isin, years, value, when = refresh_italy.traded_real_yield(refresh_italy.linker_page())
    assert (isin, years, when) == ("DE0001030575", 19.5, date(2026, 10, 1))
    assert value == pytest.approx(0.0164)


# --- the check against the linker's own traded real yield --------------------

def _outputs(path: Path) -> dict:
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


def test_the_check_is_recorded_and_handed_to_the_workflow(monkeypatch, tmp_path) -> None:
    config = _stub(monkeypatch, tmp_path)
    outputs = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    assert refresh_italy.main(["refresh_italy.py", "--write"]) == 0
    note = _written(config)["real_risk_free_source"]
    assert "lands 0.020 points away" in note and "turns red" in note
    assert _outputs(outputs) == {"safe_rate_check": "ok", "safe_rate_gap": "-0.020"}


@pytest.mark.parametrize("traded, status", [
    (math.expm1(PAR_CC) - BREAKEVEN - 0.006, "wide"),   # a misread chart: 0.6 points
    (None, "unavailable"),                              # the yield could not be read
])
def test_a_failed_check_warns_but_never_stops_the_refresh(monkeypatch, tmp_path,
                                                          traded, status) -> None:
    """Stopping would cost both pages their weekly data, since the workflow
    keeps the two variants together; the run turns red instead."""
    config = _stub(monkeypatch, tmp_path, traded=traded or 0.0)
    if traded is None:
        def unreadable(page=None):
            raise SystemExit("no chart on the page is labelled 'Real yield'")
        monkeypatch.setattr(refresh_italy, "traded_real_yield", unreadable)
    outputs = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    assert refresh_italy.main(["refresh_italy.py", "--write"]) == 0
    written = _written(config)
    assert written["real_risk_free"] == pytest.approx(math.expm1(PAR_CC) - BREAKEVEN, abs=5e-7)
    assert _outputs(outputs)["safe_rate_check"] == status


def test_the_limit_is_three_tenths_of_a_point_either_way() -> None:
    check = refresh_italy.safe_rate_check
    assert check(0.0150, 0.0121, "DE1", "DE1")[0] == "ok"
    assert check(0.0150, 0.0119, "DE1", "DE1")[0] == "wide"
    assert check(0.0150, 0.0181, "DE1", "DE1")[0] == "wide"
    # another bond's yield is no check at all
    assert check(0.0150, 0.0150, "DE1", "DE2") == ("unavailable", None)
