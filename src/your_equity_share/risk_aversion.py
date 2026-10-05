"""Eliciting relative risk aversion the way Choi's user guide does.

The guide asks one question. You face a coin flip: heads you live on $100,000
for the next year, tails you live on $50,000, and you must spend the whole
amount and cannot borrow, so a bad year cannot be smoothed away. A genie
offers to replace the gamble with a guaranteed $X. The X that leaves you indifferent identifies your
risk aversion, because that X is the certainty equivalent of the gamble under
constant relative risk aversion.

This is the definition of the parameter rather than a proxy for it, which is why
it is used here in place of a scored questionnaire. Higher risk aversion means a
lower X: someone who would accept $54,000 to avoid the coin flip dislikes risk
far more than someone who holds out for $70,000.

The published table is reproduced by `guide_table()` to the dollar; the
guide's first row, $70,710, truncates the exact $70,710.68, which this rounds
to $70,711.

THE PAGE ASKS IT AS FIVE CHOICES, not as one amount to state. Each choice is
the coin or a sure amount, the amounts are never shown as a range, and each
one depends on the answer before: the staircase of Falk, Becker, Dohmen,
Huffman and Sunde's Preference Survey Module (Management Science, 2023), the
format that best predicted real-money choices among the thirty they tested.
A slider over the guide's table showed all ten answers at once and started
at 5, and both the starting point of a slider and the middle of a displayed
menu are documented pulls on the answer.

The coin pays what the household lives on now, after tax, or half of it.
Both percentages are the guide's: its $100,000 is the wage of the paper's
worked example and its $50,000 half of that. Framing the gamble on the
respondent's own income is how the Health and Retirement Study asks it
("your current total family income"), and Hanna, Gutter and Fan (2001) ask it
on take-home family income; a 50% cut is one of the Study's own gambles.
Under constant relative risk aversion only the ratio of the two outcomes
matters, so the guide's table holds at any income: $58,566 on $100,000 is
58.6% of whatever the good outcome is, and it still means 5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "GUIDE_GAMBLE_HIGH",
    "GUIDE_GAMBLE_LOW",
    "PLAUSIBLE_GAMMA_RANGE",
    "STAIRCASE_CHOICES",
    "SMALLEST_COIN",
    "Staircase",
    "answers_disagree",
    "certainty_equivalent",
    "coin_income",
    "gamma_from_certainty_equivalent",
    "guide_table",
    "offer_step",
    "staircase_answer",
    "staircase_offer",
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

    Evaluated in logs rather than directly. Written literally, `high**power`
    underflows to zero once gamma passes about 100, and the outer power then
    raises ZeroDivisionError instead of returning an answer. Factoring out the
    larger term keeps every intermediate inside the range of a float, and the
    result tends to the worse outcome as gamma grows, which is the right limit.
    """
    if high <= 0 or low <= 0:
        raise ValueError("both outcomes must be positive")
    if gamma < 0:
        raise ValueError("risk aversion cannot be negative")

    if math.isclose(gamma, 1.0, abs_tol=1e-12):
        return math.sqrt(high * low)

    power = 1.0 - gamma
    a = power * math.log(high)
    b = power * math.log(low)
    bigger = a if a > b else b
    scaled = 0.5 * math.exp(a - bigger) + 0.5 * math.exp(b - bigger)
    return math.exp((bigger + math.log(scaled)) / power)


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


# --- the question as five choices -------------------------------------------

# Five choices halve the bracket five times, into 32 parts. The halving is in
# ratio terms, so each part spans the same 7.5% of risk aversion wherever it
# falls: the equity share is proportional to 1/gamma, and a fixed ratio is a
# fixed precision in the answer.
STAIRCASE_CHOICES = 5

# A household taking in less than this a year has no living to put on the
# coin, so the question falls back to the guide's own amounts.
SMALLEST_COIN = 1_000.0


