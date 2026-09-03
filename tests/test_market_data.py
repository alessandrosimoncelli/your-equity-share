"""Tests for the statistics, the config loader and the refresh parsers.

Everything here runs offline. The refresh tool's network calls are isolated in
`_get`, and the parsing and validation either side of them are tested against
fixtures held in this file. A test run must never depend on a data provider.
"""

from __future__ import annotations

import json
import math
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
market_ticker = "SPY"
as_of = 2026-06-02
"""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from merton_share.market_data import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    load_market_data,
)
from merton_share.statistics import (  # noqa: E402
    align_series,
    annualised_volatility,
    correlation_matrix,
    covariance_matrix,
    log_returns,
    validate_prices,
)
from update import (  # noqa: E402
    DataUnavailable,
    parse_fred_csv,
    parse_price_json,
    trim_to_window,
)


# --- statistics ------------------------------------------------------------


def test_log_returns_of_constant_series_are_zero() -> None:
    assert log_returns([100.0] * 5) == [0.0, 0.0, 0.0, 0.0]


def test_log_returns_are_additive() -> None:
    """The point of using logs: they sum to the cumulative return."""
    prices = [100.0, 110.0, 99.0, 121.0]
    assert sum(log_returns(prices)) == pytest.approx(math.log(121.0 / 100.0))


def test_log_returns_of_short_series_is_empty() -> None:
    assert log_returns([]) == []
    assert log_returns([100.0]) == []


def test_annualised_volatility_scales_by_root_time() -> None:
    daily = [0.01, -0.01] * 130
    annual = annualised_volatility(daily, periods_per_year=252)
    sample_sd = math.sqrt(sum(r * r for r in daily) / (len(daily) - 1))
    assert annual == pytest.approx(sample_sd * math.sqrt(252))


def test_annualised_volatility_needs_two_observations() -> None:
    with pytest.raises(ValueError, match="at least two"):
        annualised_volatility([0.01])


def test_correlation_of_identical_series_is_one() -> None:
    series = [0.01, -0.02, 0.03, 0.00, -0.01]
    result = correlation_matrix([series, series])
    assert result[0][1] == pytest.approx(1.0)


def test_correlation_of_opposite_series_is_minus_one() -> None:
    series = [0.01, -0.02, 0.03, 0.00, -0.01]
    result = correlation_matrix([series, [-v for v in series]])
    assert result[0][1] == pytest.approx(-1.0)


def test_correlation_matrix_is_symmetric_with_unit_diagonal() -> None:
    a = [0.01, -0.02, 0.03, 0.00, -0.01]
    b = [0.02, 0.01, -0.01, 0.02, 0.00]
    c = [-0.01, 0.03, 0.01, -0.02, 0.01]
    result = correlation_matrix([a, b, c])
    for i in range(3):
        assert result[i][i] == 1.0
        for j in range(3):
            assert result[i][j] == pytest.approx(result[j][i])
            assert -1.0 <= result[i][j] <= 1.0


def test_correlation_rejects_ragged_input() -> None:
    with pytest.raises(ValueError, match="differing lengths"):
        correlation_matrix([[0.1, 0.2], [0.1, 0.2, 0.3]])


def test_correlation_rejects_a_flat_series() -> None:
    with pytest.raises(ValueError, match="does not vary"):
        correlation_matrix([[0.1, 0.2, 0.3], [0.0, 0.0, 0.0]])


def test_covariance_matrix_diagonal_is_variance() -> None:
    sigma = covariance_matrix([0.16, 0.20], [[1.0, 0.5], [0.5, 1.0]])
    assert sigma[0][0] == pytest.approx(0.16**2)
    assert sigma[1][1] == pytest.approx(0.20**2)
    assert sigma[0][1] == pytest.approx(0.16 * 0.20 * 0.5)


def test_portfolio_variance_is_below_weighted_average_when_correlation_is_low() -> None:
    """The whole reason the covariance fix matters."""
    weights = [0.5, 0.5]
    vols = [0.16, 0.20]
    sigma = covariance_matrix(vols, [[1.0, 0.3], [0.3, 1.0]])
    portfolio = sum(
        weights[i] * weights[j] * sigma[i][j] for i in range(2) for j in range(2)
    )
    weighted_average = sum(w * v**2 for w, v in zip(weights, vols))
    assert portfolio < weighted_average


# --- aligning calendars ----------------------------------------------------


def test_align_series_keeps_only_shared_dates() -> None:
    dates, aligned = align_series(
        {
            "a": {"2026-01-02": 1.0, "2026-01-03": 2.0, "2026-01-06": 3.0},
            "b": {"2026-01-02": 10.0, "2026-01-06": 30.0, "2026-01-07": 40.0},
        }
    )
    assert dates == ["2026-01-02", "2026-01-06"]
    assert aligned["a"] == [1.0, 3.0]
    assert aligned["b"] == [10.0, 30.0]


def test_align_series_returns_sorted_dates() -> None:
    dates, _ = align_series({"a": {"2026-03-01": 1.0, "2026-01-01": 2.0}})
    assert dates == ["2026-01-01", "2026-03-01"]


def test_align_series_handles_no_overlap() -> None:
    dates, aligned = align_series(
        {"a": {"2026-01-02": 1.0}, "b": {"2026-02-02": 1.0}}
    )
    assert dates == []
    assert aligned == {"a": [], "b": []}


# --- validation ------------------------------------------------------------


def _clean_series(n: int = 300) -> tuple[list[str], list[float]]:
    dates = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    dates = sorted(set(dates))[:n]
    prices = [100.0 * (1.0005**i) for i in range(len(dates))]
    return dates, prices


def test_clean_series_has_no_problems() -> None:
    dates, prices = _clean_series()
    assert validate_prices("clean.us", dates, prices) == []


def test_short_series_is_rejected() -> None:
    problems = validate_prices("short.us", ["2026-01-01"], [100.0])
    assert any(p.kind == "too short" for p in problems)


def test_non_positive_price_is_rejected() -> None:
    dates, prices = _clean_series()
    prices[10] = 0.0
    problems = validate_prices("zero.us", dates, prices)
    assert any(p.kind == "non-positive price" for p in problems)


def test_duplicate_dates_are_rejected() -> None:
    dates, prices = _clean_series()
    dates[5] = dates[4]
    problems = validate_prices("dup.us", dates, prices)
    assert any(p.kind == "duplicate dates" for p in problems)


def test_unsorted_dates_are_rejected() -> None:
    dates, prices = _clean_series()
    dates[3], dates[9] = dates[9], dates[3]
    problems = validate_prices("unsorted.us", dates, prices)
    assert any(p.kind == "out of order" for p in problems)


def test_currency_change_partway_through_is_caught() -> None:
    """The fault that silently ruins a covariance estimate.

    A series that switches currency, or carries an unadjusted split, shows one
    enormous single-day move. Left in, it inflates the volatility estimate and
    distorts every correlation involving that sleeve.
    """
    dates, prices = _clean_series()
    prices = prices[:150] + [p * 1.35 for p in prices[150:]]
    problems = validate_prices("mixed.us", dates, prices)
    assert any(p.kind == "implausible jump" for p in problems)
    assert "split" in str(problems[0]) or "currency" in str(problems[0])


def test_ordinary_bad_day_is_not_flagged() -> None:
    """A 12% fall is a real market day, not a data fault."""
    dates, prices = _clean_series()
    prices = prices[:150] + [p * 0.88 for p in prices[150:]]
    assert validate_prices("crash.us", dates, prices) == []


# --- provider response parsing ---------------------------------------------


PRICE_JSON = json.dumps(
    {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"symbol": "SPY", "currency": "USD"},
                    # 2026-01-02, 2026-01-05, 2026-01-06 at midnight UTC
                    "timestamp": [1767312000, 1767571200, 1767657600],
                    "indicators": {
                        "quote": [{"close": [471.20, 473.90, 469.40]}]
                    },
                }
            ],
        }
    }
)


def test_parse_price_json() -> None:
    result = parse_price_json(PRICE_JSON, "SPY")
    assert result.ticker == "SPY"
    assert result.closes == {
        "2026-01-02": 471.20,
        "2026-01-05": 473.90,
        "2026-01-06": 469.40,
    }


def test_parse_price_json_drops_null_closes() -> None:
    """A null close is a shut exchange. Treating it as zero would invent a crash."""
    payload = json.loads(PRICE_JSON)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][1] = None
    closes = parse_price_json(json.dumps(payload), "SPY").closes
    assert "2026-01-05" not in closes
    assert len(closes) == 2


def test_parse_price_json_rejects_a_bot_check_page() -> None:
    """What the previous provider started returning instead of data."""
    html = '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
    with pytest.raises(DataUnavailable, match="not JSON"):
        parse_price_json(html, "SPY")


def test_parse_price_json_surfaces_a_provider_error() -> None:
    body = json.dumps({"chart": {"error": {"code": "Not Found"}, "result": None}})
    with pytest.raises(DataUnavailable, match="provider returned an error"):
        parse_price_json(body, "NOSUCH")


def test_parse_price_json_rejects_a_missing_series() -> None:
    body = json.dumps({"chart": {"error": None, "result": []}})
    with pytest.raises(DataUnavailable, match="did not contain a price series"):
        parse_price_json(body, "SPY")


def test_parse_price_json_rejects_mismatched_lengths() -> None:
    payload = json.loads(PRICE_JSON)
    payload["chart"]["result"][0]["timestamp"] = [1767312000]
    with pytest.raises(DataUnavailable, match="timestamps but"):
        parse_price_json(json.dumps(payload), "SPY")


def test_parse_price_json_rejects_an_all_null_series() -> None:
    payload = json.loads(PRICE_JSON)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [None] * 3
    with pytest.raises(DataUnavailable, match="no usable observations"):
        parse_price_json(json.dumps(payload), "SPY")


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


def test_trim_to_window_keeps_the_most_recent() -> None:
    closes = {f"2026-01-{d:02d}": float(d) for d in range(1, 29)}
    trimmed = trim_to_window(closes, years=0)
    assert trimmed == {}
    kept = trim_to_window(closes, years=1)
    assert len(kept) == 28


# --- the live config: structure only ---------------------------------------
#
# config/market_data.toml is rewritten every time `python update.py` runs, so
# these tests check that it is well formed, never what its numbers are.


def test_live_config_loads() -> None:
    data = load_market_data(DEFAULT_CONFIG_PATH)
    assert data.stock_volatility > 0
    assert data.equity_risk_premium > 0
    assert data.market_ticker


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
    """The model needs three numbers. Sleeves are optional."""
    path = Path(TMP) / "minimal.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    data = load_market_data(path)
    assert data.has_sleeve_detail is False
    assert data.stock_volatility == pytest.approx(0.185)


def test_market_ticker_defaults_when_absent() -> None:
    path = Path(TMP) / "noticker.toml"
    path.write_text(MINIMAL.replace('market_ticker = "SPY"', ""), encoding="utf-8")
    assert load_market_data(path).market_ticker == "SPY"


def test_derived_volatility_needs_a_breakdown() -> None:
    path = Path(TMP) / "minimal2.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    with pytest.raises(ValueError, match="no sleeve breakdown"):
        load_market_data(path).derived_stock_volatility()


def test_derived_volatility_is_below_the_worst_sleeve() -> None:
    """Correlations below 1 make the combination calmer than its parts."""
    data = load_market_data(FIXTURE)
    assert data.derived_stock_volatility() < max(s.volatility for s in data.sleeves)


def test_stock_volatility_stays_authoritative() -> None:
    """The optional breakdown must not silently override the model's input."""
    data = load_market_data(FIXTURE)
    assert data.stock_volatility == pytest.approx(0.185)
    assert data.stock_volatility != pytest.approx(data.derived_stock_volatility())


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


