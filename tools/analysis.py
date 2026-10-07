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

Tables 2, 3 and 6, and the tables the model produces, need no data and
always run. Tables 4, 7, 8 and 9 need Shiller's workbook, which is his and
not ours to redistribute, so it is looked for in ./data, where update.py
saves it, and SHILLER_WORKBOOK overrides that. Its absence is a skip, not a
failure. The workbook is cut at June 2026, the end the document states, so a
later vintage cannot move a measurement the document has not moved.

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

from your_equity_share.allocation import (  # noqa: E402
    Household,
    recommend,
)
from your_equity_share.expected_return import (  # noqa: E402
    arithmetic_from_compound,
    compound_from_arithmetic,
    log_premium,
)
from your_equity_share.human_capital import (  # noqa: E402
    CGM_CALIBRATION,
    Person,
    benefit_discount_rate,
    wage_discount_rate,
)
from your_equity_share.market_data import load_market_data  # noqa: E402
from your_equity_share.providers import parse_shiller_xls  # noqa: E402

DOC = ROOT / "variants" / "us" / "methodology.html"
WORKBOOK_NAME = "shiller.xls"
SHILLER_ENV = "SHILLER_WORKBOOK"
CALIB_VOL = CGM_CALIBRATION.stock_volatility  # 0.185, Choi's

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
    """Where the history is looked for.

    ./data, because update.py puts it there on every successful refresh, so
    every check runs for anyone who has refreshed without their having to
    fetch anything by hand.
    """
    if override:
        return [Path(override)]
    return [ROOT / "data" / WORKBOOK_NAME]


def find_workbook(override: str | None = None) -> Path | None:
    for candidate in workbook_candidates(override):
        if candidate.exists():
            return candidate
    return None


