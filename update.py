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
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from your_equity_share.market_data import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    load_market_data,
)
from your_equity_share.expected_return import (  # noqa: E402
    CHOI_FITTED_LOG_PREMIUM_RANGE,
    arithmetic_from_compound,
    building_block_estimate,
    consensus,
    implied_premium_estimate,
    log_premium,
    real_total_return_index,
    spread,
    valuation_regression_estimate,
    within_fitted_range,
)
from your_equity_share.providers import (  # noqa: E402
    DataUnavailable,
    parse_damodaran_components,
    parse_damodaran_erp,
    parse_fred_csv,
    parse_multpl_current,
    parse_price_json,
    parse_shiller_csv,
    parse_shiller_xls,
    ShillerHistory,
)
from your_equity_share.statistics import (  # noqa: E402
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
# The long history, in the order it is tried. Shiller is the source; the rest
# are what to do when a URL moves, which it already has once.
#
#   1  his own site, whose download link is discovered rather than hardcoded,
#      because the file sits behind a content delivery network and the address
#      carries a version stamp that changes with every update
#   2  the same file at Yale, which is where it lived until October 2023 and
#      is still served, only frozen
#   3  a community CSV mirror, which is what this project used to use and
#      which stopped carrying CPI in September 2023, taking every deflated
#      column with it
#
# A tool meant to answer the same question in twenty years cannot rest on one
# address. Each source is validated the same way, and the run says which one
# answered and how old its data is.
SHILLER_PAGE = "https://shillerdata.com/"
SHILLER_YALE_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
SHILLER_MIRROR_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"
)
CAPE_URL = "https://www.multpl.com/shiller-pe"

# Horizon for the valuation regression. The model's own horizon is a lifetime,
# and the slope of the relation falls sharply as the horizon lengthens, so a
# ten-year fit would understate the expected return for this purpose.
REGRESSION_HORIZON_YEARS = 30

# Window for the long-run real earnings growth term. A century spans several
# regimes, which is the point. Shorter windows are dominated by the buyback era:
# the last thirty years show 5% real growth per share, which no one should
# extrapolate for a lifetime.
GROWTH_WINDOW_YEARS = 100

# 30-year Treasury Inflation-Protected Securities, constant maturity. A real
# yield already, which is what the model needs and what Choi's guide asks for.
FRED_REAL_RISK_FREE = "DFII30"

# For reporting only. A 3-month bill and a 10-year breakeven do not describe
# the same horizon, so their difference is a rough real cash rate rather than a
# precise one, which is all it needs to be: it exists to show that part of the
# distance from Choi's fitted band is the choice of safe asset. Measured this
# way in September 2026 it came to 1.37% against AQR's own 1.30% estimate.
FRED_SHORT_NOMINAL = "DTB3"
FRED_BREAKEVEN = "T10YIE"

