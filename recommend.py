#!/usr/bin/env python3
"""Print an equity allocation recommendation.

    python recommend.py                                  # asks you the questions
    python recommend.py --age 45 --wage 100000 \
                        --wealth 500000 --risk-aversion 5
    python recommend.py --age 45 --wage 100000 --wealth 500000 --glide

Market data comes from config/market_data.toml. Run `python update.py` first if
it is stale; this script says so if it is.

See docs/inputs.md for what each figure means. The short version: wages are
after tax and in today's money, and wealth excludes housing and is net of tax
owed on withdrawal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from your_equity_share.allocation import Household, recommend  # noqa: E402
from your_equity_share.human_capital import Person  # noqa: E402
from your_equity_share.market_data import load_market_data  # noqa: E402
from your_equity_share.risk_aversion import (  # noqa: E402
    gamma_from_certainty_equivalent,
    guide_table,
)

RULE = "=" * 64
THIN = "-" * 64


def ask_risk_aversion() -> float:
    """Choi's elicitation question, asked directly."""
    print()
    print("  A coin is flipped. Heads, you live on $100,000 for the next year.")
    print("  Tails, you live on $50,000. You must spend it all and cannot borrow.")
    print()
    print("  Someone offers to cancel the gamble and hand you a guaranteed")
    print("  amount instead. What amount would leave you exactly indifferent?")
    print()
    for gamma, amount in sorted(guide_table().items()):
        print(f"     ${amount:>7,.0f}   would mean risk aversion {gamma}")
    print()
    while True:
        raw = input("  Your amount (or a risk aversion number 1 to 10): ").strip()
        raw = raw.replace("$", "").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            print("  Enter a number.")
            continue
        if 1.0 <= value <= 10.0:
            return value
        try:
            return gamma_from_certainty_equivalent(value)
        except ValueError as exc:
            print(f"  {exc}")


def ask(prompt: str, cast=float, minimum=None):
    while True:
        raw = input(f"  {prompt}: ").strip().replace("$", "").replace(",", "")
        try:
            value = cast(raw)
        except ValueError:
            print("  Enter a number.")
            continue
        if minimum is not None and value < minimum:
            print(f"  Must be at least {minimum}.")
            continue
        return value


def money(x: float) -> str:
    return f"${x:,.0f}"


def print_report(result, market, household) -> None:
    share = result.equity_share
    print()
    print(RULE)
    print("  Equity allocation recommendation")
    print(RULE)
    print()
    print(f"  Hold {share:.0%} of your portfolio in equities,")
    print(f"  which is {money(result.equity_dollars())} of "
          f"{money(result.financial_wealth)}.")
    if result.bond_share > 0.005:
        print(f"  The remaining {result.bond_share:.0%} goes in the safe asset.")
    print()

    print(THIN)
    print("  How this was reached")
    print()
    total = result.financial_wealth + result.human_capital
    print(f"  Your total wealth                {money(total):>14}")
    print(f"    investable today               {money(result.financial_wealth):>14}"
          f"   {result.financial_wealth / total:>5.0%}")
    print(f"    future earnings                {money(result.human_capital):>14}"
          f"   {result.human_capital / total:>5.0%}")
    if len(result.per_adult_human_capital) > 1:
        for i, value in enumerate(result.per_adult_human_capital, start=1):
            print(f"      adult {i}                     {money(value):>14}")
    print()
    print(f"  Equity share of TOTAL wealth     {result.your_equity_share:>13.1%}"
          f"   Merton (1969)")
    print(f"  Times (1 + {result.human_capital_ratio:.2f}) for the part you can trade"
          f"  {result.uncapped_share:>8.1%}")
    if result.is_capped:
        print(f"  Capped, no leverage              {share:>13.1%}")
    print()

    if result.is_capped:
        print("  The model wants more than 100%, meaning it would borrow to")
        print("  invest. The cap is imposed from outside; the model did not")
        print("  produce it. See docs/methodology.html section 4.")
        print()

    print(THIN)
    print(f"  Market data, as of {market.as_of}")
    print()
    method = market.provenance.get("expected_return_method", "set by hand")
    note = {"consensus": "median of three estimators",
            "implied": "market implied premium",
            "fixed": "set by hand"}.get(method, method)
    print(f"  expected stock real return       "
          f"{market.expected_stock_real_return:>13.2%}   {note}")
    if market.expected_return_spread > 0:
        print(f"      estimators: {market.expected_return_estimates}")
        print(f"      they span {market.expected_return_spread:.2%}, which is the")
        print(f"      least certain input here. See docs/inputs.md.")
    print(f"  real risk-free rate              "
          f"{market.real_risk_free_rate:>13.2%}   30-year TIPS")
    window = market.provenance.get("volatility_window_years")
    span = f"{window} years" if window else "history"
    adjusted = market.provenance.get("volatility_dividend_adjusted", True)
    print(f"  stock volatility                 "
          f"{market.stock_volatility:>13.2%}   {market.market_ticker}, {span}"
          + ("" if adjusted else ", unadjusted"))
    print(f"  risk aversion                    "
          f"{household.risk_aversion:>13.1f}   your answer")
    print()
    for warning in market.stale_fields():
        print(f"  STALE: {warning}")
    if market.stale_fields():
        print("  Run: python update.py")
        print()


