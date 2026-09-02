"""Refresh config/market_data.toml from public sources.

Run deliberately, never as part of using the tool:

    python tools/refresh_market_data.py                 # show what would change
    python tools/refresh_market_data.py --write         # apply it
    python tools/refresh_market_data.py --window 10     # ten years of history

What it can and cannot fetch
----------------------------
The real risk-free rate is read from FRED as a 30-year TIPS yield. Where the
file describes the equity holding fund by fund, sleeve volatilities and their
correlations are also estimated from daily closes; those sections are
optional and the model does not require them.

`expected_stock_real_return` and `stock_volatility` are judgements, not
observations, so they are carried over unchanged. No free source publishes
either. Their age is reported instead.

Refusing bad data
-----------------
A refresh that quietly writes a corrupted covariance matrix is worse than no
refresh. Every series is validated before use and the run aborts on any problem
rather than writing a partial file. `--force` overrides, and says so in the
output.

Sources are public market data endpoints requiring no key or account.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from merton_share.market_data import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    MarketData,
    Sleeve,
    load_market_data,
)
from merton_share.statistics import (  # noqa: E402
    TRADING_DAYS_PER_YEAR,
    align_series,
    annualised_volatility,
    correlation_matrix,
    log_returns,
    validate_prices,
)

PRICE_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?range={range}&interval=1d"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

# 30-year Treasury Inflation-Protected Securities constant maturity. This is a
# real yield already, which is what the model needs and what Choi's guide asks
# for. Deriving a real rate as a nominal yield less a breakeven of a different
# maturity would mismatch the two.
FRED_REAL_RISK_FREE = "DFII30"

# A browser-shaped agent string. The endpoint rejects the default urllib one.
USER_AGENT = "Mozilla/5.0 (compatible; merton-share/0.1; research tool)"
TIMEOUT_SECONDS = 30


@dataclass
class Fetched:
    ticker: str
    closes: dict[str, float]


def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{url}\n  HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"{url}\n  could not reach host: {exc.reason}") from exc


def parse_price_json(text: str, ticker: str) -> Fetched:
    """Parse Yahoo's chart JSON into {date: close}.

    Rows with a null close are dropped. Yahoo emits them for days the exchange
    was shut, and carrying them through as zeros would manufacture enormous
    fake returns.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        head = text.strip().splitlines()[:1]
        raise SystemExit(
            "{}: response is not JSON. First line: {}".format(ticker, head)
        ) from None

    error = (payload.get("chart") or {}).get("error")
    if error:
        raise SystemExit("{}: provider returned an error: {}".format(ticker, error))

    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        raise SystemExit(
            "{}: response did not contain a price series".format(ticker)
        ) from None

    if len(stamps) != len(closes):
        raise SystemExit(
            "{}: {} timestamps but {} closes".format(
                ticker, len(stamps), len(closes)
            )
        )

    out: dict[str, float] = {}
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        out[day] = float(close)

    if not out:
        raise SystemExit("{}: no usable observations in the response".format(ticker))
    return Fetched(ticker=ticker, closes=out)