# The price endpoint rejects the default urllib agent string.
USER_AGENT = "Mozilla/5.0 (compatible; your-equity-share/0.1; research tool)"
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
        "# Market data for Your Equity Share.",
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
    elif f["method"] == "building blocks":
        out += [
            "# What current valuation ratios imply if those ratios hold and",
            "# growth matches its long-run average, which is Choi's own stated",
            "# rationale for his 5% default. An ARITHMETIC mean, converted from",
            "# the compound rate the building blocks produce.",
            f"#   dividend yield         {f['dividend_yield']:.4f}",
            f"#   real growth per share  {f['real_growth']:.4f}   "
            f"{f['growth_window']} year trend",
            f"#   repricing              0.0000   ratios held constant",
            f"#   compound               {f['compound_return']:.4f}",
            f"#   arithmetic             {f['expected_return']:.4f}   "
            f"+ volatility drag",
            "# NOT counted as income: buybacks return a further",
            f"# {f['buyback_yield']:.4f}. Retiring shares is what makes earnings",
            "# per share grow, so the growth term already carries them and",
            "# adding them here would count them twice.",
        ]
    else:
        out += [
            "# Set by hand with --fixed-return. Choi's guide defaults to 5%,",
            "# roughly what current valuation ratios imply if they hold and",
            "# earnings growth matches its long-run average.",
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
        *(
            [
                f"expected_return_spread = {f['spread']:.6f}",
                'expected_return_basis = "arithmetic mean, converted from compound"',
                # The page shows this beside the arithmetic figure, because it
                # is the basis every published forecast is quoted on.
                f"expected_return_compound = {f['compound_return']:.6f}",
                f'expected_return_estimates = "{f["estimate_summary"]}"',
            ]
            if f.get("estimates")
            else []
        ),
        # The vintage of the long history behind two of the three estimators.
        # Prices arrive promptly; the earnings a cyclically adjusted ratio needs
        # do not, and the feed has stopped updating its derived columns before
        # while still appending price rows. Without this the file's as_of date,
        # which belongs to the TIPS yield and the volatility, would imply the
        # whole estimate was as fresh as those two.
        f'history_as_of = "{f["history_as_of"]}"' if f.get("history_as_of")
        else "# history_as_of = none",
        f'history_source = "{f["history_source"]}"' if f.get("history_source")
        else "# history_source = none",
        f'volatility_source = "Yahoo daily closes"',
        f'real_risk_free_source = "FRED {FRED_REAL_RISK_FREE}"',
        # Not an input. See the constant for what it is for.
        *(
            [f"real_cash = {f['real_cash']:.6f}"]
            if f.get("real_cash") is not None
            else []
        ),
        # Not added to the estimate. Buybacks reach the holder as growth in
        # earnings per share, which the growth term already carries, so adding
        # them here as income would count them twice. Recorded because it is
        # the size of what the dividend yield alone does not show.
        *(
            [f"buyback_yield_not_counted = {f['buyback_yield']:.6f}"]
            if f.get("buyback_yield") is not None
            else []
        ),
        'expected_return_source = "dividend yield plus long-run real growth in '
        'earnings per share, no repricing; see docs/methodology.html section 3"'
        if f["method"] == "building blocks"
        else 'expected_return_source = "set by hand"',
    ]
    return nl.join(out).rstrip() + nl


def discover_shiller_url() -> str:
    """Find the current download link on Shiller's own page.

    The file moved from Yale to a content delivery network in 2023 and the new
    address carries an opaque identifier and a version stamp. Reading the link
    off the page survives the next move; hardcoding it would not.
    """
    page = _get(SHILLER_PAGE).decode("utf-8", "replace")
    links = re.findall(r'href="([^"]*ie_data\.xls[^"]*)"', page, re.I)
    if not links:
        raise DataUnavailable("no ie_data.xls link found on Shiller's page")
    url = links[0]
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = SHILLER_PAGE.rstrip("/") + url
    return url


def fetch_shiller_history() -> tuple[ShillerHistory, str]:
    """The long history, from whichever source answers first.

    Returns the history and a description of where it came from, so the run
    and the saved configuration can both say which one was used.
    """
    problems: list[str] = []

    try:
        url = discover_shiller_url()
        history = parse_shiller_xls(_get(url))
        return history, "Shiller's own site"
    except (DataUnavailable, urllib.error.URLError, OSError, ValueError) as exc:
        problems.append(f"Shiller's own site: {exc}")

    try:
        history = parse_shiller_xls(_get(SHILLER_YALE_URL))
        return history, "Yale, no longer updated"
    except (DataUnavailable, urllib.error.URLError, OSError, ValueError) as exc:
        problems.append(f"Yale: {exc}")

    try:
        history = parse_shiller_csv(_get(SHILLER_MIRROR_URL).decode("utf-8", "replace"))
        return history, "community CSV mirror"
    except (DataUnavailable, urllib.error.URLError, OSError, ValueError) as exc:
        problems.append(f"mirror: {exc}")

    raise DataUnavailable(
        "no source for the long history answered. Tried:\n    "
        + "\n    ".join(problems)
    )


