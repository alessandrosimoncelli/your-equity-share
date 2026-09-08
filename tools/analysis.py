"""Recompute the measured tables in the methodology, and check the document.

    python tools/analysis.py

Six tables in section 2 and section 3 report measurements rather than model
output: the two horizon tables, the variance ratios, the buyback worked
example, the out-of-sample backtest and its decomposition by valuation. None
of the code that produced them was in this repository. The numbers lived only
in the document, where nobody could re-run them, including their author.

That is now fixed. Everything here is recomputed from the stated method and
compared with what the document says, so a claim cannot drift from its
evidence without this failing.

Tables 2, 3 and 6 need no data and always run. Tables 4, 7 and 8 need
Shiller's workbook, which is his and not ours to redistribute, so it is
looked for beside the repository and in ./data, and SHILLER_WORKBOOK
overrides both. Its absence is a skip, not a failure.

On conventions, because one of them was the bug. Every rate here is a
compound annual rate, matching the rest of the document. The intervals in
tables 2 and 3 are symmetric in logs and their bounds are converted before
printing; stating log bounds beside dollar values, which the document used
to do, gives a reader two numbers that cannot be reconciled.
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.providers import parse_shiller_xls  # noqa: E402

DOC = ROOT / "docs" / "methodology.html"
WORKBOOK_NAME = "shiller.xls"
SHILLER_ENV = "SHILLER_WORKBOOK"

# The two-sided 5% point of the standard normal, written out so this does not
# depend on whatever library the original used.
Z90 = 1.6448536269514722

passed = 0
failed: list[str] = []
skipped: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed
    if ok:
        passed += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        failed.append(name)
        print(f"  FAIL  {name}   {detail}")


def skip(name: str, detail: str = "") -> None:
    skipped.append(name)
    print(f"  SKIP  {name}" + (f"   {detail}" if detail else ""))


def head(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\n{n}. {title}\n{'=' * 72}")


def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def in_doc(*values: str) -> bool:
    t = doc_text()
    return all(v in t for v in values)


# ---------------------------------------------------------------------------
# Tables 2 and 3: the horizon intervals
# ---------------------------------------------------------------------------

def lognormal_interval(drift: float, vol: float, years: int,
                       wealth: float = 10_000.0, z: float = Z90):
    """The 90% interval, as compound annual rates and as ending values.

    Log returns are normal with mean `drift` and standard deviation `vol` a
    year, so over `years` the log return has mean drift*T and standard
    deviation vol*sqrt(T). The bounds come back as compound rates rather than
    log rates, so they agree with the ending values.
    """
    span = z * vol * math.sqrt(years)
    low_log, high_log = drift * years - span, drift * years + span
    return (
        math.exp(low_log / years) - 1,
        math.exp(high_log / years) - 1,
        wealth * math.exp(low_log),
        wealth * math.exp(high_log),
    )


def part_one() -> None:
    head(1, "Tables 2 and 3, the horizon intervals")
    print("  5% drift, 90% interval, $10,000\n")

    for years, want in ((10, ("-3.3%", "+14.3%", "$7,173", "$37,895", "5.3")),
                        (30, ("+0.2%", "+10.3%", "$10,603", "$189,438", "17.9"))):
        lo, hi, lo_v, hi_v = lognormal_interval(0.05, 0.16, years)
        got = (f"{lo:+.1%}".replace("+-", "-"), f"{hi:+.1%}",
               f"${lo_v:,.0f}", f"${hi_v:,.0f}", f"{hi_v / lo_v:.1f}")
        check(f"Table 2, {years} years", got == want and in_doc(got[1], got[3]),
              f"{got[0]} to {got[1]}, {got[2]} to {got[3]}, {got[4]}x")

    # The annualised bound and the ending value must describe one investment.
    lo, hi, lo_v, hi_v = lognormal_interval(0.05, 0.16, 10)
    implied = (hi_v / 10_000.0) ** (1 / 10) - 1
    check("Table 2's annualised bound agrees with its own ending value",
          abs(implied - hi) < 1e-9,
          f"${hi_v:,.0f} over ten years is {implied:.2%} a year, and the table "
          f"says {hi:.1%}")

    print()
    for years, want in ((10, ("5.5", "17.5")), (30, ("3.2", "10.1")),
                        (100, ("1.7", "5.5"))):
        widths = []
        for vol in (0.05, 0.16):
            lo, hi, _, _ = lognormal_interval(0.05, vol, years)
            widths.append((hi - lo) * 100)
        ratio = widths[1] / widths[0]
        got = (f"{widths[0]:.1f}", f"{widths[1]:.1f}")
        check(f"Table 3, {years} years", got == want and abs(ratio - 3.2) < 0.005,
              f"{got[0]} and {got[1]} points, ratio {ratio:.2f}")

    check("the ratio is the ratio of the volatilities at every horizon",
          in_doc("3.20"), "16 divided by 5, which is the table's whole point")


# ---------------------------------------------------------------------------
# Table 6: the buyback worked example
# ---------------------------------------------------------------------------

def part_two() -> None:
    head(2, "Table 6, the buyback worked example")
    shares, price, earnings, dividends, buyback = 100.0, 15.0, 100.0, 30.0, 20.0
    cap = shares * price
    eps_before = earnings / shares
    multiple = price / eps_before
    shares_after = shares - buyback / price
    eps_after = earnings / shares_after          # aggregate earnings flat
    price_after = eps_after * multiple           # multiple held constant
    per_share_growth = price_after / price - 1
    holder = (dividends / shares + price_after - price) / price

    print(f"  100 shares at ${price:.0f}, earns ${earnings:.0f}, "
          f"${dividends:.0f} of dividends, ${buyback:.0f} of buybacks")
    print(f"  per-share growth {per_share_growth:.4%}, "
          f"holder's return {holder:.4%}\n")

    rows = [
        ("dividend yield with per-share growth",
         dividends / cap, per_share_growth, "3.35%"),
        ("payout yield with aggregate growth",
         (dividends + buyback) / cap, 0.0, "3.33%"),
        ("payout yield with per-share growth",
         (dividends + buyback) / cap, per_share_growth, "4.68%"),
    ]
    for label, yld, growth, want in rows:
        total = f"{yld + growth:.2%}"
        check(f"Table 6, {label}", total == want and in_doc(want),
              f"{yld:.2%} plus {growth:.2%} is {total}")

    check("the correct pairing recovers the holder's actual return",
          abs((rows[0][1] + rows[0][2]) - holder) < 1e-12,
          f"{holder:.4%}, which is what the shareholder receives")
    check("the double-counted row is too high by exactly the buyback yield",
          abs((rows[2][1] + rows[2][2]) - holder - buyback / cap) < 1e-12,
          f"{buyback / cap:.2%}")


# ---------------------------------------------------------------------------
# Tables 4, 7 and 8: the ones that need Shiller
# ---------------------------------------------------------------------------

def workbook_candidates(override: str | None) -> list[Path]:
    if override:
        return [Path(override)]
    return [ROOT.parent / WORKBOOK_NAME, ROOT / "data" / WORKBOOK_NAME]


def find_workbook(override: str | None = None) -> Path | None:
    for candidate in workbook_candidates(override):
        if candidate.exists():
            return candidate
    return None


def total_return_index(prices, dividends) -> list[float]:
    """Real total return, reinvesting each month's dividend at that price.

    Shiller's dividend column is an annual rate, so a month contributes a
    twelfth of it.
    """
    index = [1.0]
    for k in range(1, len(prices)):
        index.append(index[-1] * (prices[k] + dividends[k] / 12.0) / prices[k - 1])
    return index


def annualised_volatility(index, months: int) -> tuple[float, int]:
    """Volatility of overlapping `months`-long log returns, annualised.

    Overlapping windows use all the data. They do not manufacture independent
    observations, which is why the table reports the independent window count
    beside the estimate rather than instead of it.
    """
    returns = [math.log(index[k] / index[k - months])
               for k in range(months, len(index))]
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(variance * 12.0 / months), n


def trend_growth(series, months: int) -> float | None:
    """OLS slope of log earnings over the last `months`, as an annual rate."""
    ys = [math.log(v) for v in series[-months:] if v > 0]
    n = len(ys)
    if n < 24:
        return None
    xs = range(n)
    mx, my = (n - 1) / 2.0, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return math.exp(12 * num / den) - 1


def part_three(workbook: Path) -> None:
    head(3, "Tables 4, 7 and 8, measured on Shiller's series")
    history = parse_shiller_xls(workbook.read_bytes())
    prices = list(history.real_prices)
    dividends = list(history.real_dividends)
    earnings = list(history.real_earnings)
    cape = list(history.cape)
    index = total_return_index(prices, dividends)
    print(f"  {workbook}")
    print(f"  {len(history)} usable months, "
          f"{history.dates[0]} to {history.last_date}\n")

    one_year, _ = annualised_volatility(index, 12)
    WANT = {1: "18.30%", 2: "17.85%", 5: "16.44%",
            10: "15.28%", 20: "12.46%", 30: "8.42%"}
    for years, want in WANT.items():
        vol, n = annualised_volatility(index, 12 * years)
        ratio = (vol / one_year) ** 2
        independent = (len(index) - 1) // (12 * years)
        check(f"Table 4, {years} year volatility",
              f"{vol:.2%}" == want and in_doc(want)
              and f'>{independent}<' in doc_text(),
              f"{vol:.2%}, variance ratio {ratio:.2f}, "
              f"{n} overlapping windows over {independent} independent")

    print()
    starts = {}
    for horizon in (10, 20, 30):
        months = 12 * horizon
        rows = []
        for k in range(360, len(index) - months):
            if prices[k] <= 0 or earnings[k] <= 0 or not cape[k] or cape[k] <= 0:
                continue
            growth = trend_growth(earnings[:k + 1], min(1200, k + 1))
            if growth is None:
                continue
            realised = (index[k + months] / index[k]) ** (12.0 / months) - 1
            rows.append(dict(
                cape=cape[k], realised=realised,
                estimates={
                    "Dividend yield plus per-share growth":
                        dividends[k] / prices[k] + growth,
                    "Trailing earnings yield": earnings[k] / prices[k],
                    "Cyclically adjusted earnings yield": 1.0 / cape[k],
                    "Dividend yield alone": dividends[k] / prices[k],
                    "A flat 5%": 0.05,
                }))
        starts[horizon] = rows

    WANT7 = {
        "Dividend yield plus per-share growth": (-1.63, 5.47, -1.25, 3.12, -1.06, 2.25),
        "Trailing earnings yield": (0.38, 4.82, 0.85, 2.89, 1.17, 3.31),
        "Cyclically adjusted earnings yield": (0.19, 4.73, 0.70, 3.07, 1.08, 3.18),
        "Dividend yield alone": (-2.96, 5.96, -2.53, 3.70, -2.32, 2.91),
        "A flat 5%": (-2.12, 5.93, -1.90, 3.63, -2.02, 2.52),
    }
    for name, want in WANT7.items():
        got = []
        for horizon in (10, 20, 30):
            errs = [(r["estimates"][name] - r["realised"]) * 100
                    for r in starts[horizon]]
            got.append(sum(errs) / len(errs))
            got.append(math.sqrt(sum(e * e for e in errs) / len(errs)))
        worst = max(abs(a - b) for a, b in zip(got, want))
        check(f"Table 7, {name}", worst < 0.05,
              "bias and RMSE at ten, twenty and thirty years agree to "
              f"{worst:.2f} points")

    print()
    rows = starts[10]
    by_cape = sorted(rows, key=lambda r: r["cape"])
    fifth = len(rows) // 5
    key = "Dividend yield plus per-share growth"
    WANT8 = {"all": (7.12, 5.48), "cheapest": (11.20, 7.65),
             "dearest": (3.61, 3.54), "expensive": (3.26, 3.32)}
    for label, group, want in (
            ("all starts", rows, WANT8["all"]),
            ("cheapest fifth by CAPE", by_cape[:fifth], WANT8["cheapest"]),
            ("dearest fifth by CAPE", by_cape[-fifth:], WANT8["dearest"]),
            ("a CAPE of 25 and above",
             [r for r in rows if r["cape"] >= 25], WANT8["expensive"])):
        realised = sum(r["realised"] for r in group) / len(group) * 100
        estimate = sum(r["estimates"][key] for r in group) / len(group) * 100
        ok = (abs(realised - want[0]) < 0.05 and abs(estimate - want[1]) < 0.05)
        check(f"Table 8, {label}", ok,
              f"realised {realised:.2f}%, estimated {estimate:.2f}%, "
              f"bias {estimate - realised:+.2f} over {len(group)} starts")


if __name__ == "__main__":
    part_one()
    part_two()
    book = find_workbook(os.environ.get(SHILLER_ENV))
    if book is None:
        head(3, "Tables 4, 7 and 8, measured on Shiller's series")
        override = os.environ.get(SHILLER_ENV)
        skip("Shiller's workbook was not found, so these did not run",
             f"{SHILLER_ENV}={override}" if override else "looked in: " +
             ", ".join(str(c) for c in workbook_candidates(None)))
        print(f"\n  Download ie_data.xls from Robert Shiller's site, save it as"
              f"\n  {WORKBOOK_NAME} at one of the paths above or point "
              f"{SHILLER_ENV} at it,\n  and these three tables will be "
              f"recomputed and checked.")
    else:
        part_three(book)

    print(f"\n{'=' * 72}")
    tally = f"{passed} passed, {len(failed)} failed"
    if skipped:
        tally += f", {len(skipped)} skipped"
    print(tally)
    for name in failed:
        print(f"  FAILED: {name}")
    raise SystemExit(1 if failed else 0)