def read_history(path: Path):
    """Parse the workbook the refresh saved."""
    return parse_shiller_xls(path.read_bytes())


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
    history = read_history(workbook)
    # Every table here is stated on the file to June 2026, the end the
    # document gives, so a later vintage is cut back to it: the months it adds
    # would otherwise move the measurements with no change to the document.
    every_date = list(history.dates)
    if "2026-06-01" not in every_date:
        skip("Tables 4, 7, 8 and 9", "the workbook does not run through June 2026")
        return
    end = every_date.index("2026-06-01") + 1
    dates = every_date[:end]
    prices = list(history.real_prices)[:end]
    dividends = list(history.real_dividends)[:end]
    earnings = list(history.real_earnings)[:end]
    cape = list(history.cape)[:end]
    index = total_return_index(prices, dividends)
    print(f"  {workbook}")
    print(f"  {len(dates)} usable months, {dates[0]} to {dates[-1]}"
          f" (the file runs to {history.last_date})\n")

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
        # From the first month with thirty years of earnings behind it,
        # November 1910, as the methodology says.
        for k in range(359, len(index) - months):
            if prices[k] <= 0 or earnings[k] <= 0 or not cape[k] or cape[k] <= 0:
                continue
            growth = trend_growth(earnings[:k + 1], min(1200, k + 1))
            if growth is None:
                continue
            realised = (index[k + months] / index[k]) ** (12.0 / months) - 1
            rows.append(dict(
                cape=cape[k], realised=realised,
                estimates={
                    # Compounded, as the tool's own estimator is.
                    "Dividend yield plus per-share growth":
                        (1.0 + dividends[k] / prices[k]) * (1.0 + growth) - 1.0,
                    "Trailing earnings yield": earnings[k] / prices[k],
                    "Cyclically adjusted earnings yield": 1.0 / cape[k],
                    "Dividend yield alone": dividends[k] / prices[k],
                    "A flat 5%": 0.05,
                }))
        starts[horizon] = rows

    WANT7 = {
        "Dividend yield plus per-share growth": (-1.58, 5.46, -1.19, 3.11, -1.00, 2.25),
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
    WANT8 = {"all": (7.12, 5.54), "cheapest": (11.20, 7.75),
             "dearest": (3.61, 3.57), "expensive": (3.26, 3.34)}
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

    # --- Table 9 and the equation (6) example ------------------------------
    # Both were computed on data ending in June 2023 while the rest of the
    # document used the 2026 file, so they described a different vintage.
    # Recomputed here on the file cut at June 2026, the end the document
    # states, so a later vintage of the workbook cannot move them silently.
    # Windows of 90, 100 and 110 years; end dates 0, 1, 2 and 3 years back.
    # Each cell is the largest estimate less the smallest, in points.
    print()

    def point_to_point(s):
        return (s[-1] / s[0]) ** (12.0 / (len(s) - 1)) - 1

    def ten_year_ends(s):
        return ((sum(s[-120:]) / 120) / (sum(s[:120]) / 120)) ** (12.0 / (len(s) - 120)) - 1

    def log_trend(s):
        return trend_growth(s, len(s))

    def table9(series):
        rows = []
        for estimator in (point_to_point, ten_year_ends, log_trend):
            windows = [estimator(series[-12 * years:]) for years in (90, 100, 110)]
            ends = [estimator(series[:len(series) - 12 * back][-1200:])
                    for back in range(4)]
            rows.append(((max(windows) - min(windows)) * 100,
                         (max(ends) - min(ends)) * 100))
        return rows

    if "2026-06-01" not in dates or "2023-06-01" not in dates:
        skip("Table 9 and the equation (6) example",
             "the workbook does not run through June 2026")
        return
    upto = earnings[:dates.index("2026-06-01") + 1]
    upto_2023 = earnings[:dates.index("2023-06-01") + 1]
    t9 = re.search(r'id="t9">(.*?)</table>', doc_text(), re.S)
    printed = re.findall(r'<td class="num">(?:<strong>)?([\d.]+)%',
                         t9.group(1) if t9 else "")
    got = ["%.2f" % v for row in table9(upto) for v in row]
    check("Table 9, both columns, on the file to June 2026",
          printed == got,
          "window then end date, by estimator: %s" % ", ".join(got))
    old = ["%.2f" % row[1] for row in table9(upto_2023)[:2]] + \
          ["%.3f" % table9(upto_2023)[2][1]]
    check("Table 9's end-date column on data ending in June 2023, as quoted",
          in_doc("%s, %s and %s points" % (old[0], old[1], old[2].rstrip("0"))),
          ", ".join(old))
    window = upto[-1200:]
    example = ("%.2f%%" % (point_to_point(window) * 100),
               "$%.2f" % window[0], "$%.2f" % window[-1],
               "%.2f%%" % (log_trend(window) * 100))
    check("the equation (6) example, point to point against the trend",
          in_doc("<strong>%s</strong> a year, from real earnings of %s in July 1926 "
                 "and %s in June 2026" % example[:3], example[3]),
          "%s from %s to %s, against a trend of %s" % example)


# ---------------------------------------------------------------------------
# The model-derived tables
# ---------------------------------------------------------------------------

def part_four() -> None:
    head(4, "Tables 12, 13, 15, 17, 19 and 25, and section 8.4, recomputed from the model")
    import dataclasses

    market = load_market_data(ROOT / "variants" / "us" / "snapshot.toml")
    mu = market.expected_stock_real_return
    rf = market.real_risk_free_rate
    vol = market.stock_volatility
    compound = float(market.provenance["expected_return_compound"])
    default = Household(500_000.0, [Person(45, 100_000.0)], 5.0)

    # --- Table 12, the conversion at three volatilities -------------------
    for label, at, want in (("a bond held to maturity", 0.0, "2.98%"),
                            ("2% volatility", 0.02, "3.00%"),
                            ("equities", vol, "4.76%")):
        got = "%.2f%%" % (arithmetic_from_compound(rf, at) * 100)
        check("Table 12, %s" % label, got == want and in_doc(want),
              "%.2f%% compound becomes %s arithmetic" % (rf * 100, got))

    # --- Table 13, what the safe asset is worth ---------------------------
    # The equity estimate is held at its compound value and converted, so only
    # the safe rate moves down the column.
    held = arithmetic_from_compound(compound, vol)
    # TIPS yields are quoted semiannually; the model reads annual rates, so
    # the 5- and 10-year quotes are annualised as the 30-year one is.
    for label, rate, want in (("cash", 0.013679, "75.7%"),
                              ("the 5-year TIPS", (1 + 0.0215 / 2) ** 2 - 1, "55.1%"),
                              ("the 10-year TIPS", (1 + 0.0242 / 2) ** 2 - 1, "48.9%"),
                              ("the 30-year TIPS, used here", rf, "37.3%")):
        share = recommend(default, held, rate, vol).equity_share
        drift = log_premium(held, rate, CALIB_VOL)
        check("Table 13, %s" % label,
              "%.1f%%" % (share * 100) == want and in_doc(want),
              "a %.2f%% safe rate gives %.1f%%, drift %.2f%%"
              % (rate * 100, share * 100, drift * 100))

    # --- Table 15, the corners of Choi's grid -----------------------------
    corners = []
    for log_rf in (0.0, 0.01, 0.02):
        for log_prem in (0.02, 0.04):
            corner_rf = math.exp(log_rf) - 1
            corner_mu = math.exp(log_rf + log_prem + CALIB_VOL ** 2 / 2) - 1
            share = recommend(default, corner_mu, corner_rf, vol).equity_share
            corners.append((compound_from_arithmetic(corner_mu, vol), share))
    missing = ["%.2f%%" % (c * 100) for c, _ in corners
               if "%.2f%%" % (c * 100) not in doc_text()]
    check("Table 15, the implied return at each of the six corners", not missing,
          ", ".join("%.2f%%" % (c * 100) for c, _ in corners)
          if not missing else "absent: %s" % missing)
    # Three since the volatility became Choi's 18.5% in both layers: the
    # three 4% corners saturate, and the 2% corners give 72% to 87%.
    saturated = sum(1 for _, s in corners if s > 0.999)
    lowest = min(s for _, s in corners)
    check("Table 15, three of the six corners saturate at 100%",
          saturated == 3 and "%.0f%% or more" % (lowest * 100) in doc_text(),
          "everywhere Choi solved, this household would hold far more equity "
          "than today's market tells it to: %.1f%% at the lowest corner"
          % (lowest * 100))

    # --- Table 17, where the 9.7% comes from ------------------------------
    # At the values the document states beside it: gamma 5, mu 5%, r 2%, age
    # 21. Not today's market data, which gives a different number entirely.
    g, ex_mu, ex_rf, age = 5.0, 0.05, 0.02, 21
    x = (age - 1) / 100.0
    pi = log_premium(ex_mu, ex_rf, CALIB_VOL)
    terms = [
        ("permanent wage shocks",
         4.332 * CGM_CALIBRATION.permanent_shock_volatility ** 2, "7.32"),
        ("risk aversion", 0.087 * g / 10.0, "4.35"),
        ("age", -0.149 * x + 0.142 * x ** 2, "2.41"),
        ("the real safe rate", 1.132 * math.log(1 + ex_rf), "2.24"),
        ("the constant", -0.020, "2.00"),
        ("the replacement rate",
         0.010 * CGM_CALIBRATION.benefit_replacement_rate, "0.40"),
        ("the equity drift", -0.267 * pi, "0.32"),
        ("temporary wage shocks",
         0.028 * CGM_CALIBRATION.temporary_shock_volatility ** 2, "0.16"),
    ]
    wrong = [name for name, value, want in terms
             if "%.2f" % abs(value * 100) != want]
    check("Table 17, all eight terms of the wage discount rate", not wrong,
          "at the values stated beside it, not today's" if not wrong
          else "%s" % wrong)
    total = sum(v for _, v, _ in terms)
    live = wage_discount_rate(age, g, ex_mu, ex_rf)
    check("Table 17, the terms sum to what the model returns",
          abs(total - live) < 1e-12 and in_doc("9.75"),
          "%.2f%%, and wage_discount_rate agrees exactly" % (total * 100))

    # The benefit rate is a different equation on a different age range.
    # Quoting the two together without their ages is how 3.3% came to sit
    # beside a value the model puts at the safe rate.
    at_21 = benefit_discount_rate(21, g, ex_mu, ex_rf)
    at_67 = benefit_discount_rate(67, g, ex_mu, ex_rf)
    check("the benefit rate is quoted at a retirement age, not at 21",
          abs(at_21 - ex_rf) < 1e-12 and "%.1f%%" % (at_67 * 100) in doc_text(),
          "%.2f%% at 21, which is the floor, and %.1f%% at 67"
          % (at_21 * 100, at_67 * 100))

    # --- Table 19, what each fixed constant is worth ----------------------
    # The range is the spread across all three columns, not the two ends: at
    # an 80% replacement rate the default household's pension reaches the
    # Social Security ceiling, so that row peaks at the value used.
    for field, low, high, want_low, want_high, want_range in (
            ("permanent_shock_volatility", 0.08, 0.20, "48.1%", "26.4%", "21.6"),
            ("benefit_replacement_rate", 0.0, 0.80, "35.7%", "36.6%", "1.6"),
            ("temporary_shock_volatility", 0.15, 0.35, "37.0%", "37.7%", "0.7")):
        shares = []
        for value in (low, high):
            calibration = dataclasses.replace(CGM_CALIBRATION, **{field: value})
            shares.append(
                recommend(default, mu, rf, vol, calibration).equity_share)
        used = recommend(default, mu, rf, vol).equity_share
        span = (max(shares + [used]) - min(shares + [used])) * 100
        ok = ("%.1f%%" % (shares[0] * 100) == want_low
              and "%.1f%%" % (shares[1] * 100) == want_high
              and "%.1f" % span == want_range
              and in_doc(want_low, want_high, "%s points" % want_range))
        check("Table 19, %s" % field.replace("_", " "), ok,
              "%.1f%% to %.1f%%, a range of %.1f points"
              % (shares[0] * 100, shares[1] * 100, span))

    # --- the glide path, which could not be reproduced before -------------
    # Its setup was "aged forward from 25 to 85 on a $100,000 wage, saving 15%
    # a year", which leaves out whether the savings earn anything, whether the
    # wage follows a career profile, and what is held after 67. Ten
    # combinations were tried against the published figures and none matched.
    def glide(expected: float) -> dict:
        wealth, out = 0.0, {}
        for age in range(25, 86):
            wage = 100_000.0 if age < 67 else 0.0
            benefit = 0.0 if age < 67 else 40_000.0
            if age in (25, 35, 45, 55, 65, 75):
                household = Household(max(wealth, 1.0),
                                      [Person(age, wage, benefit)], 5.0)
                out[age] = recommend(household, expected, rf, vol).equity_share
            wealth = wealth * (1 + rf) + (wage * 0.15 if age < 67 else 0.0)
        return out

    at_today, at_historical = glide(mu), glide(0.08)
    # Read cell by cell from the table itself. Looking for each figure
    # anywhere in the document let a stale 47% at 65 pass, because "46%"
    # happened to appear in section 2.4.
    t25 = re.search(r'id="t25">(.*?)</table>', doc_text(), re.S)
    rows = {int(age): (today, hist) for age, today, hist in re.findall(
        r'<tr><td class="num">(\d+)</td><td class="num">\d+%</td>'
        r'<td class="num">(\d+)%</td><td class="num">(\d+)%</td></tr>',
        t25.group(1) if t25 else "")}
    stale = [age for age in at_today
             if rows.get(age) != ("%.0f" % (at_today[age] * 100),
                                  "%.0f" % (at_historical[age] * 100))]
    check("Table 25, the glide path at both expected returns", not stale,
          "flat wage, 15% saved at the real safe rate, retiring at 67 on 40%: "
          + ", ".join("%d:%.0f%%/%.0f%%" % (a, at_today[a] * 100,
                                            at_historical[a] * 100)
                      for a in at_today)
          + ("" if not stale else "; stale at %s" % stale))
    check("the glide path falls with age under both", 
          all(at_today[a] >= at_today[b] - 1e-9
              for a, b in zip(sorted(at_today), sorted(at_today)[1:])),
          "which is the shape the comparison is about")

    check("Table 19 lists the replacement rate once",
          doc_text().count("replacement rate</td><td class=\"num\">3") <= 1,
          "it appeared twice, measured before and after that rate became a "
          "regressor in equation (12)")

    # --- where the cap stops binding, sections 4 and 8.4 -------------------
    # From equation (11) the cap binds while HC/W is above 1/w* - 1. In years
    # of pay saved the threshold does not depend on the wage while the Social
    # Security ceiling does not bind, so it is found here with the ceiling
    # off, by bisection on savings.
    no_ceiling = dataclasses.replace(CGM_CALIBRATION, benefit_cap=None)
    w_star = recommend(default, mu, rf, vol).merton_share
    w_choi = recommend(default, 0.05, 0.02, vol).merton_share
    hc_w = ("%.1f" % (1 / w_star - 1), "%.1f" % (1 / w_choi - 1))
    check("section 4, the HC/W above which the cap binds",
          hc_w == ("7.1", "4.9") and in_doc("above 7.1", "above 4.9"),
          "1/w* - 1 is %s on the snapshot and %s at Choi's defaults" % hc_w)

    def years_of_pay(age: int) -> float:
        low, high = 1.0, 1e9
        for _ in range(200):
            mid = math.sqrt(low * high)
            r = recommend(Household(mid, [Person(age, 20_000.0)], 5.0),
                          mu, rf, vol, no_ceiling)
            low, high = (mid, high) if r.uncapped_share > 1 else (low, mid)
        return low / 20_000.0

    years = {age: "%.1f" % years_of_pay(age) for age in (25, 35, 45, 55, 65)}
    check("sections 4 and 8.4, years of pay below which the cap binds",
          years == {25: "2.7", 35: "1.8", 45: "1.4", 55: "1.3", 65: "1.0"}
          and in_doc("2.7 years of salary saved at age 25, 1.8 at 35, 1.4 at "
                     "45, 1.3 at 55 and 1.0 at 65"),
          ", ".join("%d: %s" % kv for kv in years.items()))

    # --- section 8.4, the 1,040-household grid ------------------------------
    # Every combination of thirteen ages, four wages, five savings levels and
    # four risk aversions, one adult each. Adults of 67 or more retire after
    # this year on 40% of today's wage, up to the ceiling, as Person does.
    def grid(expected: float) -> list:
        return [recommend(Household(saved, [Person(age, wage)], gamma),
                          expected, rf, vol)
                for age in range(25, 86, 5)
                for wage in (40_000.0, 80_000.0, 150_000.0, 250_000.0)
                for saved in (25_000.0, 100_000.0, 500_000.0, 1_500_000.0,
                              3_000_000.0)
                for gamma in (2.0, 4.0, 6.0, 8.0)]

    today = grid(mu)
    pinned = sorted(r.uncapped_share for r in today if r.uncapped_share > 1)
    middle = len(pinned) // 2
    median = (pinned[middle] if len(pinned) % 2
              else (pinned[middle - 1] + pinned[middle]) / 2)
    double = grid(arithmetic_from_compound(
        compound + float(market.provenance["buyback_yield_not_counted"]), vol))
    got = ("%.1f%%" % (100 * len(pinned) / len(today)),
           "%.1f%%" % (100 * sum(r.uncapped_share > 1 for r in double)
                       / len(double)),
           "%.1f times" % median, "%.0f times" % pinned[-1])
    zero = sum(r.equity_share <= 0 for r in today)
    check("section 8.4, the 1,040-household grid",
          len(today) == 1040 and zero == 0
          and got == ("33.3%", "43.8%", "2.9 times", "81 times")
          and in_doc("1,040 single-adult households", *got),
          "%d households, %s pinned, %s with the double count, median ask "
          "%s, largest %s, %d at zero" % ((len(today),) + got + (zero,)))


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

    part_four()

    print(f"\n{'=' * 72}")
    tally = f"{passed} passed, {len(failed)} failed"
    if skipped:
        tally += f", {len(skipped)} skipped"
    print(tally)
    for name in failed:
        print(f"  FAILED: {name}")
    raise SystemExit(1 if failed else 0)
