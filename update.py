#!/usr/bin/env python3
"""Update the tool's market data. Run this before using the tool.

    python update.py              # fetch the latest data and save it
    python update.py --dry-run    # show what would change, save nothing
    python update.py --years 10   # estimate volatility over ten years instead of five

Two of the three numbers the model uses can be observed, and this script
refreshes both:

    real risk-free rate     the 30-year TIPS yield, from FRED
    stock market volatility estimated from daily closes of your chosen index

The third, the expected real return on the stock market, is a judgement about
the future rather than an observation of the past. No source publishes it. It
stays as you set it in config/market_data.toml and this script reports its age.

Nothing here runs when you use the tool. The model reads the saved file, so a
slow or unreachable data provider can never break a demonstration.
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

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

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

# 30-year Treasury Inflation-Protected Securities, constant maturity. Already a
# real yield, which is what the model needs and what Choi's guide asks for.
# Deriving a real rate as a nominal yield less a breakeven of a different
# maturity would mismatch the two.
FRED_REAL_RISK_FREE = "DFII30"

# The endpoint rejects the default urllib agent string.
USER_AGENT = "Mozilla/5.0 (compatible; merton-share/0.1; research tool)"
TIMEOUT_SECONDS = 30


class DataUnavailable(Exception):
    """A provider could not be reached or returned something unusable."""


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
        raise DataUnavailable(f"HTTP {exc.code} {exc.reason} from {url}") from exc
    except urllib.error.URLError as exc:
        raise DataUnavailable(f"could not reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DataUnavailable(f"timed out after {TIMEOUT_SECONDS}s: {url}") from exc


def parse_price_json(text: str, ticker: str) -> Fetched:
    """Parse Yahoo's chart JSON into {date: close}.

    Rows with a null close are dropped. The provider emits them for days the
    exchange was shut, and carrying them through as zeros would manufacture
    enormous fake returns.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        head = text.strip().splitlines()[:1]
        raise DataUnavailable(
            f"{ticker}: response is not JSON. First line: {head}"
        ) from None

    error = (payload.get("chart") or {}).get("error")
    if error:
        raise DataUnavailable(f"{ticker}: provider returned an error: {error}")

    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        raise DataUnavailable(
            f"{ticker}: response did not contain a price series"
        ) from None

    if len(stamps) != len(closes):
        raise DataUnavailable(
            f"{ticker}: {len(stamps)} timestamps but {len(closes)} closes"
        )

    out: dict[str, float] = {}
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        out[day] = float(close)

    if not out:
        raise DataUnavailable(f"{ticker}: no usable observations in the response")
    return Fetched(ticker=ticker, closes=out)