def test_rejects_half_a_sleeve_breakdown() -> None:
    """Sleeves without correlations, or the reverse, is a broken file."""
    path = Path(TMP) / "half.toml"
    path.write_text(
        MINIMAL
        + chr(10)
        + '[[sleeve]]'
        + chr(10)
        + 'label = "only"'
        + chr(10)
        + 'ticker = "X"'
        + chr(10)
        + "weight = 1.0"
        + chr(10)
        + "volatility = 0.16"
        + chr(10),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="both"):
        load_market_data(path)


def test_rejects_weights_that_do_not_sum_to_one() -> None:
    path = Path(TMP) / "weights.toml"
    path.write_text(
        FIXTURE.read_text(encoding="utf-8").replace(
            "weight = 0.650000", "weight = 0.750000", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sum to"):
        load_market_data(path)


def test_rejects_an_asymmetric_correlation_matrix() -> None:
    path = Path(TMP) / "asym.toml"
    path.write_text(
        FIXTURE.read_text(encoding="utf-8").replace(
            "[ 1.000000,  0.802740,  0.675494]",
            "[ 1.000000,  0.900000,  0.675494]",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not symmetric"):
        load_market_data(path)


def test_reports_a_missing_file() -> None:
    with pytest.raises(FileNotFoundError, match="update.py"):
        load_market_data(Path("does-not-exist.toml"))
