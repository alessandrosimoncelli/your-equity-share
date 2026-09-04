"""Generate the conformance fixture that binds the JavaScript port to Python.

    python tools/make_golden.py

The browser runs JavaScript; the tests, the refresh and the validation against
Choi's spreadsheet are all Python. Two implementations of the same arithmetic
will drift unless something checks them, so this writes every layer of the model
out at full precision and `tools/check_golden.mjs` replays it through the port.

Python stays the reference implementation. The fixture is its testimony.

Cases are recorded per function rather than only end to end, so a failure says
which layer broke instead of only that the answer moved.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.allocation import (  # noqa: E402
    Household,
    merton_share,
    recommend,
)
from your_equity_share.human_capital import (  # noqa: E402
    CGM_CALIBRATION,
    Person,
    benefit_discount_rate,
    human_capital,
    imputed_wage,
    project_earnings,
    wage_discount_rate,
)
from your_equity_share.risk_aversion import (  # noqa: E402
    certainty_equivalent,
    gamma_from_certainty_equivalent,
)

OUT = ROOT / "tests" / "golden.json"

# Coverage, not volume. A transcription error shows on any case, so what the
# fixture has to hit is every branch: either side of retirement, a zero wage,
# a benefit already being drawn, gamma exactly 1 where the formula changes,
# and markets that drive the answer to the floor and into the cap.
AGES = [20, 30, 45, 60, 66, 67, 75, 99]
GAMMAS = [1.0, 2.0, 5.0, 6.4, 10.0]
RETURNS = [0.03, 0.0673, 0.10]
RISK_FREE = [0.0, 0.0298, 0.045]
VOLATILITIES = [0.12, 0.1719, 0.25]
WAGES = [0.0, 35_000.0, 100_000.0, 240_000.0]
WEALTHS = [1_000.0, 500_000.0, 4_000_000.0]


def merton_cases() -> list[dict]:
    cases = []
    for mu in RETURNS:
        for rf in RISK_FREE:
            for gamma in GAMMAS:
                for sigma in VOLATILITIES:
                    cases.append(
                        {
                            "args": [mu, rf, gamma, sigma],
                            "expect": merton_share(mu, rf, gamma, sigma),
                        }
                    )
    return cases


def discount_rate_cases() -> tuple[list[dict], list[dict]]:
    wage, benefit = [], []
    for age in AGES:
        for gamma in GAMMAS:
            for mu in RETURNS:
                for rf in RISK_FREE[:3]:
                    wage.append(
                        {
                            "args": [age, gamma, mu, rf],
                            "expect": wage_discount_rate(age, gamma, mu, rf),
                        }
                    )
                    benefit.append(
                        {
                            "args": [age, gamma, mu, rf],
                            "expect": benefit_discount_rate(age, gamma, mu, rf),
                        }
                    )
    return wage, benefit


def imputed_wage_cases() -> list[dict]:
    cases = []
    for current_age in AGES:
        for age in range(current_age + 1, 101, 7):
            for current_wage in WAGES[1:3]:
                cases.append(
                    {
                        "args": [age, current_age, current_wage],
                        "expect": imputed_wage(age, current_age, current_wage),
                    }
                )
    return cases


def risk_aversion_cases() -> tuple[list[dict], list[dict]]:
    forward = [
        {"args": [g], "expect": certainty_equivalent(g)}
        for g in [0.0, 0.5, 0.9999999, 1.0, 1.0000001, 1.5, 2.0, 3.0, 4.0,
                  5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.5, 20.0]
    ]
    # The inverse is a bisection, so it is the most likely place for a port to
    # drift. Sampled densely across the slider's whole range.
    inverse = [
        {"args": [float(a)], "expect": gamma_from_certainty_equivalent(float(a))}
        for a in range(50_100, 75_000, 500)
    ]
    return forward, inverse


def _person_payload(p: Person) -> dict:
    return {
        "current_age": p.current_age,
        "current_wage": p.current_wage,
        "current_benefit": p.current_benefit,
    }


def earnings_cases() -> list[dict]:
    """The projected path itself, so a divergence in the benefit rule shows up
    here rather than only as a wrong present value."""
    cases = []
    for current_age in [25, 45, 66, 67, 70, 85]:
        for wage in WAGES[1:3]:
            for current_benefit in [0.0, 18_000.0]:
                person = Person(current_age, wage, current_benefit)
                years = project_earnings(person)
                cases.append(
                    {
                        "person": _person_payload(person),
                        "expect": [
                            {"age": y.age, "wage": y.wage, "benefit": y.benefit}
                            for y in years
                        ],
                    }
                )
    return cases


def human_capital_cases() -> list[dict]:
    cases = []
    for current_age in AGES:
        for wage in WAGES:
            for current_benefit in [0.0, 18_000.0]:
                for gamma in [1.0, 5.0]:
                    for mu, rf in [(0.03, 0.0), (0.0673, 0.0298)]:
                        person = Person(current_age, wage, current_benefit)
                        cases.append(
                            {
                                "person": _person_payload(person),
                                "args": [gamma, mu, rf],
                                "expect": human_capital(person, gamma, mu, rf),
                            }
                        )
    return cases


def recommend_cases() -> list[dict]:
    cases = []
    for current_age in AGES:
        for wage in WAGES:
            for wealth in WEALTHS:
                for gamma in [1.0, 5.0, 10.0]:
                    for mu, rf, sigma in [
                        (0.03, 0.0298, 0.185),      # premium near zero
                        (0.0673, 0.0298, 0.1719),   # today
                        (0.10, 0.0, 0.12),          # far into the cap
                    ]:
                        household = Household(
                            wealth, [Person(current_age, wage)], gamma
                        )
                        r = recommend(household, mu, rf, sigma)
                        cases.append(
                            {
                                "household": {
                                    "investable_net_worth": wealth,
                                    "adults": [
                                        _person_payload(a) for a in household.adults
                                    ],
                                    "risk_aversion": gamma,
                                },
                                "args": [mu, rf, sigma],
                                "expect": {
                                    "equity_share": r.equity_share,
                                    "merton_share": r.merton_share,
                                    "human_capital": r.human_capital,
                                    "financial_wealth": r.financial_wealth,
                                    "uncapped_share": r.uncapped_share,
                                    "human_capital_ratio": r.human_capital_ratio,
                                    "is_capped": r.is_capped,
                                    "bond_share": r.bond_share,
                                    "equity_dollars": r.equity_dollars(),
                                    "per_adult_human_capital": list(
                                        r.per_adult_human_capital
                                    ),
                                },
                            }
                        )

    # Two-adult households, including one already retired, since the sum over
    # adults is a place where an order-of-operations difference would show.
    for ages, wages in [
        ((45, 42), (100_000.0, 80_000.0)),
        ((30, 34), (60_000.0, 0.0)),
        ((68, 66), (0.0, 40_000.0)),
        ((55, 55), (150_000.0, 150_000.0)),
    ]:
        for gamma in [2.0, 5.0, 8.0]:
            adults = [Person(ages[0], wages[0]), Person(ages[1], wages[1])]
            household = Household(750_000.0, adults, gamma)
            r = recommend(household, 0.0673, 0.0298, 0.1719)
            cases.append(
                {
                    "household": {
                        "investable_net_worth": 750_000.0,
                        "adults": [_person_payload(a) for a in adults],
                        "risk_aversion": gamma,
                    },
                    "args": [0.0673, 0.0298, 0.1719],
                    "expect": {
                        "equity_share": r.equity_share,
                        "merton_share": r.merton_share,
                        "human_capital": r.human_capital,
                        "financial_wealth": r.financial_wealth,
                        "uncapped_share": r.uncapped_share,
                        "human_capital_ratio": r.human_capital_ratio,
                        "is_capped": r.is_capped,
                        "bond_share": r.bond_share,
                        "equity_dollars": r.equity_dollars(),
                        "per_adult_human_capital": list(r.per_adult_human_capital),
                    },
                }
            )
    return cases


def rejection_cases() -> list[dict]:
    """Inputs the model must refuse. A port that silently returns a number for
    these is wrong in a way no numeric comparison would catch."""
    return [
        {"fn": "merton_share", "args": [0.05, 0.02, 5.0, 0.0]},
        {"fn": "merton_share", "args": [0.05, 0.02, 0.0, 0.16]},
        {"fn": "merton_share", "args": [0.05, 0.02, -1.0, 0.16]},
        {"fn": "merton_share", "args": [-1.5, 0.02, 5.0, 0.16]},
        {"fn": "merton_share", "args": [0.05, -1.2, 5.0, 0.16]},
        {"fn": "household", "args": [0.0, 45, 100_000.0, 5.0]},
        {"fn": "household", "args": [-10.0, 45, 100_000.0, 5.0]},
        {"fn": "household", "args": [500_000.0, 45, 100_000.0, 0.5]},
        {"fn": "household", "args": [500_000.0, 45, 100_000.0, 10.5]},
        {"fn": "person", "args": [19, 100_000.0, 0.0]},
        {"fn": "person", "args": [100, 100_000.0, 0.0]},
        {"fn": "person", "args": [45, -1.0, 0.0]},
        {"fn": "person", "args": [45, 100_000.0, -1.0]},
        {"fn": "gamma_from_certainty_equivalent", "args": [75_000.0]},
        {"fn": "gamma_from_certainty_equivalent", "args": [50_000.0]},
        {"fn": "gamma_from_certainty_equivalent", "args": [49_000.0]},
    ]


def main() -> int:
    wage_rates, benefit_rates = discount_rate_cases()
    forward_ce, inverse_ce = risk_aversion_cases()

    cases = {
        "merton_share": merton_cases(),
        "wage_discount_rate": wage_rates,
        "benefit_discount_rate": benefit_rates,
        "imputed_wage": imputed_wage_cases(),
        "certainty_equivalent": forward_ce,
        "gamma_from_certainty_equivalent": inverse_ce,
        "project_earnings": earnings_cases(),
        "human_capital": human_capital_cases(),
        "recommend": recommend_cases(),
        "must_reject": rejection_cases(),
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "tools/make_golden.py",
        "note": (
            "Expected values produced by the Python implementation, which is the "
            "reference. Replay with: node tools/check_golden.mjs"
        ),
        "calibration": {
            "stock_volatility": CGM_CALIBRATION.stock_volatility,
            "permanent_shock_volatility": CGM_CALIBRATION.permanent_shock_volatility,
            "temporary_shock_volatility": CGM_CALIBRATION.temporary_shock_volatility,
            "wage_equity_beta": CGM_CALIBRATION.wage_equity_beta,
            "benefit_replacement_rate": CGM_CALIBRATION.benefit_replacement_rate,
        },
        "cases": cases,
    }

    # Compact: this is a machine fixture replayed by check_golden.mjs, and the
    # reviewable artefact is this generator, not its output.
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    total = sum(len(v) for v in cases.values())
    print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB)")
    for name, rows in cases.items():
        print(f"  {len(rows):>5}  {name}")
    print(f"  {total:>5}  total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
