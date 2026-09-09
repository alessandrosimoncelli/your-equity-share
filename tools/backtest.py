"""Would this estimator have made a good allocation rule? Probably not, and why.

    python tools/backtest.py
    python tools/backtest.py --gamma 5 --lag 3

The model says what share of wealth belongs in equities given a household's risk
aversion and today's prices. A natural curiosity follows: if you had recomputed
that share every year since 1901 and traded it, would you have beaten 60/40?

This answers it, and the answer needs three warnings before any number.

FIRST, THE MODEL DOES NOT CLAIM THIS. Merton's share maximises expected
UTILITY for a stated risk aversion. It does not claim to maximise return, or
Sharpe ratio, or anything a performance table ranks. A hundred per cent
equities will usually win on return over a long sample and often on Sharpe,
and that refutes nothing, because a household at risk aversion 5 does not want
the portfolio that maximises return. So the metric that matters here is the
CERTAINTY EQUIVALENT at the same risk aversion, which is what the model
actually optimises. It is reported beside the others, and the others are
reported because they are what everyone looks at first.

SECOND, A GOOD RESULT WOULD BE WEAK EVIDENCE. There are about three
independent thirty-year periods in this history. Nothing measured on it
separates two allocation rules that are close, and this file prints the
independent-period count beside the results so that is hard to forget.

THIRD, THE HONEST CONTROL IS NOT 60/40. It is the strategy's OWN AVERAGE
WEIGHT held constant. If dynamic weights and their own long-run average
perform the same, the timing added nothing and only the level ever mattered.
That control is the one that decides whether there is anything here, and it is
the one a flattering backtest would leave out.

HOW LOOK-AHEAD IS KEPT OUT

  Every input at date t is computed from data dated t or earlier, and
  fundamentals are lagged a further three months by default, because Shiller's
  earnings and dividends are not knowable on the last day of the month they
  describe. --lag changes it and the robustness grid varies it.

  The growth trend uses a trailing window of up to a hundred years and at
  least thirty, which is the rule the methodology's own Table 7 uses. So the
  backtest starts in 1901, thirty years after the data does.

  Volatility is the trailing five years of monthly real total returns. The
  inflation expectation deflating the bond yield is trailing ten-year realised
  inflation. Both are backward looking on purpose.

  Risk aversion is fixed at 5, the methodology's default household. It is not
  fitted, and the robustness grid varies it to show the conclusion does not
  depend on it.

  NOTHING IS TUNED ON THE RESULT. No window, no threshold and no rebalancing
  interval was chosen by looking at what it produced. The one place this
  claim is weak is the hundred-year growth window, which the methodology
  chose partly from a sensitivity analysis on this same series, so the grid
  reports fifty and seventy-five as well.

IN SAMPLE AND OUT OF SAMPLE. 1901 to 1970 and 1971 to 2026. The split is by
date rather than at random, because a random split would let the rule learn
from its own future through overlapping windows.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.allocation import merton_share  # noqa: E402
from your_equity_share.expected_return import (  # noqa: E402
    arithmetic_from_compound,
)
from your_equity_share.providers import read_xls_sheet  # noqa: E402

WORKBOOK = ROOT / "data" / "shiller.xls"

# Shiller's sheet, header row 7: Date, P, D, E, CPI, Fraction, Rate GS10.
COLUMNS = {"date": 0, "price": 1, "dividend": 2, "earnings": 3, "cpi": 4,
           "rate": 6}

GROWTH_MAX_YEARS, GROWTH_MIN_YEARS = 100, 30
VOL_MONTHS, INFLATION_MONTHS = 60, 120
BOND_MATURITY = 10.0
SPLIT_YEAR = 1971
DEFAULT_GAMMA, DEFAULT_LAG = 5.0, 3


def load():
    """Shiller's monthly series: real price, real dividend, real earnings,
    the price index and the long nominal rate."""
    cells = read_xls_sheet(WORKBOOK.read_bytes(), "Data")

    def value(row, col):
        v = cells.get((row, col))
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", "").strip())
            except ValueError:
                return None
        return None

    rows = []
    for row in sorted({r for r, _ in cells if r > 7}):
        got = {k: value(row, c) for k, c in COLUMNS.items()}
        if any(got[k] is None for k in ("date", "price", "dividend", "cpi")):
            continue
        year = int(got["date"])
        month = int(round((got["date"] - year) * 100))
        if not 1 <= month <= 12:
            continue
        rows.append({
            "ym": year * 12 + (month - 1),
            "label": "%d-%02d" % (year, month),
            "price": got["price"], "dividend": got["dividend"],
            "earnings": got["earnings"], "cpi": got["cpi"],
            "rate": got["rate"],
        })
    rows.sort(key=lambda r: r["ym"])
    base = rows[-1]["cpi"]
    for r in rows:
        r["real_price"] = r["price"] * base / r["cpi"]
        r["real_dividend"] = r["dividend"] * base / r["cpi"]
        r["real_earnings"] = (r["earnings"] * base / r["cpi"]
                              if r["earnings"] is not None else None)
    return rows


def monthly_returns(rows):
    """Real total return on equities and on a ten-year bond, month by month.

    The bond is a constant-maturity par bond, priced the standard way: it earns
    a twelfth of last month's yield and gains the change in yield times its
    modified duration. Deflated by realised inflation, because that is what a
    holder actually kept.
    """
    for a, b in zip(rows, rows[1:]):
        equity = ((b["real_price"] + b["real_dividend"] / 12.0)
                  / a["real_price"]) - 1.0
        bond = None
        if a["rate"] is not None and b["rate"] is not None:
            y0, y1 = a["rate"] / 100.0, b["rate"] / 100.0
            duration = ((1.0 - (1.0 + y0) ** -BOND_MATURITY) / y0
                        if y0 > 0 else BOND_MATURITY)
            nominal = y0 / 12.0 + duration * (y0 - y1)
            bond = (1.0 + nominal) / (b["cpi"] / a["cpi"]) - 1.0
        b["equity_return"], b["bond_return"] = equity, bond
    return rows[1:]


def trend(values):
    """OLS slope of the log series, as an annual rate. The model's estimator."""
    usable = [v for v in values if v is not None and v > 0]
    if len(usable) < 24:
        return None
    ys = [math.log(v) for v in usable]
    n = len(ys)
    mx, my = (n - 1) / 2.0, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in enumerate(ys))
    den = sum((x - mx) ** 2 for x in range(n))
    return math.exp(12.0 * num / den) - 1.0


