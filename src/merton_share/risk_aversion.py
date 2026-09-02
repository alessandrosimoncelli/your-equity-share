"""Eliciting relative risk aversion the way Choi's user guide does.

The guide asks one question. You face a coin flip: heads you live on $100,000
for the next year, tails you live on $50,000. A genie offers to replace the
gamble with a guaranteed $X. The X that leaves you indifferent identifies your
risk aversion, because that X is the certainty equivalent of the gamble under
constant relative risk aversion.

This is the definition of the parameter rather than a proxy for it, which is why
it is used here in place of a scored questionnaire. Higher risk aversion means a
lower X: someone who would accept $54,000 to avoid the coin flip dislikes risk
far more than someone who holds out for $70,000.

The published table is reproduced by `guide_table()` to the dollar, so the
numbers a user sees here are the numbers in the guide.
"""

from __future__ import annotations

import math

__all__ = [
    "GUIDE_GAMBLE_HIGH",
    "GUIDE_GAMBLE_LOW",
    "PLAUSIBLE_GAMMA_RANGE",
    "certainty_equivalent",
    "gamma_from_certainty_equivalent",
    "guide_table",
]

# The gamble used in the user guide.
GUIDE_GAMBLE_HIGH = 100_000.0
GUIDE_GAMBLE_LOW = 50_000.0

# The range the guide describes as the one economists work in.
PLAUSIBLE_GAMMA_RANGE = (1.0, 10.0)


def certainty_equivalent(
    gamma: float,
    high: float = GUIDE_GAMBLE_HIGH,
    low: float = GUIDE_GAMBLE_LOW,
) -> float:
    """The guaranteed amount worth the same as a 50/50 gamble between `high` and `low`.

    Under constant relative risk aversion, utility is `W**(1-gamma)/(1-gamma)`,
    so the certainty equivalent of an even gamble is

        [ (high**(1-gamma) + low**(1-gamma)) / 2 ] ** (1/(1-gamma))

    At gamma = 1 utility is logarithmic and that expression is undefined; the
    limit is the geometric mean, which is what this returns.
    """
    if high <= 0 or low <= 0:
        raise ValueError("both outcomes must be positive")
    if gamma < 0:
        raise ValueError("risk aversion cannot be negative")

    if math.isclose(gamma, 1.0, abs_tol=1e-12):
        return math.sqrt(high * low)

    power = 1.0 - gamma
    return (0.5 * high**power + 0.5 * low**power) ** (1.0 / power)


def gamma_from_certainty_equivalent(
    amount: float,
    high: float = GUIDE_GAMBLE_HIGH,
    low: float = GUIDE_GAMBLE_LOW,
    tolerance: float = 1e-10,
) -> float:
    """Invert `certainty_equivalent`: the risk aversion implied by answering `amount`.

    The certainty equivalent falls monotonically in gamma, from the arithmetic
    mean of the two outcomes at gamma = 0 down towards the lower outcome, so a
    bisection is reliable and needs no starting guess.
    """
    midpoint = 0.5 * (high + low)
    if amount >= midpoint:
        raise ValueError(
            f"an answer of {amount:,.0f} is at or above the average outcome of "
            f"{midpoint:,.0f}, which means no aversion to the risk at all"
        )
    if amount <= min(high, low):
        raise ValueError(
            f"an answer of {amount:,.0f} is at or below the worst outcome of "
            f"{min(high, low):,.0f}, which no risk aversion can justify"
        )

    lower, upper = 0.0, 1.0
    while certainty_equivalent(upper, high, low) > amount:
        upper *= 2.0
        if upper > 1e6:
            raise ValueError("could not bracket a solution")

    while upper - lower > tolerance:
        middle = 0.5 * (lower + upper)
        if certainty_equivalent(middle, high, low) > amount:
            lower = middle
        else:
            upper = middle
    return 0.5 * (lower + upper)


def guide_table(
    high: float = GUIDE_GAMBLE_HIGH,
    low: float = GUIDE_GAMBLE_LOW,
) -> dict[int, float]:
    """The lookup table printed in the user guide, computed rather than copied."""
    return {g: certainty_equivalent(float(g), high, low) for g in range(1, 11)}