def estimate_expected_return(
    real_risk_free: float,
) -> tuple[list, str, str, float, float, float]:
    """Build the expected real return three independent ways.

    Each uses free public data and none of them needs a key. They disagree by
    several percentage points, which is the honest state of knowledge about
    this input, so all three are returned rather than one. The trailing values
    are the pieces of the first estimate, for the record it writes: the
    buyback yield, which is reported but deliberately not used, and the two
    terms that are.
    """
    workbook = _get(ERP_URL)
    erp_as_of, erp = parse_damodaran_erp(workbook)
    payout_as_of, payout_yield, _smoothed = parse_damodaran_components(workbook)

    shiller, shiller_source = fetch_shiller_history()
    # The trend through the window, not the two months at its ends. See
    # ShillerHistory.real_earnings_trend_growth for the measured difference.
    real_growth = shiller.real_earnings_trend_growth(GROWTH_WINDOW_YEARS)

    # Dividends only. Damodaran's payout yield adds buybacks, and a buyback is
    # already inside `real_growth`, since retiring shares is what lifts earnings
    # per share. See building_block_estimate for the arithmetic. The buyback
    # yield is still worth carrying: it is the size of the term this estimate
    # leaves out, and the reason the dividend yield reads so low.
    dividend_yield = shiller.dividend_yield
    buyback_yield = payout_yield - dividend_yield

    # A current cyclically adjusted ratio, falling back to Shiller's own last
    # observation when the scrape fails. The fallback is months stale but the
    # ratio moves slowly, and a stale ratio beats no estimate.
    try:
        cape = parse_multpl_current(
            _get(CAPE_URL).decode("utf-8", "replace"), "Shiller PE"
        )
        if not 5.0 < cape < 80.0:
            raise DataUnavailable(f"CAPE of {cape} is implausible")
        cape_note = "current"
    except DataUnavailable:
        cape = shiller.cape[-1]
        cape_note = f"as of {shiller.dates[-1]}, current value unavailable"

    index = real_total_return_index(
        list(shiller.real_prices), list(shiller.real_dividends)
    )

    # Order matters: the first is the estimate, the rest are cross-checks.
    estimates = [
        building_block_estimate(
            dividend_yield,
            real_growth,
            as_of=shiller.last_date_as_date(),
            growth_basis=f"{GROWTH_WINDOW_YEARS} year trend",
        ),
        implied_premium_estimate(erp, real_risk_free, erp_as_of),
        valuation_regression_estimate(
            list(shiller.cape),
            index,
            cape,
            horizon_years=REGRESSION_HORIZON_YEARS,
            as_of=None,
        ),
    ]
    history_as_of = shiller.last_date
    if cape_note != "current":
        estimates[2] = type(estimates[2])(
            **{**estimates[2].__dict__, "detail": estimates[2].detail + f", {cape_note}"}
        )
    return (estimates, history_as_of, shiller_source, buyback_yield,
            dividend_yield, real_growth)