def signal(rows, index, gamma, lag, growth_years):
    """The equity share the model would have recommended at `index`.

    Everything here reads rows[:index - lag + 1] and nothing later. The lag is
    what makes it honest: Shiller's dividend and earnings for a month are not
    on anybody's desk on the last day of that month.
    """
    known = index - lag
    if known < GROWTH_MIN_YEARS * 12:
        return None
    at = rows[known]
    if at["real_price"] <= 0 or at["real_dividend"] <= 0:
        return None

    window = min(growth_years * 12, known + 1)
    growth = trend([r["real_earnings"] for r in rows[known - window + 1:known + 1]])
    if growth is None:
        return None
    yield_ = at["real_dividend"] / at["real_price"]

    history = [r["equity_return"] for r in rows[max(0, index - VOL_MONTHS):index]
               if r.get("equity_return") is not None]
    if len(history) < 24:
        return None
    mean = sum(history) / len(history)
    variance = sum((x - mean) ** 2 for x in history) / (len(history) - 1)
    sigma = math.sqrt(variance * 12.0)
    if sigma <= 0:
        return None

    span = rows[max(0, index - INFLATION_MONTHS):index + 1]
    if len(span) < 24 or rows[index]["rate"] is None:
        return None
    inflation = (span[-1]["cpi"] / span[0]["cpi"]) ** (12.0 / (len(span) - 1)) - 1.0
    safe = (1.0 + rows[index]["rate"] / 100.0) / (1.0 + inflation) - 1.0

    compound = yield_ + growth
    if compound <= -1.0 or safe <= -1.0:
        return None
    return compound, safe, sigma