def parse_fred_csv(text: str, series: str) -> tuple[date, float]:
    """Return the most recent non-missing observation of a FRED series."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise SystemExit(f"{series}: unexpected FRED response")
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
        raise SystemExit(f"{series}: no observations in the response")
    return latest


def trim_to_window(closes: dict[str, float], years: int) -> dict[str, float]:
    """Keep roughly the last `years` of observations.

    The guard on `wanted` is not decorative: `sorted(closes)[-0:]` is
    `sorted(closes)[0:]`, so without it a window of zero would silently return
    the entire history instead of nothing.
    """
    wanted = years * TRADING_DAYS_PER_YEAR
    if wanted <= 0:
        return {}
    days = sorted(closes)[-wanted:]
    return {d: closes[d] for d in days}


def build_toml(
    *,
    market: dict[str, object],
    real_risk_free: float,
    rates_as_of: date,
    sleeves: list[dict[str, object]] | None = None,
    correlation: list[list[float]] | None = None,
    observations: int = 0,
    window_years: int = 0,
    covariance_as_of: date | None = None,
) -> str:
    """Render the config file.

    The [market] section is always written. The sleeve breakdown is written only
    when one was supplied, because the model does not need it.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out = [
        "# Static market data for the equity allocation tool.",
        "#",
        "# Regenerate with: python tools/refresh_market_data.py --write",
        "# The model reads this file and never fetches anything itself, so a demo",
        "# cannot fail because a data provider is unavailable.",
        "#",
        "# See docs/inputs.md for what each number means and how to choose it.",
        "",
        "[meta]",
        'generated_at = "' + now + '"',
        'generated_by = "tools/refresh_market_data.py"',
        "",
        "# The three inputs the model uses. This section is required.",
        "[market]",
        "",
        "# Judgement, not an observation. No free source publishes it, so a",
        "# refresh carries it over unchanged.",
        "expected_stock_real_return = {:.6f}".format(
            float(market["expected_stock_real_return"])
        ),
        "",
        "# Real yield already, so no inflation adjustment is applied.",
        "real_risk_free = {:.6f}".format(real_risk_free),
        "",
        "# The value the fitted human capital discount rates were calibrated on.",
        "# A refresh carries it over unchanged.",
        "stock_volatility = {:.6f}".format(float(market["stock_volatility"])),
        "",
        "as_of = " + rates_as_of.isoformat(),
        'real_risk_free_source = "FRED ' + FRED_REAL_RISK_FREE + ', 30-year TIPS yield"',
    ]

    if sleeves and correlation and covariance_as_of is not None:
        rule = "# " + "-" * 74
        out += [
            "",
            rule,
            "# OPTIONAL. The model uses stock_volatility above. These sections only",
            "# let a multi-fund holder derive that number rather than enter it.",
            rule,
            "",
            "[covariance]",
            "as_of = " + covariance_as_of.isoformat(),
            "observations = {}".format(observations),
            "window_years = {}".format(window_years),
            'frequency = "daily"',
            "trading_days_per_year = {}".format(TRADING_DAYS_PER_YEAR),
            'source = "Yahoo daily closes, price returns"',
            "correlation = [",
        ]
        for row in correlation:
            out.append("  [" + ", ".join("{: .6f}".format(v) for v in row) + "],")
        out += ["]", ""]

        for sleeve in sleeves:
            out += [
                "[[sleeve]]",
                'label = "{}"'.format(sleeve["label"]),
                'ticker = "{}"'.format(sleeve["ticker"]),
                "weight = {:.6f}".format(float(sleeve["weight"])),
                "volatility = {:.6f}".format(float(sleeve["volatility"])),
                "",
            ]

    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the static market data file from public sources."
    )
    parser.add_argument(
        "--write", action="store_true", help="apply the refresh (default is a dry run)"
    )
    parser.add_argument(
        "--window", type=int, default=5, help="years of history to estimate over"
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="file to update"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="write even if a series fails validation (records that it was forced)",
    )
    args = parser.parse_args(argv[1:])

    if args.window < 1:
        parser.error("--window must be at least 1 year")

    existing = load_market_data(args.config)
    print("current file: {}".format(args.config))
    print("  expected stock real return {:6.2%}   (judgement, carried over)".format(
        existing.expected_stock_real_return))
    print("  stock volatility           {:6.2%}   (calibration, carried over)".format(
        existing.stock_volatility))
    print("  real risk-free             {:6.2%}   as of {}".format(
        existing.real_risk_free_rate, existing.as_of))
    for warning in existing.stale_fields():
        print("  stale: {}".format(warning))

    # --- the one number this tool can actually observe ---------------------
    rf_date, rf = parse_fred_csv(
        _get(FRED_URL.format(series=FRED_REAL_RISK_FREE)), FRED_REAL_RISK_FREE
    )
    print()
    print("fetched real risk-free {:6.2%} as of {}  (change {:+.2%})".format(
        rf, rf_date, rf - existing.real_risk_free_rate))

    sleeve_payload = None
    correlation = None
    observations = 0
    covariance_as_of = None

    if not existing.has_sleeve_detail:
        print()
        print("no sleeve breakdown in this file, so nothing else to estimate.")
        print("The model uses stock_volatility from [market], which is unchanged.")
    else:
        print()
        print("optional sleeve breakdown present, estimating its covariance")
        print("fetching {} price series".format(len(existing.sleeves)))
        fetched: dict[str, dict[str, float]] = {}
        for sleeve in existing.sleeves:
            text = _get(
                PRICE_URL.format(
                    ticker=sleeve.ticker,
                    range="{}y".format(max(args.window, 1)),
                )
            )
            series = parse_price_json(text, sleeve.ticker)
            trimmed = trim_to_window(series.closes, args.window)
            fetched[sleeve.ticker] = trimmed
            print("  {:10s} {:5d} closes  {} to {}".format(
                sleeve.ticker, len(trimmed), min(trimmed), max(trimmed)))

        dates, aligned = align_series(fetched)
        print()
        print("common calendar: {} dates".format(len(dates)))
        if len(dates) < 2:
            raise SystemExit("series do not overlap; nothing to estimate")

        problems = []
        for ticker, prices in aligned.items():
            problems.extend(validate_prices(ticker, dates, prices))
        if problems:
            print()
            print("validation problems:")
            for problem in problems:
                print("  {}".format(problem))
            if not args.force:
                raise SystemExit(
                    "refusing to write. Inspect the series, then rerun with "
                    "--force if the data is genuinely fine."
                )
            print("--force given, continuing despite the above")

        returns = {t: log_returns(pr) for t, pr in aligned.items()}
        order = [s.ticker for s in existing.sleeves]
        volatilities = [annualised_volatility(returns[t]) for t in order]
        correlation = correlation_matrix([returns[t] for t in order])
        observations = len(dates) - 1
        covariance_as_of = date.fromisoformat(max(dates))

        print()
        print("estimates:")
        for sleeve, vol in zip(existing.sleeves, volatilities):
            print("  {:18s} volatility {:6.2%}  (was {:6.2%}, {:+.2%})".format(
                sleeve.label, vol, sleeve.volatility, vol - sleeve.volatility))
        print("  correlation")
        for sleeve, row in zip(existing.sleeves, correlation):
            print("    {:18s} ".format(sleeve.label)
                  + "  ".join("{:6.3f}".format(v) for v in row))

        sleeve_payload = [
            {
                "label": s.label,
                "ticker": s.ticker,
                "weight": s.weight,
                "volatility": v,
            }
            for s, v in zip(existing.sleeves, volatilities)
        ]

        implied = MarketData(
            expected_stock_real_return=existing.expected_stock_real_return,
            real_risk_free_rate=rf,
            stock_volatility=existing.stock_volatility,
            as_of=rf_date,
            source_path=args.config,
            sleeves=tuple(
                Sleeve(s.label, s.ticker, s.weight, v)
                for s, v in zip(existing.sleeves, volatilities)
            ),
            correlation=tuple(tuple(r) for r in correlation),
            covariance_as_of=covariance_as_of,
            covariance_observations=observations,
        ).derived_stock_volatility()
        print()
        print("  volatility implied by these sleeves: {:6.2%}".format(implied))
        print("  stock_volatility currently in use:   {:6.2%}".format(
            existing.stock_volatility))
        print("  The model uses the second. Copy the first into [market] only if")
        print("  you intend the recommendation to reflect this fund mix.")

    document = build_toml(
        market={
            "expected_stock_real_return": existing.expected_stock_real_return,
            "stock_volatility": existing.stock_volatility,
        },
        real_risk_free=rf,
        rates_as_of=rf_date,
        sleeves=sleeve_payload,
        correlation=correlation,
        observations=observations,
        window_years=args.window if sleeve_payload else 0,
        covariance_as_of=covariance_as_of,
    )

    if not args.write:
        print()
        print("dry run. Rerun with --write to apply.")
        return 0

    args.config.write_text(document, encoding="utf-8")
    print()
    print("wrote {}".format(args.config))
    load_market_data(args.config)
    print("reloaded and validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
