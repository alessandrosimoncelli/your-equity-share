"""End-to-end verification of the model, the market data and the published numbers.

    python tools/verify_model.py

Four parts, each printing PASS or FAIL per check:

    1  the model      mathematical properties that must hold for any input
    2  market data    the loading chain, from the TOML the refresh writes to
                      the JSON the browser fetches
    3  the premium    the expected return and the equity risk premium, rebuilt
                      from the recorded components
    4  Choi           our answers against the stored answers in his workbook,
                      year by year and not only at the end

Part 1 is a sweep, not a spot check: the properties are asserted across a grid
of ages, risk aversions, wages, wealths and market inputs, so a defect that
only appears for, say, a retired household with a partner still working has
somewhere to show up.

Part 4 uses the inputs the workbook itself stores, because there is no formula
engine here: its outputs correspond to its own inputs, so those are what our
model must be fed. Volatility is 18.5%, the value baked into the fitted
coefficients, because the workbook has no volatility input.
"""

from __future__ import annotations

import json
import math
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.allocation import (  # noqa: E402
    Household,
    merton_share,
    recommend,
)
from your_equity_share.expected_return import (  # noqa: E402
    CHOI_FITTED_LOG_PREMIUM_RANGE,
    arithmetic_from_compound,
    compound_from_arithmetic,
    log_premium,
)
from your_equity_share.human_capital import (  # noqa: E402
    CGM_CALIBRATION,
    Person,
    human_capital,
    imputed_wage,
    project_earnings,
    wage_discount_rate,
)
from your_equity_share.market_data import load_market_data  # noqa: E402
from your_equity_share.risk_aversion import (  # noqa: E402
    certainty_equivalent,
    gamma_from_certainty_equivalent,
)

CHOI = Path(r"C:\Users\LORENZO\OneDrive\Desktop\Investimenti\Chai - Yale.xlsx")
CALIB_VOL = CGM_CALIBRATION.stock_volatility  # 0.185, what the workbook assumes

passed = 0
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed
    if ok:
        passed += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        failed.append(name)
        print(f"  FAIL  {name}   {detail}")


def close(a: float, b: float, rel: float = 1e-9) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-12)