def share(rows, index, gamma, lag, growth_years, freeze=None, running=None):
    """The weight, optionally with one half of the signal held constant.

    Two documented effects could produce a good result here and they are not
    the same claim. Valuation timing is Campbell and Shiller: a high dividend
    yield predicts higher subsequent returns. Volatility timing is Moreira and
    Muir (2017): scaling exposure by one over recent variance earns a large
    premium on its own. This rule contains both, so a headline number says
    nothing about which one is working.

    freeze="vol" holds sigma at its own EXPANDING average, leaving valuation to
    move alone. freeze="drift" holds the drift at its expanding average,
    leaving volatility to move alone. Expanding rather than full-sample,
    because a full-sample average is a number from the future.
    """
    got = signal(rows, index, gamma, lag, growth_years)
    if got is None:
        return None
    compound, safe, sigma = got
    if freeze is None:
        mu = arithmetic_from_compound(compound, sigma)
        return max(0.0, min(1.0, merton_share(mu, safe, gamma, sigma)))
    running.append((compound, safe, sigma))
    mean_drift = sum(c for c, _, _ in running) / len(running)
    mean_safe = sum(s for _, s, _ in running) / len(running)
    mean_sigma = sum(v for _, _, v in running) / len(running)
    if freeze == "vol":
        mu = arithmetic_from_compound(compound, mean_sigma)
        return max(0.0, min(1.0, merton_share(mu, safe, gamma, mean_sigma)))
    mu = arithmetic_from_compound(mean_drift, sigma)
    return max(0.0, min(1.0, merton_share(mu, mean_safe, gamma, sigma)))


def simulate(rows, weight_at, every, start=0, stop=None):
    """Hold a target weight, let it drift, reset it every `every` months.

    `start` and `stop` bound the TRADING, not the data. The signal keeps the
    whole of `rows` to look back over, because a rule trading in 1971 is
    entitled to every observation before 1971. Slicing the rows instead, which
    this file did first, both starved the estimator and made it re-serve its
    own thirty-year warm-up inside the slice.
    """
    wealth, path, weights = 1.0, [], []
    equity = bond = None
    target = None
    stop = len(rows) if stop is None else stop
    for i, row in enumerate(rows):
        if i < start or i >= stop:
            continue
        if row.get("equity_return") is None or row.get("bond_return") is None:
            continue
        if target is None or i % every == 0:
            # DECIDED ON DATA THROUGH i-1, THEN EARNS MONTH i's RETURN. Asking
            # for the weight at i and then applying rows[i]'s return would set
            # the allocation using a month that has already happened, which is
            # a one-month look-ahead and was in the first version of this file.
            # It was worth about a point and a half a year of imaginary skill.
            proposed = weight_at(i - 1) if i >= 1 else None
            # A missing signal holds the previous weight. Skipping the month
            # instead would quietly take the strategy out of the market, which
            # is neither a real option nor a neutral one.
            if proposed is not None:
                target = proposed
            if target is None:
                continue
            equity, bond = wealth * target, wealth * (1.0 - target)
        weights.append(target)
        equity *= 1.0 + row["equity_return"]
        bond *= 1.0 + row["bond_return"]
        wealth = equity + bond
        path.append((row["ym"], wealth))
    return path, weights


def metrics(path, gamma, bond_path=None):
    if len(path) < 24:
        return None
    months = len(path) - 1
    total = path[-1][1] / path[0][1]
    annual = total ** (12.0 / months) - 1.0
    rets = [path[k][1] / path[k - 1][1] - 1.0 for k in range(1, len(path))]
    mean = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) * 12.0)
    peak, drawdown = path[0][1], 0.0
    for _, w in path:
        peak = max(peak, w)
        drawdown = min(drawdown, w / peak - 1.0)
    yearly = [path[k][1] / path[k - 12][1] - 1.0
              for k in range(12, len(path), 12)]
    ce = None
    if yearly and all(1 + r > 0 for r in yearly):
        utility = sum((1 + r) ** (1 - gamma) for r in yearly) / len(yearly)
        ce = utility ** (1 / (1 - gamma)) - 1.0
    excess = None
    if bond_path is not None and len(bond_path) == len(path):
        bond_annual = ((bond_path[-1][1] / bond_path[0][1])
                       ** (12.0 / months) - 1.0)
        excess = (annual - bond_annual) / vol if vol > 0 else None
    return {"annual": annual, "vol": vol, "drawdown": drawdown,
            "sharpe": excess, "ce": ce, "years": months / 12.0}