def print_glide(household, market) -> None:
    print()
    print(THIN)
    print("  Glide path, holding wealth and salary fixed")
    print()
    print("   age    equity    human capital    HC / wealth")
    base = household.adults[0]
    for age in range(max(25, base.current_age - 20), 91, 5):
        try:
            trial = Household(
                investable_net_worth=household.investable_net_worth,
                adults=[Person(age, base.current_wage, base.current_benefit)],
                risk_aversion=household.risk_aversion,
            )
        except ValueError:
            continue
        r = recommend(
            trial,
            market.expected_stock_real_return,
            market.real_risk_free_rate,
            market.stock_volatility,
        )
        print(f"   {age:>3}   {r.equity_share:>6.0%}   {money(r.human_capital):>14}"
              f"   {r.human_capital_ratio:>10.1f}")
    print()
    print("  Wealth is held fixed here, which no real saver does, so treat this")
    print("  as the effect of age alone rather than a forecast of your path.")
    print("  What moves the share is human capital shrinking against savings,")
    print("  not the horizon shortening. Section 2.3 of the methodology.")
    print()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="recommend.py",
        description="How much of your portfolio belongs in equities.",
    )
    parser.add_argument("--age", type=int, help="your current age, 20 to 99")
    parser.add_argument("--wage", type=float, help="current after-tax annual wage")
    parser.add_argument("--wealth", type=float, help="investable net worth")
    parser.add_argument(
        "--risk-aversion", type=float, help="1 to 10, see docs/inputs.md"
    )
    parser.add_argument("--benefit", type=float, default=0.0,
                        help="retirement benefit already being received")
    parser.add_argument("--partner-age", type=int, help="second adult's age")
    parser.add_argument("--partner-wage", type=float, help="second adult's wage")
    parser.add_argument("--glide", action="store_true",
                        help="also show the path across ages")
    args = parser.parse_args(argv[1:])

    try:
        market = load_market_data()
    except FileNotFoundError as exc:
        print(exc)
        return 1

    interactive = args.age is None or args.wage is None or args.wealth is None
    if interactive:
        print(RULE)
        print("  A few questions. See docs/inputs.md for the definitions.")
        print(RULE)
        print()
        age = int(ask("Your age", int, 20))
        wage = ask("Current after-tax annual wage", float, 0)
        wealth = ask("Investable net worth, excluding housing", float, 1)
        gamma = ask_risk_aversion()
        partner_age = partner_wage = None
    else:
        age, wage, wealth = args.age, args.wage, args.wealth
        gamma = args.risk_aversion if args.risk_aversion is not None else 5.0
        partner_age, partner_wage = args.partner_age, args.partner_wage

    adults = [Person(age, wage, args.benefit)]
    if partner_age is not None:
        if partner_wage is None:
            print("\n--partner-age needs --partner-wage. Pass 0 if they do not")
            print("earn, so that the zero is deliberate rather than assumed.")
            return 1
        adults.append(Person(partner_age, partner_wage))
    elif partner_wage is not None:
        print("\n--partner-wage needs --partner-age.")
        return 1

    try:
        household = Household(wealth, adults, gamma)
    except ValueError as exc:
        print(f"\n{exc}")
        return 1

    result = recommend(
        household,
        market.expected_stock_real_return,
        market.real_risk_free_rate,
        market.stock_volatility,
    )
    print_report(result, market, household)
    if args.glide:
        print_glide(household, market)

    print(THIN)
    print("  Educational and illustrative only. Not investment advice.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
