#!/usr/bin/env python3
"""Update the tool's market data. Run this before using the tool.

    python update.py                     # fetch the latest data and save it
    python update.py --dry-run           # show what would change, save nothing
    python update.py --years 10          # volatility over ten years, not five
    python update.py --fixed-return 0.05 # set the expected return by hand

All three inputs the model uses are now fetched, from three free sources that
need no key or account:

    real risk-free rate       FRED, the 30-year TIPS yield
    stock market volatility   Yahoo, daily adjusted closes
    expected stock return     Damodaran's implied equity risk premium,
                              published monthly, plus the real risk-free rate

Nothing here runs when you use the tool. The model reads the saved file, so a
slow or unreachable provider can never break a demonstration.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from merton_share.market_data import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    load_market_data,
)
from merton_share.providers import (  # noqa: E402
    DataUnavailable,
    parse_damodaran_erp,
    parse_fred_csv,
    parse_price_json,
)
from merton_share.statistics import (  # noqa: E402
    TRADING_DAYS_PER_YEAR,
    annualised_volatility,
    log_returns,
    validate_prices,
)

PRICE_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?range={range}&interval=1d"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
ERP_URL = "https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx"

# 30-year Treasury Inflation-Protected Securities, constant maturity. A real
# yield already, which is what the model needs and what Choi's guide asks for.
FRED_REAL_RISK_FREE = "DFII30"

# The price endpoint rejects the default urllib agent string.
USER_AGENT = "Mozilla/5.0 (compatible; merton-share/0.1; research tool)"
TIMEOUT_SECONDS = 40


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise DataUnavailable(f"HTTP {exc.code} {exc.reason} from {url}") from exc
    except urllib.error.URLError as exc:
        raise DataUnavailable(f"could not reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DataUnavailable(f"timed out after {TIMEOUT_SECONDS}s: {url}") from exc


def trim_to_window(closes: dict[str, float], years: int) -> dict[str, float]:
    """Keep roughly the last `years` of observations.

    The guard is not decorative: `sorted(x)[-0:]` is `sorted(x)[0:]`, so without
    it a window of zero would return the whole history instead of nothing.
    """
    wanted = years * TRADING_DAYS_PER_YEAR
    if wanted <= 0:
        return {}
    days = sorted(closes)[-wanted:]
    return {d: closes[d] for d in days}


def estimate_volatility(
    ticker: str, years: int, force: bool
) -> tuple[float, date, int, bool]:
    """Annualised volatility of one instrument, with the series checked first."""
    series = parse_price_json(
        _get(PRICE_URL.format(ticker=ticker, range=f"{max(years, 1)}y")).decode(
            "utf-8", "replace"
        ),
        ticker,
    )
    closes = trim_to_window(series.closes, years)
    dates = sorted(closes)
    prices = [closes[d] for d in dates]

    problems = validate_prices(ticker, dates, prices)
    if problems:
        detail = "; ".join(str(p) for p in problems)
        if not force:
            raise DataUnavailable(
                f"{ticker} failed its checks: {detail}. "
                f"Rerun with --force if the data is genuinely fine."
            )
        print(f"  warning, continuing under --force: {detail}")

    return (
        annualised_volatility(log_returns(prices)),
        date.fromisoformat(dates[-1]),
        len(prices) - 1,
        series.adjusted,
    )


def render_config(**f) -> str:
    nl = chr(10)
    out = [
        "# Market data for the Merton Share tool.",
        "#",
        "# Refresh with:  python update.py",
        "#",
        "# The model reads this file and never fetches anything itself, so an",
        "# unreachable provider can never break a demonstration.",
        "#",
        "# See docs/inputs.md for what each number means.",
        "",
        "[meta]",
        f'generated_at = "{f["generated_at"]}"',
        'generated_by = "update.py"',
        "",
        "# The three numbers the model uses. This section is required.",
        "[market]",
        "",
    ]
    if f["method"] == "implied":
        out += [
            "# Implied equity risk premium plus the real risk-free rate. The",
            "# premium is Damodaran's, published monthly, and is derived by",
            "# discounting expected index cash flows back to the current level.",
            f"#   implied premium {f['erp']:.4f} as of {f['erp_as_of']}",
            f"#   plus real rate  {f['real_risk_free']:.4f}",
            "# CAVEAT. The premium is quoted against the 10-year NOMINAL",
            "# Treasury. Adding it to a 30-year REAL yield treats the premium",
            "# as neutral to both maturity and inflation, which it is not",
            "# exactly. Pairing it with Damodaran's own 10-year nominal and a",
            "# 10-year breakeven gives a real expected return about half a",
            "# point lower. The 30-year real yield is used here because the",
            "# model's horizon is a whole lifetime.",
        ]
    else:
        out += [
            "# Set by hand. Choi's guide defaults to 5%, roughly what current",
            "# valuation ratios imply if they hold and earnings growth matches",
            "# its long-run average.",
        ]
    out += [
        f"expected_stock_real_return = {f['expected_return']:.6f}",
        "",
        f"# FRED {FRED_REAL_RISK_FREE}, the 30-year TIPS yield. A real yield",
        "# already, so no inflation adjustment is applied. Reduce it by your",
        "# marginal income tax rate if your bonds sit in a taxable account.",
        f"real_risk_free = {f['real_risk_free']:.6f}",
        "",
        f"# {f['window_years']} years of daily "
        f"{'adjusted' if f['adjusted'] else 'UNADJUSTED'} closes of "
        f"{f['ticker']},",
        f"# {f['observations']} returns, annualised.",
        f"stock_volatility = {f['volatility']:.6f}",
        f'market_ticker = "{f["ticker"]}"',
        "",
        f"as_of = {f['as_of'].isoformat()}",
        "",
        "# Where each number came from. The model does not read this section.",
        "[provenance]",
        f'expected_return_method = "{f["method"]}"',
        f"implied_erp = {f['erp']:.6f}" if f["erp"] is not None else "implied_erp = 0.0",
        f"erp_as_of = {f['erp_as_of']}" if f["erp_as_of"] else "# erp_as_of = none",
        f"volatility_window_years = {f['window_years']}",
        f"volatility_observations = {f['observations']}",
        f"volatility_dividend_adjusted = {'true' if f['adjusted'] else 'false'}",
        f'volatility_source = "Yahoo daily closes"',
        f'real_risk_free_source = "FRED {FRED_REAL_RISK_FREE}"',
        'expected_return_source = "Damodaran implied ERP + real risk-free rate"'
        if f["method"] == "implied"
        else 'expected_return_source = "set by hand"',
    ]
    return nl.join(out).rstrip() + nl


def _change(new: float, old: float) -> str:
    delta = (new - old) * 100
    return "unchanged" if abs(delta) < 0.005 else f"{delta:+.2f} points"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="update.py",
        description="Fetch the latest market data for the Merton Share tool.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change without saving")
    parser.add_argument("--years", type=int, default=5,
                        help="years of history for the volatility estimate")
    parser.add_argument("--fixed-return", type=float, default=None,
                        help="set the expected real return by hand, e.g. 0.05")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true",
                        help="save even if a price series fails its checks")
    args = parser.parse_args(argv[1:])

    if args.years < 1:
        parser.error("--years must be at least 1")
    if args.fixed_return is not None and not -0.05 < args.fixed_return < 0.30:
        parser.error(
            f"--fixed-return {args.fixed_return} is outside any plausible range; "
            f"it is a decimal, so 5 percent is 0.05"
        )

    print("Updating market data for the Merton Share tool")
    print("=" * 64)

    try:
        existing = load_market_data(args.config)
    except FileNotFoundError as exc:
        print(f"\n{exc}")
        return 1

    erp: float | None = None
    erp_as_of: date | None = None

    try:
        print("\nFetching...")

        rf_date, real_rf = parse_fred_csv(
            _get(FRED_URL.format(series=FRED_REAL_RISK_FREE)).decode(
                "utf-8", "replace"
            ),
            FRED_REAL_RISK_FREE,
        )
        print(f"  real risk-free rate (30y TIPS)   {real_rf:>8.2%}"
              f"   was {existing.real_risk_free_rate:>6.2%}"
              f"   {_change(real_rf, existing.real_risk_free_rate)}")

        vol, vol_date, observations, adjusted = estimate_volatility(
            existing.market_ticker, args.years, args.force
        )
        label = f"stock volatility ({existing.market_ticker}, {args.years}y)"
        print(f"  {label:<32.32s} {vol:>8.2%}"
              f"   was {existing.stock_volatility:>6.2%}"
              f"   {_change(vol, existing.stock_volatility)}")
        if not adjusted:
            print("    note: provider returned unadjusted closes, so this is a")
            print("    price-return estimate and reads a few basis points high")

        if args.fixed_return is not None:
            method = "fixed"
            expected = args.fixed_return
            print(f"  expected stock real return       {expected:>8.2%}"
                  f"   set by hand")
        else:
            method = "implied"
            erp_as_of, erp = parse_damodaran_erp(_get(ERP_URL))
            expected = erp + real_rf
            print(f"  implied equity risk premium      {erp:>8.2%}"
                  f"   Damodaran, {erp_as_of}")
            print(f"  expected stock real return       {expected:>8.2%}"
                  f"   was {existing.expected_stock_real_return:>6.2%}"
                  f"   {_change(expected, existing.expected_stock_real_return)}")
            print(f"    = implied premium {erp:.2%} + real rate {real_rf:.2%}")

        if expected <= real_rf:
            raise DataUnavailable(
                f"expected return {expected:.2%} is not above the real risk-free "
                f"rate {real_rf:.2%}, which would mean holding no equities at all. "
                f"Refusing to save."
            )

    except DataUnavailable as exc:
        print(f"\nCould not update: {exc}")
        print(f"\n{args.config.name} is unchanged. The tool still works on the")
        print(f"data it already has, from {existing.as_of}.")
        return 1

    document = render_config(
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        method=method,
        expected_return=expected,
        real_risk_free=real_rf,
        volatility=vol,
        ticker=existing.market_ticker,
        as_of=min(rf_date, vol_date),
        window_years=args.years,
        observations=observations,
        adjusted=adjusted,
        erp=erp,
        erp_as_of=erp_as_of.isoformat() if erp_as_of else None,
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
