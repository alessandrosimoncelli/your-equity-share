#!/usr/bin/env python3
"""Update the American variant's market data.

The published site runs this every Monday, followed by
tools/refresh_italy.py, which takes its growth term from the Shiller data
saved here. Run both by hand only for a copy that is not on GitHub.

    python update.py                     # fetch the latest data and save it
    python update.py --dry-run           # show what would change, save nothing
    python update.py --fixed-return 0.05 # set the expected return by hand,
                                         # as an arithmetic mean

Two of the three inputs the model uses are fetched, from free sources that
need no key or account; the third is fixed:

    real risk-free rate       the US Treasury's daily real yield curve,
                              30 years, which FRED republishes as DFII30
    expected stock return     Shiller: the dividend yield plus the 100-year
                              trend in real earnings per share, no repricing
    stock market volatility   Choi, Liu and Liu's 18.5%, fixed: monthly CRSP
                              log excess returns, 1926 to 2024. A trailing
                              window moved the answer whenever a crash entered
                              or left it, with no change in long-run risk

Damodaran's implied premium, an earnings anchor and a valuation regression are
computed beside it as cross-checks and are not used.

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
    CALIBRATION_VOLATILITY,
    CHOI_FITTED_LOG_PREMIUM_RANGE,
    CHOI_FITTED_LOG_RISK_FREE_RANGE,
    log_risk_free,
    within_fitted_risk_free,
    arithmetic_from_compound,
    building_block_estimate,
    earnings_anchor_estimate,
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
    parse_treasury_real_yield_csv,
    parse_multpl_current,
    parse_shiller_xls,
    ShillerHistory,
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
ERP_URL = "https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx"
# The long history, from Shiller's own site, whose download link is discovered
# rather than hardcoded, because the file sits behind a content delivery
# network and the address carries a version stamp that changes with every
# update. There is deliberately no fallback. The two that existed, Yale's copy
# and a community mirror, both stopped in 2023, so all they could ever supply
# was a 2023 valuation written in as today's. If the site fails, the refresh
# fails, and the weekly job keeps last week's data, which is fresher.
SHILLER_PAGE = "https://shillerdata.com/"
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

# The same number at its origin. FRED's DFII30 is the 30-year point of the
# Treasury's Daily Treasury Par Real Yield Curve, republished through the
# Federal Reserve's H.15 release: on all 186 trading days of 2026 to 28
# September the two agree exactly, and the Treasury publishes a day sooner.
# It is read first because FRED does not answer GitHub's servers, where the
# weekly refresh runs: the first scheduled attempt timed out on it. FRED stays
# as the fallback. One file per calendar year, so {year} is filled in.
TREASURY_REAL_YIELD_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_real_yield_curve&field_tdr_date_value={year}"
    "&page&_format=csv"
)
TREASURY_REAL_COLUMN = "30 YR"
TREASURY_SOURCE = "US Treasury daily par real yield curve, 30 years"

# Which configurations this script knows how to refresh.
#
# It rebuilds the whole file from one template, so running it on a
# configuration it does not understand does not merely replace a field: it
# replaces the header, the expected return and the safe rate with American
# ones, and drops the provenance recording that some of those numbers were
# provisional. That happened once, to the Italian file, during the session
# that added it. A tool quietly using the wrong country's safe asset, and
# reporting it as measured, is worse than one that admits its inputs are not
# measured yet, so an unknown variant is refused rather than rebuilt.
KNOWN_VARIANTS = {"us"}

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
# For downloads that only feed a printed comparison, so a provider that does
# not answer costs a quarter of a minute rather than two thirds of one.
REPORTING_TIMEOUT_SECONDS = 15


def _get(url: str, timeout: float = TIMEOUT_SECONDS) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise DataUnavailable(f"HTTP {exc.code} {exc.reason} from {url}") from exc
    except urllib.error.URLError as exc:
        raise DataUnavailable(f"could not reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DataUnavailable(f"timed out after {timeout:g}s: {url}") from exc


def fetch_real_risk_free(today: date | None = None) -> tuple[date, float, str]:
    """The 30-year real yield: from the Treasury, or from FRED if it fails.

    Returns the observation date, the yield as a fraction, and which of the
    two supplied it, so the written file says where the number came from.
    The Treasury keeps one file per year and a new year's file is empty on
    its first business day, so an empty current year falls back to the last.
    """
    today = today or date.today()
    try:
        for year in (today.year, today.year - 1):
            latest = parse_treasury_real_yield_csv(
                _get(TREASURY_REAL_YIELD_URL.format(year=year)).decode(
                    "utf-8", "replace"),
                TREASURY_REAL_COLUMN,
            )
            if latest is not None:
                return latest[0], latest[1], TREASURY_SOURCE
        raise DataUnavailable(
            f"the Treasury's real yield files for {today.year} and "
            f"{today.year - 1} hold no 30-year observation")
    except DataUnavailable as treasury_error:
        try:
            day, value = parse_fred_csv(
                _get(FRED_URL.format(series=FRED_REAL_RISK_FREE)).decode(
                    "utf-8", "replace"),
                FRED_REAL_RISK_FREE,
            )
        except DataUnavailable as fred_error:
            raise DataUnavailable(
                f"30-year real yield: the Treasury failed ({treasury_error}) "
                f"and so did FRED ({fred_error})") from fred_error
        return day, value, (f"FRED {FRED_REAL_RISK_FREE}, because the "
                            f"Treasury failed: {treasury_error}")


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
            "# NOT counted as income: buybacks, which Damodaran's payout yield",
            "# adds, recorded below when his workbook answered. Retiring shares",
            "# is what makes earnings per share grow, so the growth term already",
            "# carries them and adding them here would count them twice.",
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
        f"# The 30-year TIPS yield, from the Treasury's real yield curve, which",
        f"# FRED republishes as {FRED_REAL_RISK_FREE}. A real yield",
        "# already, so no inflation adjustment is applied. Before tax: in a",
        "# taxable account the inflation increase in the principal is taxed",
        "# too, so what is left is about r(1 - t) - t * inflation, not r(1 - t).",
        "# Methodology section 3.3.",
        f"real_risk_free = {f['real_risk_free']:.6f}",
        "",
        "# Fixed at Choi, Liu and Liu's 18.5%: the annualised standard",
        "# deviation of monthly CRSP value-weighted log excess returns, July",
        "# 1926 to July 2024 (paper, section 1.2). Not re-measured: a trailing",
        "# window moves the answer whenever a crash enters or leaves it.",
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
        # which belongs to the TIPS yield, would imply the
        # whole estimate was as fresh as the yield.
        f'history_as_of = "{f["history_as_of"]}"' if f.get("history_as_of")
        else "# history_as_of = none",
        f'history_source = "{f["history_source"]}"' if f.get("history_source")
        else "# history_source = none",
        'volatility_source = "Choi, Liu and Liu (2025), section 1.2: 18.5%, '
        'monthly CRSP value-weighted log excess returns, July 1926 to July '
        '2024, held fixed"',
        f'real_risk_free_source = "{f.get("real_risk_free_source", "FRED " + FRED_REAL_RISK_FREE)}"',
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
        'earnings per share, no repricing; see variants/us/methodology.html section 3"'
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


DATA_DIR = Path(__file__).resolve().parent / "data"


def _keep(raw: bytes, name: str) -> None:
    """Save the raw download beside the repository, for tools/analysis.py.

    That tool recomputes the measured tables in the methodology and needs the
    same history this refresh just read. Without a copy on disk it can only
    skip, so anyone who has run a refresh gets the twenty-seven checks and
    anyone who has not still gets the twelve that need no data.

    The file is not committed. It is Shiller's series, not this project's, and
    .gitignore excludes the directory.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / name).write_bytes(raw)
    except OSError as exc:
        # A refresh must not fail because a convenience copy could not be
        # written. The tool skips, which is what it does anyway.
        print(f"  note: could not keep {name} for tools/analysis.py: {exc}")