def bounds(rows, first_year, last_year):
    """Index bounds for a calendar window, so trading can be limited to it
    without hiding earlier data from the estimator."""
    start = next((i for i, r in enumerate(rows)
                  if r["ym"] >= first_year * 12), len(rows))
    stop = next((i for i, r in enumerate(rows)
                 if r["ym"] >= (last_year + 1) * 12), len(rows))
    return start, stop


def first_tradable(rows, gamma, lag, growth_years, after=0):
    """The first month the model can say anything, at or after `after`."""
    for i in range(after, len(rows)):
        if signal(rows, i, gamma, lag, growth_years) is not None:
            return i
    return None


def report(title, rows, gamma, lag, growth_years, every, start=0, stop=None):
    dyn = lambda i: share(rows, i, gamma, lag, growth_years)  # noqa: E731

    # EVERY STRATEGY MUST RUN OVER THE SAME MONTHS. The model needs thirty
    # years of history before it can say anything, so it starts around 1901
    # while a fixed weight could start in 1871. Scoring them over different
    # samples would credit or blame the model for decades it never traded, and
    # the first version of this file did exactly that.
    speaks = first_tradable(rows, gamma, lag, growth_years, start)
    if speaks is None:
        return None
    begin = speaks + 1

    path, weights = simulate(rows, dyn, every, begin, stop)
    if not weights:
        return None
    average = sum(weights) / len(weights)
    runs = {
        "model, dynamic": (path, weights),
        "its own average, fixed": simulate(rows, lambda i: average, every, begin, stop),
        "60/40": simulate(rows, lambda i: 0.60, every, begin, stop),
        "100% equities": simulate(rows, lambda i: 1.0, every, begin, stop),
        "100% bonds": simulate(rows, lambda i: 0.0, every, begin, stop),
    }
    bond_path = runs["100% bonds"][0]
    print("\n%s" % title)
    print("  %-24s %8s %8s %9s %7s %8s"
          % ("", "real", "vol", "max draw", "Sharpe", "CE at %g" % gamma))
    out = {}
    for name, (p, _) in runs.items():
        m = metrics(p, gamma, bond_path)
        if m is None:
            continue
        out[name] = m
        print("  %-24s %7.2f%% %7.2f%% %8.1f%% %7s %7.2f%%"
              % (name, m["annual"] * 100, m["vol"] * 100, m["drawdown"] * 100,
                 "%.2f" % m["sharpe"] if m["sharpe"] is not None else "-",
                 m["ce"] * 100 if m["ce"] is not None else float("nan")))
    years = out["model, dynamic"]["years"]
    moves = [abs(b - a) for a, b in zip(weights, weights[1:]) if b != a]
    turnover = sum(moves) / years if years else 0.0
    print("  %.0f years, %.1f independent 30-year periods, average weight %.1f%%"
          % (years, years / 30.0, average * 100))
    print("  weight ranged %.0f%% to %.0f%%, turnover %.1f%% of the portfolio "
          "a year, charged at zero"
          % (min(weights) * 100, max(weights) * 100, turnover * 100))
    return out, average, weights


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gamma", type=float, default=DEFAULT_GAMMA)
    parser.add_argument("--lag", type=int, default=DEFAULT_LAG)
    parser.add_argument("--growth-years", type=int, default=GROWTH_MAX_YEARS)
    args = parser.parse_args(argv[1:])

    if not WORKBOOK.exists():
        print("Shiller's workbook is not at %s. Run update.py first."
              % WORKBOOK.relative_to(ROOT))
        return 0

    rows = monthly_returns(load())
    usable = [r for r in rows if r.get("bond_return") is not None]
    print("Backtesting the model as an allocation rule")
    print("=" * 74)
    print("  %d months, %s to %s, risk aversion %g, %d month reporting lag"
          % (len(usable), usable[0]["label"], usable[-1]["label"],
             args.gamma, args.lag))
    print("  The certainty equivalent is the column the model optimises. The")
    print("  others are the columns everyone reads first.")

    print("\n\nREBALANCING INTERVAL, full sample")
    print("=" * 74)
    averages = {}
    for every, label in ((3, "quarterly"), (12, "yearly"), (24, "every 2 years"),
                         (36, "every 3 years"), (60, "every 5 years")):
        got = report("%s" % label, usable, args.gamma, args.lag,
                     args.growth_years, every)
        if got:
            averages[label] = got[1]

    print("\n\nIN SAMPLE AND OUT OF SAMPLE, rebalanced yearly")
    print("=" * 74)
    a, b = bounds(usable, 1901, SPLIT_YEAR - 1)
    report("1901 to %d" % (SPLIT_YEAR - 1), usable, args.gamma, args.lag,
           args.growth_years, 12, a, b)
    c, d = bounds(usable, SPLIT_YEAR, 2026)
    report("%d to 2026, out of sample" % SPLIT_YEAR, usable, args.gamma,
           args.lag, args.growth_years, 12, c, d)

    print("\n\nWHICH HALF OF THE SIGNAL IS DOING THE WORK")
    print("=" * 74)
    print("  Valuation timing and volatility timing are different claims, and")
    print("  the rule contains both. Freezing one at its expanding average")
    print("  leaves the other working alone.")
    print("  %-36s %8s %9s %8s"
          % ("", "real", "CE at %g" % args.gamma, "avg wt"))
    begin = first_tradable(usable, args.gamma, args.lag, args.growth_years)
    for label, freeze in (("both, the rule as it stands", None),
                          ("valuation only, volatility frozen", "vol"),
                          ("volatility only, valuation frozen", "drift")):
        running = []
        fn = (lambda i, f=freeze, r=running:
              share(usable, i, args.gamma, args.lag, args.growth_years, f, r))
        path, weights = simulate(usable, fn, 12, begin + 1)
        m = metrics(path, args.gamma)
        if m:
            print("  %-36s %7.2f%% %8.2f%% %7.1f%%"
                  % (label, m["annual"] * 100, m["ce"] * 100,
                     sum(weights) / len(weights) * 100))

    print("\n\nROBUSTNESS, yearly, full sample")
    print("=" * 74)
    print("  %-34s %9s %9s %9s"
          % ("", "model CE", "60/40 CE", "avg weight"))
    for label, gamma, lag, years in (
            ("risk aversion 3", 3.0, args.lag, args.growth_years),
            ("risk aversion 5", 5.0, args.lag, args.growth_years),
            ("risk aversion 7", 7.0, args.lag, args.growth_years),
            ("growth window 50 years", args.gamma, args.lag, 50),
            ("growth window 75 years", args.gamma, args.lag, 75),
            ("growth window 100 years", args.gamma, args.lag, 100),
            ("no reporting lag", args.gamma, 0, args.growth_years),
            ("six month reporting lag", args.gamma, 6, args.growth_years)):
        dyn = lambda i, g=gamma, l=lag, y=years: share(usable, i, g, l, y)  # noqa: E731
        begin = first_tradable(usable, gamma, lag, years)
        if begin is None:
            continue
        path, weights = simulate(usable, dyn, 12, begin)
        fixed, _ = simulate(usable, lambda i: 0.60, 12, begin)
        m, f = metrics(path, gamma), metrics(fixed, gamma)
        if not m or not f:
            continue
        print("  %-34s %8.2f%% %8.2f%% %8.1f%%"
              % (label, m["ce"] * 100, f["ce"] * 100,
                 sum(weights) / len(weights) * 100))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
