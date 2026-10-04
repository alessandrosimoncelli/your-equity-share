#!/usr/bin/env python3
"""Print an equity allocation recommendation.

    python recommend.py                                  # asks you the questions
    python recommend.py --age 45 --wage 100000 \
                        --wealth 500000 --risk-aversion 5
    python recommend.py --age 45 --wage 100000 --wealth 500000 --glide

Market data comes from variants/us/market_data.toml. Run `python update.py` first if
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


def ask_optional(prompt: str, cast=int):
    """A number, or None for a blank answer."""
    while True:
        raw = input(f"  {prompt}: ").strip().replace("$", "").replace(",", "")
        if raw == "":
            return None
        try:
            return cast(raw)
        except ValueError:
            print("  Enter a number, or leave it blank.")


def ask_yes(prompt: str) -> bool:
    while True:
        raw = input(f"  {prompt} (y/n): ").strip().lower()
        if raw in ("y", "yes", "n", "no"):
            return raw.startswith("y")
        print("  Answer y or n.")


def ask_pension(whose: str) -> tuple[float, int | None, bool]:
    """A pension, the age it starts and whether it is Social Security, as the
    page asks for them."""
    amount = ask(f"{whose} pension, a year of it after tax (0 if none)", float, 0)
    if amount == 0:
        return 0.0, None, False
    start = ask_optional("The age it starts (blank if already paid)")
    state = ask_yes("Is it Social Security? Then it replaces the 40% estimate")
    return amount, start, state


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
    print(f"  which is {money(result.equity_dollars)} of "
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
    print(f"  Equity share of TOTAL wealth     {result.merton_share:>13.1%}"
          f"   Merton (1969)")
    print(f"  Times (1 + {result.human_capital_ratio:.2f}) for the part you can trade"
          f"  {result.uncapped_share:>8.1%}")
    if result.is_capped:
        print(f"  Capped, no leverage              {share:>13.1%}")
    print()

    if result.is_capped:
        print("  The model wants more than 100%, meaning it would borrow to")
        print("  invest. The cap is the no-borrowing rule of the model the")
        print("  formula approximates (Choi's equation 9). See section 4 of")
        print("  variants/us/methodology.html.")
        print()

    print(THIN)
    print(f"  Market data, as of {market.as_of}")
    print()
    method = market.provenance.get("expected_return_method", "set by hand")
    note = {"building blocks": "dividend yield plus long-run growth",
            "consensus": "median of three estimators",
            "implied": "market implied premium",
            "fixed": "set by hand"}.get(method, method)
    print(f"  expected stock real return       "
          f"{market.expected_stock_real_return:>13.2%}   {note}")
    if market.expected_return_spread > 0:
        print(f"      estimators: {market.expected_return_estimates}")
        print(f"      the first is used; the others are cross-checks spanning")
        print(f"      {market.expected_return_spread:.2%}. This is the least certain")
        print(f"      input in the model. See docs/inputs.md.")
    print(f"  real risk-free rate              "
          f"{market.real_risk_free_rate:>13.2%}   30-year TIPS")
    print(f"  stock volatility                 "
          f"{market.stock_volatility:>13.2%}   fixed, long-run")
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
                adults=[Person(age, base.current_wage, base.current_benefit,
                               benefit_start=base.benefit_start,
                               benefit_is_state=base.benefit_is_state)],
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
                        help="your pension, a year of it after tax: one already "
                             "paid, or one from --benefit-start")
    parser.add_argument("--benefit-start", type=int,
                        help="the age your pension starts, if not already paid")
    parser.add_argument("--state-pension", action="store_true",
                        help="your pension is your Social Security: it replaces "
                             "the 40%% estimate instead of adding to it")
    parser.add_argument("--partner-age", type=int, help="second adult's age")
    parser.add_argument("--partner-wage", type=float, help="second adult's wage")
    parser.add_argument("--partner-benefit", type=float, default=0.0,
                        help="second adult's pension, a year of it after tax")
    parser.add_argument("--partner-benefit-start", type=int,
                        help="the age the second adult's pension starts")
    parser.add_argument("--partner-state-pension", action="store_true",
                        help="the second adult's pension is their Social Security")
    parser.add_argument("--partner-spousal", action="store_true",
                        help="the second adult claims the spousal benefit, half "
                             "of your Social Security, instead of their own")
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
        benefit, start, state = ask_pension("Your")
        partner_age = ask_optional("Second adult's age (blank if none)")
        partner_wage = partner_benefit = 0.0
        partner_start, partner_state, spousal = None, False, False
        if partner_age is not None:
            partner_wage = ask("Their after-tax annual wage", float, 0)
            partner_benefit, partner_start, partner_state = ask_pension("Their")
            if partner_benefit == 0:
                spousal = ask_yes("Will they claim the spousal benefit, half of "
                                  "your Social Security, instead of their own?")
        gamma = ask_risk_aversion()
    else:
        age, wage, wealth = args.age, args.wage, args.wealth
        gamma = args.risk_aversion if args.risk_aversion is not None else 5.0
        partner_age, partner_wage = args.partner_age, args.partner_wage
        benefit, start, state = args.benefit, args.benefit_start, args.state_pension
        partner_benefit, partner_start = args.partner_benefit, args.partner_benefit_start
        partner_state, spousal = args.partner_state_pension, args.partner_spousal

    adults = [Person(age, wage, benefit, benefit_start=start, benefit_is_state=state)]
    if partner_age is not None:
        if partner_wage is None:
            print("\n--partner-age needs --partner-wage. Pass 0 if they do not")
            print("earn, so that the zero is deliberate rather than assumed.")
            return 1
        adults.append(Person(partner_age, partner_wage, partner_benefit,
                             benefit_start=partner_start,
                             benefit_is_state=partner_state, claims_spousal=spousal))
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