def _change(new: float, old: float) -> str:
    delta = (new - old) * 100
    return "unchanged" if abs(delta) < 0.005 else f"{delta:+.2f} points"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="update.py",
        description="Fetch the latest market data for Your Equity Share.",
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

    print("Updating market data for Your Equity Share")
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

        try:
            _, short_nominal = parse_fred_csv(
                _get(FRED_URL.format(series=FRED_SHORT_NOMINAL)).decode(
                    "utf-8", "replace"
                ),
                FRED_SHORT_NOMINAL,
            )
            _, breakeven = parse_fred_csv(
                _get(FRED_URL.format(series=FRED_BREAKEVEN)).decode("utf-8", "replace"),
                FRED_BREAKEVEN,
            )
            real_cash = (1.0 + short_nominal) / (1.0 + breakeven) - 1.0
        except (DataUnavailable, urllib.error.URLError, OSError, ValueError):
            # Reporting only, so a failure here must not stop a refresh.
            real_cash = None

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
            estimates = []
            history_as_of = None
            history_source = None
            buyback_yield = dividend_yield = real_growth = None
            print(f"  expected stock real return       {expected:>8.2%}"
                  f"   set by hand")
        else:
            method = "building blocks"
            (estimates, history_as_of, history_source, buyback_yield,
             dividend_yield, real_growth) = estimate_expected_return(real_rf)
            chosen, *cross_checks = estimates
            erp_as_of = next(
                (e.as_of for e in estimates if e.method == "implied premium"), None
            )
            erp = next(
                (e.value - real_rf for e in estimates
                 if e.method == "implied premium"), None
            )

            print()
            print("  Expected real return on equities.")
            print("  A COMPOUND return, which is what a Gordon discount rate,")
            print("  a discounted cash flow and a regression on annualised")
            print("  returns all produce.")
            print(f"    {chosen.method:<28s} {chosen.value:>7.2%}   <- used")
            print(f"      {chosen.detail}")
            print("      Choi's own stated rationale for his 5% default: what")
            print("      current valuation ratios imply if those ratios hold")
            print("      and growth matches its long-run average. It is also")
            print("      the method behind AQR's 1.9%, the figure he anchors")
            print("      his own 2% log premium to.")
            print(f"      Buybacks return a further {buyback_yield:.2%} that this")
            print("      does not count as income, because per-share growth")
            print("      already carries it. Counting it twice would add")
            print(f"      {buyback_yield:.2%} to the estimate and roughly twenty")
            print("      points to the recommended equity share.")
            print()
            print("  Cross-checks, not used. See section 3 of the methodology")
            print("  for why each is worse for a lifetime horizon.")
            for estimate in cross_checks:
                error = (
                    f" +/- {estimate.standard_error:.2%}"
                    if estimate.standard_error is not None
                    else ""
                )
                print(f"    {estimate.method:<28s} {estimate.value:>7.2%}{error}")
                print(f"      {estimate.detail}")
            if history_as_of:
                from datetime import date as _date
                y, m, _d = (int(x) for x in history_as_of.split("-"))
                today = datetime.now(timezone.utc).date()
                months = (today.year - y) * 12 + today.month - m
                warn = "  <- STALE" if months > 6 else ""
                print(f"    long history runs to        {history_as_of}"
                      f"   {months} months behind{warn}")
                print(f"      source: {history_source}")
                if months > 6:
                    print("      Both terms come from this month of that file.")
                    print("      Growth is the trend through a century, where")
                    print("      three years of lag moves it about a basis")
                    print("      point. The yield is a ratio of two figures in")
                    print("      the same row, so the lag largely cancels.")

            print()
            compound = chosen.value
            expected = arithmetic_from_compound(compound, vol)
            print(f"    {'as an arithmetic mean':<28s} {expected:>7.2%}   "
                  f"+{(expected - compound) * 100:.2f} from the volatility drag")
            print(f"      The paper states the conversion itself: the level")
            print(f"      premium is exp(r + pi + sigma^2/2) - exp(r).")
            print(f"    {'spread of the cross-checks':<28s} "
                  f"{spread(estimates):>7.2%}   <- how little is known here")
            print(f"  was {existing.expected_stock_real_return:.2%}, "
                  f"{_change(expected, existing.expected_stock_real_return)}")

        pi = log_premium(expected, real_rf)
        low, high = CHOI_FITTED_LOG_PREMIUM_RANGE
        print()
        print(f"  log excess drift (Choi's pi)     {pi:>8.2%}")
        if within_fitted_range(expected, real_rf):
            print(f"    inside the {low:.0%} to {high:.0%} band the approximation was")
            print(f"    fitted over.")
        else:
            distance = low - pi if pi < low else pi - high
            side = "below" if pi < low else "above"
            print(f"    {distance:.2%} {side} the {low:.0%} to {high:.0%} band the")
            print(f"    approximation was fitted over.")
            if pi > high:
                print(f"    Choi notes allocations saturate at 100% by {high:.0%}, so")
                print(f"    being above the band is benign.")
            else:
                print(f"    Below the band is the unvalidated side: he does not")
                print(f"    address it. Today's high real rates compress the premium,")
                print(f"    which is what puts us here. Read the answer as indicative.")

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
        spread=spread(estimates) if estimates else 0.0,
        estimate_summary="; ".join(
            f'{e.method} {e.value:.4f}{" (used)" if i == 0 else ""}'
            for i, e in enumerate(estimates)
        ) if estimates else "",
        estimates=bool(estimates),
        history_as_of=history_as_of,
        history_source=history_source,
        real_cash=real_cash,
        buyback_yield=buyback_yield,
        dividend_yield=dividend_yield,
        real_growth=real_growth,
        growth_window=GROWTH_WINDOW_YEARS,
        compound_return=estimates[0].value if estimates else expected,
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
