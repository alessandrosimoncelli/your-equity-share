"""Refresh config/market_data.toml from public sources.

Run deliberately, never as part of using the tool:

    python tools/refresh_market_data.py                 # show what would change
    python tools/refresh_market_data.py --write         # apply it
    python tools/refresh_market_data.py --window 10     # ten years of history

What it can and cannot fetch
----------------------------
Volatilities and correlations are estimated from daily closes (Stooq), and the
real risk-free rate is read from FRED as a 30-year TIPS yield. Forward
price-to-earnings ratios are not available from a free source, so they are
carried over from the existing file unchanged and their age is reported. That
split is the reason every field in the file records its own observation date.

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
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from merton_share.market_data import DEFAULT_CONFIG_PATH, load_market_data  # noqa: E402
from merton_share.statistics import (  # noqa: E402
    TRADING_DAYS_PER_YEAR,
    align_series,
    annualised_volatility,
    correlation_matrix,
    log_returns,
    validate_prices,
)

STOOQ_URL = "https://stooq.com/q/d/l/?s={ticker}&i=d"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

# 30-year Treasury Inflation-Protected Securities constant maturity. This is a
# real yield already, which is what the model needs and what Choi's guide asks
# for. Deriving a real rate as a nominal yield less a breakeven of a different
# maturity would mismatch the two.
FRED_REAL_RISK_FREE = "DFII30"

USER_AGENT = "merton-share/0.1 (research tool; contact via repository)"
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


def parse_stooq_csv(text: str, ticker: str) -> Fetched:
    """Parse Stooq's daily CSV into {date: close}."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "Close" not in reader.fieldnames:
        head = text.strip().splitlines()[:1]
        raise SystemExit(
            f"{ticker}: response is not the expected CSV. First line: {head}"
        )
    closes: dict[str, float] = {}
    for row in reader:
        raw = (row.get("Close") or "").strip()
        day = (row.get("Date") or "").strip()
        if not day or raw in ("", "N/A", "null"):
            continue
        try:
            closes[day] = float(raw)
        except ValueError:
            continue
    if not closes:
        raise SystemExit(f"{ticker}: no usable rows in the response")
    return Fetched(ticker=ticker, closes=closes)


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
    sleeves: list[dict[str, object]],
    correlation: list[list[float]],
    observations: int,
    window_years: int,
    covariance_as_of: date,
    real_risk_free: float,
    rates_as_of: date,
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        "# Static market data for the equity allocation tool.",
        "#",
        "# Regenerate with: python tools/refresh_market_data.py --write",
        "# The model reads this file and never fetches anything itself, so a",
        "# demo cannot fail because a data provider is unavailable.",
        "#",
        "# forward_pe is entered by hand. No free source publishes forward",
        "# earnings estimates, so those fields survive a refresh untouched and",
        "# their age is reported instead.",
        "",
        "[meta]",
        f'generated_at = "{now}"',
        'generated_by = "tools/refresh_market_data.py"',
        "",
        "[rates]",
        f"real_risk_free = {real_risk_free:.6f}",
        f"as_of = {rates_as_of.isoformat()}",
        f'real_risk_free_source = "FRED {FRED_REAL_RISK_FREE}, 30-year TIPS yield"',
        "",
        "[covariance]",
        f"as_of = {covariance_as_of.isoformat()}",
        f"observations = {observations}",
        f"window_years = {window_years}",
        'frequency = "daily"',
        f"trading_days_per_year = {TRADING_DAYS_PER_YEAR}",
        'source = "Stooq daily closes, price returns"',
        "correlation = [",
    ]
    for row in correlation:
        lines.append("  [" + ", ".join(f"{v: .6f}" for v in row) + "],")
    lines.append("]")
    lines.append("")

    for sleeve in sleeves:
        lines += [
            "[[sleeve]]",
            f'label = "{sleeve["label"]}"',
            f'ticker = "{sleeve["ticker"]}"',
            f"weight = {sleeve['weight']:.6f}",
            f"volatility = {sleeve['volatility']:.6f}  # annualised, from daily price returns",
            f"forward_pe = {sleeve['forward_pe']}  # hand-entered",
            f"forward_pe_as_of = {sleeve['forward_pe_as_of']}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


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
    print(f"current file: {args.config}")
    print(f"  covariance as of {existing.covariance_as_of} "
          f"({existing.covariance_observations} observations)")
    print(f"  rates as of {existing.rates_as_of}")
    for warning in existing.stale_fields():
        print(f"  stale: {warning}")
    print()

    print(f"fetching {len(existing.sleeves)} price series from Stooq")
    fetched: dict[str, dict[str, float]] = {}
    for sleeve in existing.sleeves:
        text = _get(STOOQ_URL.format(ticker=sleeve.ticker))
        series = parse_stooq_csv(text, sleeve.ticker)
        trimmed = trim_to_window(series.closes, args.window)
        fetched[sleeve.ticker] = trimmed
        first, last = min(trimmed), max(trimmed)
        print(f"  {sleeve.ticker:10s} {len(trimmed):5d} closes  {first} to {last}")

    dates, aligned = align_series(fetched)
    print(f"\ncommon calendar: {len(dates)} dates")
    if len(dates) < 2:
        raise SystemExit("series do not overlap; nothing to estimate")

    problems = []
    for ticker, prices in aligned.items():
        problems.extend(validate_prices(ticker, dates, prices))
    if problems:
        print("\nvalidation problems:")
        for problem in problems:
            print(f"  {problem}")
        if not args.force:
            raise SystemExit(
                "\nrefusing to write. Inspect the series, then rerun with --force "
                "if the data is genuinely fine."
            )
        print("\n--force given, continuing despite the above")

    returns = {t: log_returns(p) for t, p in aligned.items()}
    order = [s.ticker for s in existing.sleeves]
    volatilities = [annualised_volatility(returns[t]) for t in order]
    correlation = correlation_matrix([returns[t] for t in order])

    print("\nestimates:")
    for sleeve, vol in zip(existing.sleeves, volatilities):
        change = vol - sleeve.volatility
        print(f"  {sleeve.label:16s} volatility {vol:6.2%}  "
              f"(was {sleeve.volatility:6.2%}, {change:+.2%})")
    print("  correlation")
    for label, row in zip((s.label for s in existing.sleeves), correlation):
        print(f"    {label:16s} " + "  ".join(f"{v:6.3f}" for v in row))

    rf_date, rf = parse_fred_csv(
        _get(FRED_URL.format(series=FRED_REAL_RISK_FREE)), FRED_REAL_RISK_FREE
    )
    print()
    print(
        f"  real risk-free  {rf:6.2%}  "
        f"(was {existing.real_risk_free_rate:6.2%}) as of {rf_date}"
    )

    document = build_toml(
        sleeves=[
            {
                "label": s.label,
                "ticker": s.ticker,
                "weight": s.weight,
                "volatility": v,
                "forward_pe": s.forward_pe,
                "forward_pe_as_of": s.forward_pe_as_of.isoformat(),
            }
            for s, v in zip(existing.sleeves, volatilities)
        ],
        correlation=correlation,
        observations=len(dates) - 1,
        window_years=args.window,
        covariance_as_of=date.fromisoformat(max(dates)),
        real_risk_free=rf,
        rates_as_of=rf_date,
    )

    if not args.write:
        print("\ndry run. Rerun with --write to apply.")
        return 0

    args.config.write_text(document, encoding="utf-8")
    print(f"\nwrote {args.config}")
    reloaded = load_market_data(args.config)
    print(f"reloaded and validated: portfolio volatility "
          f"{reloaded.portfolio_variance() ** 0.5:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