@dataclass(frozen=True)
class Staircase:
    """Where the answers so far place the household's risk aversion."""

    low: float = PLAUSIBLE_GAMMA_RANGE[0]
    high: float = PLAUSIBLE_GAMMA_RANGE[1]
    answered: int = 0

    @property
    def done(self) -> bool:
        return self.answered >= STAIRCASE_CHOICES

    @property
    def estimate(self) -> float:
        """The middle of the bracket in ratio terms: its geometric mean."""
        return math.sqrt(self.low * self.high)


def coin_income(wage: float, partner_wage: float = 0.0, pension: float = 0.0) -> float:
    """The coin's good outcome: what the household lives on now, after tax.

    The wage, the second adult's wage and any pension already being received,
    added up, because the Health and Retirement Study frames its gamble on
    "your current total family income" and Hanna, Gutter and Fan (2001) on
    take-home family income. A retired person whose partner still works lives
    on both. Rounded to the dollar, half up as the browser rounds. Below
    SMALLEST_COIN nothing is coming in, and the guide's own $100,000 is asked.
    """
    if min(wage, partner_wage, pension) < 0:
        raise ValueError("incomes cannot be negative")
    household = wage + partner_wage + pension
    if household < SMALLEST_COIN:
        return GUIDE_GAMBLE_HIGH
    return float(math.floor(household + 0.5))


def offer_step(income: float) -> float:
    """What sure amounts are rounded to: $100 on an income in six figures.

    A thousandth of the income's order of magnitude, counted from its digits
    rather than from a logarithm, so the browser port rounds identically.
    """
    if income < 1:
        raise ValueError("the income behind the question must be at least 1")
    digits = len(str(int(income)))
    return max(1.0, 10.0 ** (digits - 1) / 1000.0)


def staircase_offer(state: Staircase, income: float) -> float:
    """The sure amount to set against the coin next.

    The coin pays `income` or half of it. The offer is the amount the coin is
    worth at the middle of the current bracket, rounded to a friendly figure.
    It starts near the middle of the dollar range, $62,800 on $100,000, which
    is where the validated staircase starts too.
    """
    if state.done:
        raise ValueError("all the choices have been answered")
    exact = certainty_equivalent(state.estimate, income, income / 2.0)
    step = offer_step(income)
    return math.floor(exact / step + 0.5) * step


def staircase_answer(
    state: Staircase, income: float, offer: float, took_sure: bool
) -> Staircase:
    """Narrow the bracket by one answer.

    Taking the sure amount says the coin is worth less to this household than
    the offer, so its risk aversion is at least the value at which the offer
    is exactly the coin's worth; choosing the coin says it is at most that.
    The split is computed from the offer as shown, after rounding, so what is
    inferred is what the person actually saw.
    """
    if state.done:
        raise ValueError("all the choices have been answered")
    split = gamma_from_certainty_equivalent(offer, income, income / 2.0)
    split = min(max(split, state.low), state.high)
    if took_sure:
        return Staircase(split, state.high, state.answered + 1)
    return Staircase(state.low, split, state.answered + 1)


# --- the self-assessment, as a check on the choices -------------------------

def answers_disagree(willingness: int, gamma: float) -> bool:
    """True when the self-assessment and the choices point opposite ways.

    `willingness` is the answer to "in financial matters, how willing are you
    to take risks?" on the 0 to 10 scale of Dohmen, Falk, Huffman, Sunde,
    Schupp and Wagner (2011), higher meaning more willing. `gamma` is the
    risk aversion the choices imply, higher meaning more cautious.

    The self-assessment does not change gamma: nothing converts one scale into
    the other, so it is used only to notice a contradiction. Each scale is cut
    into thirds, and the answers disagree when they sit in opposite outer
    thirds: very willing yet cautious (7 or more on both), or very unwilling
    yet relaxed (3 or less, and risk aversion under 4, which is also where
    Choi's fitted grid ends).
    """
    if not 0 <= willingness <= 10:
        raise ValueError("willingness is on a scale from 0 to 10")
    willing, unwilling = willingness >= 7, willingness <= 3
    cautious, relaxed = gamma >= 7.0, gamma < 4.0
    return (willing and cautious) or (unwilling and relaxed)