def fetch_shiller_history() -> tuple[ShillerHistory, str]:
    """The long history, from whichever source answers first.

    Returns the history and a description of where it came from, so the run
    and the saved configuration can both say which one was used.
    """
    problems: list[str] = []

    try:
        url = discover_shiller_url()
        raw = _get(url)
        history = parse_shiller_xls(raw)
        _keep(raw, "shiller.xls")
        return history, "Shiller's own site"
    except (DataUnavailable, urllib.error.URLError, OSError, ValueError) as exc:
        problems.append(f"Shiller's own site: {exc}")

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
    # Damodaran's workbook feeds a cross-check and the buyback figure, neither
    # of which the model reads, so an outage there must not stop a refresh.
    try:
        workbook = _get(ERP_URL)
        erp_as_of, erp = parse_damodaran_erp(workbook)
        _payout_as_of, payout_yield, _smoothed = parse_damodaran_components(workbook)
    except (DataUnavailable, urllib.error.URLError, OSError, ValueError):
        erp_as_of = erp = payout_yield = None

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
    buyback_yield = (payout_yield - dividend_yield
                     if payout_yield is not None else None)

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
    # AQR's own construction, computed exactly as they publish it. It is the
    # lower anchor around the estimate as the implied premium is the upper
    # one, and unlike the regression below it has nothing fitted.
    anchor = earnings_anchor_estimate(cape)
    if cape_note != "current":
        anchor = type(anchor)(**{**anchor.__dict__,
                                 "detail": anchor.detail + f", {cape_note}"})
    estimates = [
        building_block_estimate(
            dividend_yield,
            real_growth,
            as_of=shiller.last_date_as_date(),
            growth_basis=f"{GROWTH_WINDOW_YEARS} year trend",
        ),
        *([implied_premium_estimate(erp, real_risk_free, erp_as_of)]
          if erp is not None else []),
        anchor,
        valuation_regression_estimate(
            list(shiller.cape),
            index,
            cape,
            horizon_years=REGRESSION_HORIZON_YEARS,
            as_of=None,
        ),
    ]
    history_as_of = shiller.last_date
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
    parser.add_argument("--fixed-return", type=float, default=None,
                        help="set the expected real return by hand, as an "
                             "arithmetic mean, which is what the model takes; "
                             "Choi's guide defaults to 0.05")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true",
                        help="save even if a price series fails its checks")
    args = parser.parse_args(argv[1:])

    if args.fixed_return is not None and not -0.05 < args.fixed_return < 0.30:
        parser.error(
            f"--fixed-return {args.fixed_return} is outside any plausible range; "
            f"it is a decimal, so 5 percent is 0.05"
        )

    print("Updating market data for Your Equity Share")
    print("=" * 64)

    try:
        existing = load_market_data(args.config)
        variant = str(existing.provenance.get("variant", "us")).lower()
        if variant not in KNOWN_VARIANTS:
            raise SystemExit(
                "\n  " + str(args.config) + " declares itself the '" + variant
                + "' variant.\n"
                "  This script only knows how to refresh the United States "
                "one, and refuses\n  to rebuild a file it would fill with the "
                "wrong country's numbers.\n\n"
                "  It would write " + FRED_REAL_RISK_FREE + ", the 30-year "
                "United States TIPS, as the safe\n  rate, an American expected "
                "return, and would drop the provenance saying\n  which of "
                "those were provisional.\n"
            )
    except FileNotFoundError as exc:
        print(f"\n{exc}")
        return 1

    erp: float | None = None
    erp_as_of: date | None = None

    try:
        print("\nFetching...")

        try:
            _, short_nominal = parse_fred_csv(
                _get(FRED_URL.format(series=FRED_SHORT_NOMINAL),
                     timeout=REPORTING_TIMEOUT_SECONDS).decode(
                    "utf-8", "replace"
                ),
                FRED_SHORT_NOMINAL,
            )
            _, breakeven = parse_fred_csv(
                _get(FRED_URL.format(series=FRED_BREAKEVEN),
                     timeout=REPORTING_TIMEOUT_SECONDS).decode("utf-8", "replace"),
                FRED_BREAKEVEN,
            )
            real_cash = (1.0 + short_nominal) / (1.0 + breakeven) - 1.0
        except (DataUnavailable, urllib.error.URLError, OSError, ValueError):
            # Reporting only, so a failure here must not stop a refresh.
            real_cash = None

        rf_date, real_rf, rf_source = fetch_real_risk_free()
        print(f"  real risk-free rate (30y TIPS)   {real_rf:>8.2%}"
              f"   was {existing.real_risk_free_rate:>6.2%}"
              f"   {_change(real_rf, existing.real_risk_free_rate)}")
        if rf_source != TREASURY_SOURCE:
            print(f"    from {rf_source}")

        vol = CALIBRATION_VOLATILITY
        print(f"  stock volatility, fixed          {vol:>8.2%}   Choi's 18.5%")

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
            if buyback_yield is not None:
                print(f"      Buybacks return a further {buyback_yield:.2%} that this")
                print("      does not count as income, because per-share growth")
                print("      already carries it. Counting it twice would add")
                print(f"      {buyback_yield:.2%} to the estimate and roughly thirty")
                print("      points to the default household's equity share.")
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
                    print("      point. The yield divides that month's dividend")
                    print("      by that month's price, so it is as old as the")
                    print("      file: after a sharp market move it is out of")
                    print("      date by however far prices have moved since.")

                if months > 12:
                    # The page calls data a year old stale. A dividend yield
                    # that old saved under today's date would be worse than
                    # keeping last week's figures, so refuse.
                    raise DataUnavailable(
                        f"Shiller's history ends {history_as_of}, {months} "
                        f"months ago. Refusing to save a yield that old under "
                        f"today's date.")

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

        rf_low, rf_high = CHOI_FITTED_LOG_RISK_FREE_RANGE
        if not within_fitted_risk_free(real_rf):
            print()
            print(f"  log safe rate                    "
                  f"{log_risk_free(real_rf):>8.2%}")
            print(f"    {log_risk_free(real_rf) - rf_high:.2%} above the "
                  f"{rf_low:.0%} to {rf_high:.0%} band the approximation was")
            print(f"    fitted over. The paper calibrates its safe rate to the")
            print(f"    FIVE year TIPS yield; the guide asks for the THIRTY")
            print(f"    year yield, which has been above the band throughout.")
            print(f"    The coefficient on this regressor is 1.132, against")
            print(f"    0.267 on the drift, so this is the larger liberty.")

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
        real_risk_free_source=rf_source.replace('"', "'"),
        volatility=vol,
        ticker=existing.market_ticker,
        as_of=rf_date,
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
    print("Next, run tools/refresh_italy.py --write, so the Italian variant")
    print("takes the same growth term. On GitHub both run every Monday.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
