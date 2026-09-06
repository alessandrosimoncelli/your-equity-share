"""Properties that must hold for every household the page can produce.

The rest of the suite checks this project against Choi: his workbook, his
worked example, and the JavaScript against the Python. None of that catches a
household his workbook never contains, and one such household found a real
defect: the benefit discount rate went negative below about age 40, which
valued a future payment above its face amount. See
`test_a_benefit_is_never_discounted_below_the_safe_rate`.
"""

from __future__ import annotations

import itertools
import math

import pytest

from your_equity_share import Household, Person, certainty_equivalent, recommend
from your_equity_share.human_capital import (
    benefit_discount_rate,
    human_capital,
    wage_discount_rate,
)

MU = 0.0492
RF = 0.0296
VOL = 0.171808

# Choi fits the retirement regression on retirement years alone: 63 parameter
# sets by 34 years, and 34 years is age 67 to 100.
FITTED_BENEFIT_AGES = range(67, 101)


def share(age=45, wage=100_000.0, wealth=500_000.0, gamma=5.0, benefit=0.0,
          mu=MU, rf=RF) -> float:
    household = Household(wealth, [Person(age, wage, benefit)], gamma)
    return recommend(household, mu, rf, VOL).equity_share


def is_monotone(values: list[float], direction: int) -> bool:
    return all((b - a) * direction >= -1e-12 for a, b in zip(values, values[1:]))


# --- the answer is always an allocation -------------------------------------


@pytest.mark.parametrize("age", [20, 34, 45, 66, 67, 80, 99])
@pytest.mark.parametrize("wage", [0.0, 25_000.0, 250_000.0])
@pytest.mark.parametrize("wealth", [1_000.0, 250_000.0, 50_000_000.0])
@pytest.mark.parametrize("benefit", [0.0, 30_000.0])
def test_every_household_gets_a_usable_answer(age, wage, wealth, benefit) -> None:
    result = recommend(
        Household(wealth, [Person(age, wage, benefit)], 5.0), MU, RF, VOL
    )
    assert 0.0 <= result.equity_share <= 1.0
    assert math.isfinite(result.merton_share)
    assert result.human_capital >= 0.0
    assert result.equity_share + result.bond_share == pytest.approx(1.0)
    assert result.equity_dollars == pytest.approx(result.equity_share * wealth)
    if wage == 0.0 and benefit == 0.0:
        assert result.human_capital == 0.0


# --- the directions the theory requires -------------------------------------


def test_share_falls_as_risk_aversion_rises() -> None:
    assert is_monotone([share(gamma=float(g)) for g in range(1, 11)], -1)


def test_share_rises_with_the_expected_return() -> None:
    assert is_monotone([share(mu=m) for m in (0.031, 0.04, 0.06, 0.10)], +1)


def test_share_falls_as_the_safe_rate_rises() -> None:
    assert is_monotone([share(rf=r) for r in (0.005, 0.01, 0.02, 0.029)], -1)


def test_share_falls_as_savings_rise() -> None:
    """The driver is human capital over financial wealth, so more of the second
    means less of the multiplier and a smaller share."""
    assert is_monotone(
        [share(wealth=w) for w in (10_000.0, 500_000.0, 20_000_000.0)], -1
    )


def test_share_rises_with_the_wage() -> None:
    assert is_monotone([share(wage=w) for w in (0.0, 60_000.0, 200_000.0)], +1)


def test_share_falls_with_age_at_a_fixed_wage_and_wealth() -> None:
    assert is_monotone([share(age=a) for a in (25, 45, 65, 85)], -1)


# --- risk aversion ----------------------------------------------------------


def test_certainty_equivalent_stays_inside_the_gamble() -> None:
    for tenth in range(4, 41):
        amount = certainty_equivalent(tenth / 4)
        assert 50_000.0 < amount < 75_000.0


def test_certainty_equivalent_falls_as_risk_aversion_rises() -> None:
    assert is_monotone([certainty_equivalent(float(g)) for g in range(1, 11)], -1)


# --- discount rates ---------------------------------------------------------


@pytest.mark.parametrize("age", range(21, 101, 7))
def test_a_wage_is_discounted_harder_than_a_benefit(age) -> None:
    """A salary is an undiversifiable claim on one person. A government
    inflation-linked annuity is not, and must never be marked down further."""
    assert wage_discount_rate(age, 5.0, MU, RF) > benefit_discount_rate(
        age, 5.0, MU, RF
    )


@pytest.mark.parametrize("age", range(21, 101))
def test_a_benefit_is_never_discounted_below_the_safe_rate(age) -> None:
    """The regression behind this rate is fitted on ages 67 to 100 only.

    Evaluated at 30 it returned minus 2.7%, which values a future payment above
    its face amount, and the page reaches that because it offers a pension
    field to everybody. A government indexed annuity cannot be worth more than
    a risk-free bond paying the same schedule, so the safe rate is the floor.
    """
    assert benefit_discount_rate(age, 5.0, MU, RF) >= RF


@pytest.mark.parametrize("age", FITTED_BENEFIT_AGES)
def test_the_floor_does_not_bind_where_choi_actually_fitted(age) -> None:
    """Inside the fitted ages the raw equation already clears the safe rate, so
    the floor changes nothing Choi's own work supports."""
    x = (age - 1) / 100.0
    pi = math.log(1.0 + MU) - 0.185**2 / 2 - math.log(1.0 + RF)
    raw = (
        -0.166
        + 0.0003 * (5.0 / 10.0)
        - 0.217 * pi
        + 0.893 * math.log(1.0 + RF)
        + 0.476 * x
        - 0.295 * x**2
    )
    assert raw >= RF
    assert benefit_discount_rate(age, 5.0, MU, RF) == pytest.approx(raw)


def test_a_pension_is_worth_less_than_its_undiscounted_total() -> None:
    for age, benefit in itertools.product((30, 45, 67, 85), (12_000.0, 40_000.0)):
        person = Person(age, 0.0, benefit)
        undiscounted = benefit * (100 - age)
        assert 0.0 < human_capital(person, 5.0, MU, RF) < undiscounted


# --- households of two ------------------------------------------------------


def test_two_identical_adults_are_worth_twice_one() -> None:
    one = recommend(
        Household(500_000.0, [Person(45, 100_000.0)], 5.0), MU, RF, VOL
    )
    two = recommend(
        Household(500_000.0, [Person(45, 100_000.0)] * 2, 5.0), MU, RF, VOL
    )
    assert two.human_capital == pytest.approx(2 * one.human_capital)