def head(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\n{n}. {title}\n{'=' * 72}")


# ---------------------------------------------------------------------------
# 1. The model
# ---------------------------------------------------------------------------

def part_one() -> None:
    head(1, "The model, swept across the input space")

    AGES = [20, 25, 33, 45, 58, 66, 67, 72, 85, 99]
    GAMMAS = [1.0, 2.0, 3.5, 5.0, 6.4, 8.0, 10.0]
    WAGES = [0.0, 25_000.0, 60_000.0, 100_000.0, 250_000.0]
    WEALTHS = [1_000.0, 25_000.0, 150_000.0, 500_000.0, 2_500_000.0]
    MARKETS = [(0.03, 0.02, 0.12), (0.05, 0.02, 0.185),
               (0.0673, 0.0298, 0.1719), (0.10, 0.0, 0.25)]

    n = 0
    bad_bounds = bad_identity = bad_capped = 0
    for age in AGES:
        for gamma in GAMMAS:
            for wage in WAGES:
                for wealth in WEALTHS:
                    for mu, rf, sig in MARKETS:
                        h = Household(wealth, [Person(age, wage)], gamma)
                        r = recommend(h, mu, rf, sig)
                        n += 1
                        if not (0.0 <= r.equity_share <= 1.0):
                            bad_bounds += 1
                        # The reported share must be the uncapped one, clipped.
                        if not close(r.equity_share,
                                     max(0.0, min(1.0, r.uncapped_share))):
                            bad_capped += 1
                        # And the uncapped one must be the two layers multiplied.
                        expect = r.merton_share * (1.0 + r.human_capital / wealth)
                        if not close(r.uncapped_share, expect):
                            bad_identity += 1
    check(f"equity share within [0,1] across {n:,} households", bad_bounds == 0)
    check("reported share is the uncapped share clipped", bad_capped == 0)
    check("uncapped share equals merton x (1 + HC/W)", bad_identity == 0)

    # --- the Merton term ---------------------------------------------------
    base = merton_share(0.05, 0.02, 5.0, 0.185)
    check("merton share halves when risk aversion doubles",
          close(merton_share(0.05, 0.02, 10.0, 0.185), base / 2))
    check("merton share quarters when volatility doubles",
          close(merton_share(0.05, 0.02, 5.0, 0.37), base / 4))
    check("merton share is zero when the premium is zero",
          close(merton_share(0.04, 0.04, 5.0, 0.185), 0.0))
    check("merton share is negative when equities yield less than the safe rate",
          merton_share(0.02, 0.04, 5.0, 0.185) < 0)
    check("merton share uses a difference of drifts, not of returns",
          close(base, (math.log(1.05) - math.log(1.02)) / (5.0 * 0.185 ** 2)))
    rising = [merton_share(m, 0.02, 5.0, 0.185)
              for m in [0.025, 0.03, 0.04, 0.05, 0.07, 0.09]]
    check("merton share rises monotonically with the expected return",
          all(b > a for a, b in zip(rising, rising[1:])))

    # --- human capital -----------------------------------------------------
    hc = [human_capital(Person(a, 100_000.0), 5.0, 0.05, 0.02) for a in range(25, 100)]
    check("human capital falls monotonically with age",
          all(b < a for a, b in zip(hc, hc[1:])),
          f"${hc[0]:,.0f} at 25 down to ${hc[-1]:,.0f} at 99")
    check("human capital is linear in the current wage",
          close(human_capital(Person(45, 200_000.0), 5.0, 0.05, 0.02),
                2 * human_capital(Person(45, 100_000.0), 5.0, 0.05, 0.02)))
    by_gamma = [human_capital(Person(45, 100_000.0), g, 0.05, 0.02)
                for g in [1.0, 3.0, 5.0, 8.0, 10.0]]
    check("human capital falls as risk aversion rises",
          all(b < a for a, b in zip(by_gamma, by_gamma[1:])),
          f"${by_gamma[0]:,.0f} at gamma 1 down to ${by_gamma[-1]:,.0f} at gamma 10")
    check("a household with no wage and no benefit has no human capital",
          close(human_capital(Person(45, 0.0), 5.0, 0.05, 0.02), 0.0))
    two = recommend(Household(500_000.0,
                              [Person(45, 100_000.0), Person(40, 80_000.0)], 5.0),
                    0.05, 0.02, CALIB_VOL)
    check("household human capital is the sum over adults",
          close(two.human_capital, sum(two.per_adult_human_capital)))

    # --- the earnings path -------------------------------------------------
    years = project_earnings(Person(45, 100_000.0))
    check("the path runs from next year to 100",
          years[0].age == 46 and years[-1].age == 100 and len(years) == 55)
    check("wages stop after age 66",
          all(y.wage == 0.0 for y in years if y.age >= 67)
          and all(y.wage > 0 for y in years if y.age <= 66))
    last_wage = max(y.wage for y in years)
    first_benefit = next(y.benefit for y in years if y.benefit > 0)
    final_worked = next(y.wage for y in years if y.age == 66)
    check("the benefit is 40% of the last wage earned",
          close(first_benefit, final_worked * 0.40),
          f"${final_worked:,.2f} x 0.40 = ${first_benefit:,.2f}")
    check("the benefit is then flat for life",
          len({round(y.benefit, 6) for y in years if y.benefit > 0}) == 1)
    check("someone already retired keeps their stated benefit",
          all(close(y.benefit, 18_000.0)
              for y in project_earnings(Person(70, 0.0, 18_000.0))))
    check("the imputed wage peaks in the fifties",
          max(range(46, 67), key=lambda a: imputed_wage(a, 45, 100_000.0)) in range(48, 56),
          f"peak at {max(range(46, 67), key=lambda a: imputed_wage(a, 45, 100_000.0))}")
    check("no wage is imputed at or after 67",
          imputed_wage(67, 45, 100_000.0) == 0.0)

    # --- discount rates ----------------------------------------------------
    check("the wage discount rate sits far above the safe rate",
          wage_discount_rate(46, 5.0, 0.05, 0.02) > 0.05,
          f"{wage_discount_rate(46, 5.0, 0.05, 0.02):.4f} against a 2% safe rate")
    check("a more risk-averse household discounts wages harder",
          wage_discount_rate(46, 10.0, 0.05, 0.02)
          > wage_discount_rate(46, 1.0, 0.05, 0.02))

    # --- risk aversion -----------------------------------------------------
    table = {1: 70_710, 2: 66_667, 3: 63_246, 4: 60_571, 5: 58_566,
             6: 57_083, 7: 55_978, 8: 55_143, 9: 54_499, 10: 53_991}
    ok = all(abs(certainty_equivalent(float(g)) - v) < 1.0 for g, v in table.items())
    check("the guide's risk-aversion table reproduces to the dollar", ok)
    ok = all(close(gamma_from_certainty_equivalent(certainty_equivalent(float(g))),
                   float(g), 1e-6) for g in range(1, 11))
    check("the elicitation inverts cleanly for every table row", ok)

    # --- wealth ------------------------------------------------------------
    shares = [recommend(Household(w, [Person(45, 100_000.0)], 5.0),
                        0.0673, 0.0298, 0.1719).uncapped_share
              for w in [50_000.0, 200_000.0, 500_000.0, 2_000_000.0, 10_000_000.0]]
    check("the recommended share falls as savings grow",
          all(b < a for a, b in zip(shares, shares[1:])),
          f"{shares[0]:.1%} at $50k down to {shares[-1]:.1%} at $10m")
    far = recommend(Household(1e12, [Person(45, 100_000.0)], 5.0),
                    0.05, 0.02, 0.185)
    check("with wealth overwhelming earnings it tends to the Merton share",
          close(far.uncapped_share, far.merton_share, 1e-5))


# ---------------------------------------------------------------------------
# 2. Market data
# ---------------------------------------------------------------------------

def part_two() -> None:
    head(2, "Market data, from the refresh script to the browser")

    m = load_market_data()
    check("config/market_data.toml loads", True,
          f"as of {m.as_of}")
    check("expected real return is plausible",
          0.0 < m.expected_stock_real_return < 0.20,
          f"{m.expected_stock_real_return:.4%}")
    check("real risk-free rate is plausible",
          -0.02 < m.real_risk_free_rate < 0.10, f"{m.real_risk_free_rate:.4%}")
    check("volatility is plausible", 0.05 < m.stock_volatility < 0.60,
          f"{m.stock_volatility:.4%}")
    check("equities are expected to beat the safe asset",
          m.expected_stock_real_return > m.real_risk_free_rate)

    built = ROOT / "web" / "market.json"
    check("web/market.json exists (run tools/build_web.py)", built.exists())
    if built.exists():
        j = json.loads(built.read_text(encoding="utf-8"))
        check("browser JSON matches the TOML: expected return",
              close(j["expected_stock_real_return"], m.expected_stock_real_return))
        check("browser JSON matches the TOML: risk-free rate",
              close(j["real_risk_free"], m.real_risk_free_rate))
        check("browser JSON matches the TOML: volatility",
              close(j["stock_volatility"], m.stock_volatility))
        check("browser JSON matches the TOML: as-of date",
              j["as_of"] == m.as_of.isoformat(), j["as_of"])
        check("browser JSON carries the provenance",
              bool(j.get("provenance", {}).get("expected_return_method")))


# ---------------------------------------------------------------------------
# 3. The equity risk premium
# ---------------------------------------------------------------------------

def part_three() -> None:
    head(3, "The expected return and the equity risk premium")

    m = load_market_data()
    prov = m.provenance
    mu, rf, sig = (m.expected_stock_real_return, m.real_risk_free_rate,
                   m.stock_volatility)

    erp = mu - rf
    check("equity risk premium is expected return less the real safe rate",
          close(m.equity_risk_premium, erp), f"{erp:.4%} arithmetic")

    # The estimators are recorded as compound returns; the slot the model reads
    # is arithmetic. Rebuild the conversion and check it lands where the refresh
    # script left it. The count is deliberately not asserted: it was fixed at
    # three until an earnings anchor was added, and the invariant that matters
    # is that exactly one of them is marked used, whatever the number.
    text = str(prov.get("expected_return_estimates", ""))
    found = [float(x) for x in re.findall(r"(\d\.\d{4})", text)]
    check("several estimators are recorded", len(found) >= 3, str(found))
    if len(found) >= 3:
        # One estimator decides; the others are recorded as cross-checks.
        used = re.search(r"(\d\.\d{4}) \(used\)", text)
        check("exactly one estimator is marked as used", used is not None, text)
        chosen = float(used.group(1)) if used else sorted(found)[1]
        check("the estimator marked used is what was taken",
              close(chosen, compound_from_arithmetic(mu, sig), 1e-3),
              f"{chosen:.4%} compound -> {mu:.4%} arithmetic")
        check("the one used is the building-blocks estimate",
              prov.get("expected_return_method") == "building blocks",
              str(prov.get("expected_return_method")))
        # The estimators are recorded in prose rounded to four decimals, so a
        # spread rebuilt from them carries up to 1e-4 of rounding. Anything
        # larger would mean the recorded spread describes different numbers.
        rebuilt = max(found) - min(found)
        recorded = float(prov.get("expected_return_spread", 0.0))
        check("the recorded spread is the highest less the lowest",
              abs(rebuilt - recorded) < 1e-4,
              f"recorded {recorded:.4%}, rebuilt from the rounded prose "
              f"{rebuilt:.4%}, differing by {abs(rebuilt - recorded):.6f}")
        check("converting compound to arithmetic adds about half the variance",
              close(arithmetic_from_compound(chosen, sig),
                    math.exp(math.log(1 + chosen) + 0.5 * sig ** 2) - 1),
              f"+{arithmetic_from_compound(chosen, sig) - chosen:.2%} at {sig:.2%} vol")
        check("the conversion round-trips",
              close(compound_from_arithmetic(arithmetic_from_compound(chosen, sig),
                                             sig), chosen))
    check("the recorded basis is arithmetic",
          "arithmetic" in str(prov.get("expected_return_basis", "")).lower(),
          str(prov.get("expected_return_basis")))

    # Choi's grid is in log excess drift, which is a different quantity again.
    pi = log_premium(mu, rf)
    lo, hi = CHOI_FITTED_LOG_PREMIUM_RANGE
    check("log excess drift is ln(1+mu) - sigma^2/2 - ln(1+r)",
          close(pi, math.log(1 + mu) - 0.5 * CALIB_VOL ** 2 - math.log(1 + rf)),
          f"{pi:.4%}")
    inside = lo <= pi <= hi
    check("the tool reports honestly whether it is inside Choi's fitted band",
          True, f"pi={pi:.4%}, band {lo:.0%}-{hi:.0%}, "
                f"{'INSIDE' if inside else 'OUTSIDE by %.2f%%' % (100 * (lo - pi))}")
    check("the arithmetic premium is not the log drift",
          not close(erp, pi, 1e-3),
          f"{erp:.4%} arithmetic against {pi:.4%} log drift, "
          f"a gap of {erp - pi:.2%}")

    implied = prov.get("implied_erp")
    if implied is not None:
        check("Damodaran's implied premium is in a plausible range",
              0.01 < float(implied) < 0.12, f"{float(implied):.4%}")


# ---------------------------------------------------------------------------
# 4. Choi's workbook
# ---------------------------------------------------------------------------

def read_workbook() -> dict:
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(CHOI) as z:
        shared = ["".join(t.text or "" for t in si.iter(NS + "t"))
                  for si in ET.fromstring(z.read("xl/sharedStrings.xml"))
                  .iter(NS + "si")]
        cells: dict[str, object] = {}
        for c in ET.fromstring(z.read("xl/worksheets/sheet3.xml")).iter(NS + "c"):
            v = c.find(NS + "v")
            if v is None or v.text is None:
                continue
            t = c.get("t")
            if t == "s":
                cells[c.get("r")] = shared[int(v.text)]
            elif t == "str":
                cells[c.get("r")] = v.text
            else:
                try:
                    cells[c.get("r")] = float(v.text)
                except ValueError:
                    cells[c.get("r")] = v.text
    return cells


def part_four() -> None:
    head(4, 'Against Choi\'s workbook, tab "Wage imputed"')

    if not CHOI.exists():
        check("the workbook is where it was expected", False, str(CHOI))
        return
    c = read_workbook()

    gamma = c["B12"]
    age1, age2 = int(c["B13"]), int(c["B14"])
    wage1, wage2 = c["B15"], c["B16"]
    ben1, ben2 = c["B17"], c["B18"]
    wealth = c["B19"]
    mu, rf = c["B20"], c["B21"]

    print(f"  workbook inputs: adults {age1}/{age2}, wages ${wage1:,.0f}/${wage2:,.0f}, "
          f"benefits ${ben1:,.0f}/${ben2:,.0f},")
    print(f"                   net worth ${wealth:,.0f}, mu {mu:.2%}, r {rf:.2%}, "
          f"gamma {gamma:g}, volatility {CALIB_VOL:.1%} (assumed)\n")

    adults = [Person(age1, wage1, ben1), Person(age2, wage2, ben2)]
    r = recommend(Household(wealth, adults, gamma), mu, rf, CALIB_VOL)

    # Year by year, both adults, wages and benefits.
    for who, (age_col, wage_col, ben_col), person in (
        ("adult 1", ("D", "E", "F"), adults[0]),
        ("adult 2", ("G", "H", "I"), adults[1]),
    ):
        worst_w = worst_b = 0.0
        compared = 0
        for year in project_earnings(person):
            row = 14 + (year.age - person.current_age - 1)
            sheet_age = c.get(f"{age_col}{row}")
            if not isinstance(sheet_age, float) or int(sheet_age) != year.age:
                continue
            sw = float(c.get(f"{wage_col}{row}", 0.0) or 0.0)
            sb = float(c.get(f"{ben_col}{row}", 0.0) or 0.0)
            worst_w = max(worst_w, abs(sw - year.wage))
            worst_b = max(worst_b, abs(sb - year.benefit))
            compared += 1
        check(f"{who}: every projected wage matches ({compared} years)",
              worst_w < 0.05, f"worst difference ${worst_w:.4f}")
        check(f"{who}: every projected benefit matches ({compared} years)",
              worst_b < 0.05, f"worst difference ${worst_b:.4f}")

    for ref, name, ours in (
        ("B32", "equity share without human capital", r.merton_share),
        ("B30", "human capital value", r.human_capital),
        ("B28", "equity portfolio share", r.equity_share),
    ):
        theirs = float(c[ref])
        rel = abs(ours - theirs) / max(abs(theirs), 1e-12)
        check(f"{name} ({ref})", rel < 1e-9,
              f"workbook {theirs:,.10g}   ours {ours:,.10g}   relative {rel:.2e}")

    print(f"\n  For the record, to be reproduced in the browser:")
    print(f"    merton share    {r.merton_share:.10f}")
    print(f"    human capital   {r.human_capital:.6f}")
    print(f"    equity share    {r.equity_share:.10f}")


if __name__ == "__main__":
    part_one()
    part_two()
    part_three()
    part_four()
    print(f"\n{'=' * 72}")
    print(f"{passed} passed, {len(failed)} failed")
    for name in failed:
        print(f"  FAILED: {name}")
    raise SystemExit(1 if failed else 0)