def parse_fred_csv(text: str, series: str) -> tuple[date, float]:
    """Return the most recent non-missing observation of a FRED series."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise DataUnavailable(f"{series}: unexpected response from FRED")
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
        raise DataUnavailable(f"{series}: no observations in the response")
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


def estimate_volatility(
    ticker: str, years: int, force: bool
) -> tuple[float, date, int]:
    """Annualised volatility of one instrument, with the data checked first."""
    series = parse_price_json(
        _get(PRICE_URL.format(ticker=ticker, range=f"{max(years, 1)}y")), ticker
    )
    closes = trim_to_window(series.closes, years)
    dates = sorted(closes)
    prices = [closes[d] for d in dates]

    problems = validate_prices(ticker, dates, prices)
    if problems:
        detail = "; ".join(str(p) for p in problems)
        if not force:
            raise DataUnavailable(
                f"{ticker} failed validation: {detail}. "
                f"Rerun with --force if the data is genuinely fine."
            )
        print(f"  warning, continuing under --force: {detail}")

    return (
        annualised_volatility(log_returns(prices)),
        date.fromisoformat(dates[-1]),
        len(prices) - 1,
    )


def render_config(
    *,
    expected_return: float,
    real_risk_free: float,
    stock_volatility: float,
    market_ticker: str,
    as_of: date,
    window_years: int,
    observations: int,
    sleeves: list[dict[str, object]] | None = None,
    correlation: list[list[float]] | None = None,
    covariance_as_of: date | None = None,
    covariance_observations: int = 0,
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    nl = chr(10)
    out = [
        "# Market data for the Merton Share tool.",
        "#",
        "# Refresh with:  python update.py",
        "#",
        "# The model reads this file and never fetches anything itself, so an",
        "# unreachable data provider can never break a demonstration.",
        "#",
        "# See docs/inputs.md for what each number means.",
        "",
        "[meta]",
        f'generated_at = "{now}"',
        'generated_by = "update.py"',
        "",
        "# The three numbers the model uses. This section is required.",
        "[market]",
        "",
        "# YOUR JUDGEMENT. Not fetched, because nobody publishes a forecast of",
        "# this. Choi's guide defaults to 5%, roughly what current valuation",
        "# ratios imply if they hold and earnings growth matches its history.",
        f"expected_stock_real_return = {expected_return:.6f}",
        "",
        f"# Fetched: FRED {FRED_REAL_RISK_FREE}, the 30-year TIPS yield. Already a",
        "# real yield, so no inflation adjustment is applied. Reduce it by your",
        "# marginal income tax rate if your bonds sit in a taxable account.",
        f"real_risk_free = {real_risk_free:.6f}",
        "",
        f"# Fetched: {window_years} years of daily closes of {market_ticker},",
        f"# {observations} returns, annualised.",
        f"stock_volatility = {stock_volatility:.6f}",
        f'market_ticker = "{market_ticker}"',
        "",
        f"as_of = {as_of.isoformat()}",
    ]

    if sleeves and correlation and covariance_as_of is not None:
        rule = "# " + "-" * 72
        out += [
            "",
            rule,
            "# OPTIONAL. The model uses stock_volatility above. These sections",
            "# only let a multi-fund holder derive that number instead. Nothing",
            "# reads them unless you copy the derived figure up into [market].",
            rule,
            "",
            "[covariance]",
            f"as_of = {covariance_as_of.isoformat()}",
            f"observations = {covariance_observations}",
            f"window_years = {window_years}",
            'frequency = "daily"',
            f"trading_days_per_year = {TRADING_DAYS_PER_YEAR}",
            'source = "Yahoo daily closes, price returns"',
            "correlation = [",
        ]
        for row in correlation:
            out.append("  [" + ", ".join(f"{v: .6f}" for v in row) + "],")
        out += ["]", ""]
        for sleeve in sleeves:
            out += [
                "[[sleeve]]",
                f'label = "{sleeve["label"]}"',
                f'ticker = "{sleeve["ticker"]}"',
                f"weight = {float(sleeve['weight']):.6f}",
                f"volatility = {float(sleeve['volatility']):.6f}",
                "",
            ]

    return nl.join(out).rstrip() + nl


def _change(new: float, old: float) -> str:
    delta = (new - old) * 100
    if abs(delta) < 0.005:
        return "unchanged"
    return f"{delta:+.2f} points"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="update.py",
        description="Fetch the latest market data for the Merton Share tool.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change without saving",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="years of history used to estimate volatility (default 5)",
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="save even if a price series fails its checks",
    )
    args = parser.parse_args(argv[1:])

    if args.years < 1:
        parser.error("--years must be at least 1")

    print("Updating market data for the Merton Share tool")
    print("=" * 62)

    try:
        existing = load_market_data(args.config)
    except FileNotFoundError as exc:
        print(f"\n{exc}")
        return 1

    try:
        print("\nFetching...")

        rf_date, real_rf = parse_fred_csv(
            _get(FRED_URL.format(series=FRED_REAL_RISK_FREE)), FRED_REAL_RISK_FREE
        )
        print(
            f"  real risk-free rate (30y TIPS)   {real_rf:7.2%}"
            f"   was {existing.real_risk_free_rate:6.2%}"
            f"   {_change(real_rf, existing.real_risk_free_rate)}"
        )

        vol, vol_date, observations = estimate_volatility(
            existing.market_ticker, args.years, args.force
        )
        print(
            f"  stock volatility ({existing.market_ticker}, {args.years}y)"
            f"{'':>{max(0, 9 - len(existing.market_ticker))}}{vol:7.2%}"
            f"   was {existing.stock_volatility:6.2%}"
            f"   {_change(vol, existing.stock_volatility)}"
        )

        sleeves_payload = None
        correlation = None
        cov_as_of = None
        cov_observations = 0

        if existing.has_sleeve_detail:
            fetched: dict[str, dict[str, float]] = {}
            for sleeve in existing.sleeves:
                series = parse_price_json(
                    _get(
                        PRICE_URL.format(
                            ticker=sleeve.ticker, range=f"{max(args.years, 1)}y"
                        )
                    ),
                    sleeve.ticker,
                )
                fetched[sleeve.ticker] = trim_to_window(series.closes, args.years)

            dates, aligned = align_series(fetched)
            if len(dates) < 2:
                raise DataUnavailable("the sleeve series do not overlap")

            problems = []
            for ticker, prices in aligned.items():
                problems.extend(validate_prices(ticker, dates, prices))
            if problems and not args.force:
                raise DataUnavailable(
                    "sleeve data failed validation: "
                    + "; ".join(str(p) for p in problems)
                )

            returns = {t: log_returns(p) for t, p in aligned.items()}
            order = [s.ticker for s in existing.sleeves]
            vols = [annualised_volatility(returns[t]) for t in order]
            correlation = correlation_matrix([returns[t] for t in order])
            cov_as_of = date.fromisoformat(max(dates))
            cov_observations = len(dates) - 1
            sleeves_payload = [
                {
                    "label": s.label,
                    "ticker": s.ticker,
                    "weight": s.weight,
                    "volatility": v,
                }
                for s, v in zip(existing.sleeves, vols)
            ]

            derived = MarketData(
                expected_stock_real_return=existing.expected_stock_real_return,
                real_risk_free_rate=real_rf,
                stock_volatility=vol,
                market_ticker=existing.market_ticker,
                as_of=rf_date,
                source_path=args.config,
                sleeves=tuple(
                    Sleeve(s.label, s.ticker, s.weight, v)
                    for s, v in zip(existing.sleeves, vols)
                ),
                correlation=tuple(tuple(r) for r in correlation),
                covariance_as_of=cov_as_of,
                covariance_observations=cov_observations,
            ).derived_stock_volatility()
            print(
                f"\n  (optional) your three-fund mix implies {derived:.2%}. "
                f"The model uses {vol:.2%}"
            )
            print("  above. Copy it up into [market] only if you mean to.")

    except DataUnavailable as exc:
        print(f"\nCould not update: {exc}")
        print(f"\n{args.config} is unchanged. The tool still works on the data")
        print(f"it already has, from {existing.as_of}.")
        return 1

    age = (date.today() - existing.as_of).days
    print("\nNot fetched, this one is your judgement:")
    print(
        f"  expected stock real return       "
        f"{existing.expected_stock_real_return:7.2%}"
        f"   set {age} days ago"
    )
    print(f"  edit it in {args.config.name} if your view has changed")

    document = render_config(
        expected_return=existing.expected_stock_real_return,
        real_risk_free=real_rf,
        stock_volatility=vol,
        market_ticker=existing.market_ticker,
        as_of=min(rf_date, vol_date),
        window_years=args.years,
        observations=observations,
        sleeves=sleeves_payload,
        correlation=correlation,
        covariance_as_of=cov_as_of,
        covariance_observations=cov_observations,
    )

    if args.dry_run:
        print("\nDry run, nothing saved. Run without --dry-run to apply.")
        return 0

    args.config.write_text(document, encoding="utf-8")
    reloaded = load_market_data(args.config)
    print(f"\nSaved. Market data is now current to {reloaded.as_of}.")
    print("Run this again whenever you use the tool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
