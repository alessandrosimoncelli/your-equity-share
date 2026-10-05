"""The elicitation must reproduce the table printed in Choi's user guide.

Those are the numbers a user will see, so they are pinned here as published,
rounded to whole dollars exactly as the guide prints them.
"""

from __future__ import annotations

import pytest

from your_equity_share.risk_aversion import (
    GUIDE_GAMBLE_HIGH,
    GUIDE_GAMBLE_LOW,
    certainty_equivalent,
    gamma_from_certainty_equivalent,
    guide_table,
)

# Transcribed from the user guide for the "Practical Finance: An Approximate
# Solution to Lifecycle Portfolio Choice" spreadsheet, Choi, Liu and Liu,
# 24 December 2025, the risk aversion section.
PUBLISHED = {
    1: 70_710,
    2: 66_667,
    3: 63_246,
    4: 60_571,
    5: 58_566,
    6: 57_083,
    7: 55_978,
    8: 55_143,
    9: 54_499,
    10: 53_991,
}


@pytest.mark.parametrize("gamma, published", sorted(PUBLISHED.items()))
def test_matches_the_published_table(gamma: int, published: int) -> None:
    """Within a dollar of every published row.

    A dollar rather than exact rounding because the guide is not consistent at
    the last digit: the gamma = 1 row prints $70,710 where the exact value is
    $70,710.68, which rounds up. Every other row rounds. The difference is a
    presentation choice in the guide, not a disagreement about the model.
    """
    assert abs(certainty_equivalent(float(gamma)) - published) <= 1.0


def test_guide_table_covers_one_to_ten() -> None:
    assert sorted(guide_table()) == list(range(1, 11))


def test_gamma_one_is_the_geometric_mean() -> None:
    """Log utility. The closed form is undefined there, so the limit is used."""
    expected = (GUIDE_GAMBLE_HIGH * GUIDE_GAMBLE_LOW) ** 0.5
    assert certainty_equivalent(1.0) == pytest.approx(expected)


def test_continuous_through_gamma_one() -> None:
    """No discontinuity at the special case."""
    below = certainty_equivalent(1.0 - 1e-6)
    at = certainty_equivalent(1.0)
    above = certainty_equivalent(1.0 + 1e-6)
    assert below == pytest.approx(at, rel=1e-6)
    assert above == pytest.approx(at, rel=1e-6)


def test_zero_risk_aversion_gives_the_average_outcome() -> None:
    assert certainty_equivalent(0.0) == pytest.approx(
        0.5 * (GUIDE_GAMBLE_HIGH + GUIDE_GAMBLE_LOW)
    )


def test_certainty_equivalent_falls_as_risk_aversion_rises() -> None:
    values = [certainty_equivalent(g / 2) for g in range(0, 41)]
    assert all(b < a for a, b in zip(values, values[1:]))


def test_certainty_equivalent_stays_between_the_outcomes() -> None:
    for gamma in (0.0, 0.5, 1.0, 3.0, 10.0, 50.0):
        value = certainty_equivalent(gamma)
        assert GUIDE_GAMBLE_LOW < value < GUIDE_GAMBLE_HIGH


def test_rejects_negative_risk_aversion() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        certainty_equivalent(-1.0)


def test_rejects_non_positive_outcomes() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        certainty_equivalent(3.0, high=100.0, low=0.0)


# --- inverting the answer --------------------------------------------------


@pytest.mark.parametrize("gamma", [1.0, 2.0, 3.5, 5.0, 7.25, 10.0])
def test_inversion_round_trips(gamma: float) -> None:
    amount = certainty_equivalent(gamma)
    assert gamma_from_certainty_equivalent(amount) == pytest.approx(gamma, abs=1e-6)


@pytest.mark.parametrize("gamma, published", sorted(PUBLISHED.items()))
def test_published_answers_recover_their_gamma(gamma: int, published: int) -> None:
    """A user reading a value off the guide's table gets that row's gamma back."""
    assert gamma_from_certainty_equivalent(float(published)) == pytest.approx(
        float(gamma), abs=0.001
    )


def test_answering_the_average_is_rejected() -> None:
    """Indifference at the mean is risk neutrality, outside the model's range."""
    with pytest.raises(ValueError, match="no aversion"):
        gamma_from_certainty_equivalent(75_000.0)


def test_answering_above_the_average_is_rejected() -> None:
    with pytest.raises(ValueError, match="no aversion"):
        gamma_from_certainty_equivalent(80_000.0)


def test_answering_the_worst_outcome_is_rejected() -> None:
    with pytest.raises(ValueError, match="worst outcome"):
        gamma_from_certainty_equivalent(50_000.0)


def test_a_typical_answer_lands_in_the_plausible_range() -> None:
    """The guide describes 1 to 10 as the range economists work in."""
    assert 1.0 < gamma_from_certainty_equivalent(60_000.0) < 10.0


def test_works_for_a_gamble_of_a_different_size() -> None:
    """Risk aversion is relative, so scaling both outcomes scales the answer."""
    scaled = certainty_equivalent(
        4.0, high=2 * GUIDE_GAMBLE_HIGH, low=2 * GUIDE_GAMBLE_LOW
    )
    assert scaled == pytest.approx(2 * certainty_equivalent(4.0))


# --- the underflow that used to crash the terminal front end ----------------


def test_certainty_equivalent_survives_extreme_risk_aversion() -> None:
    """Written directly, high**(1-gamma) underflows to zero once gamma passes
    about a hundred, and the outer power then raised ZeroDivisionError. Any
    answer at or below about $50,500 reached that, and recommend.py catches
    only ValueError, so it died with a traceback."""
    for gamma in (50.0, 100.0, 500.0, 1_000.0, 1e6):
        value = certainty_equivalent(gamma)
        assert GUIDE_GAMBLE_LOW < value < GUIDE_GAMBLE_HIGH


def test_certainty_equivalent_tends_to_the_worst_outcome() -> None:
    """The limit as risk aversion grows without bound: someone infinitely
    averse to risk values the gamble at exactly its worst case."""
    assert certainty_equivalent(1e6) == pytest.approx(GUIDE_GAMBLE_LOW, abs=1.0)
    assert certainty_equivalent(1e9) == pytest.approx(GUIDE_GAMBLE_LOW, abs=1e-3)


def test_certainty_equivalent_stays_monotonic_through_the_extreme_range() -> None:
    previous = certainty_equivalent(1.0)
    for gamma in (2.0, 5.0, 10.0, 25.0, 60.0, 120.0, 400.0, 5_000.0):
        current = certainty_equivalent(gamma)
        assert current < previous
        previous = current


def test_answers_just_above_the_worst_outcome_invert_cleanly() -> None:
    for amount in (50_100.0, 50_500.0, 51_000.0, 54_000.0):
        gamma = gamma_from_certainty_equivalent(amount)
        assert gamma > 0
        assert certainty_equivalent(gamma) == pytest.approx(amount, abs=1.0)


# --- the question as five choices -------------------------------------------

from your_equity_share.risk_aversion import (  # noqa: E402
    STAIRCASE_CHOICES,
    Staircase,
    offer_step,
    staircase_answer,
    staircase_offer,
)


def _answer_truthfully(gamma: float, income: float) -> tuple[Staircase, list[float]]:
    """A respondent whose risk aversion is exactly `gamma`, answering every
    choice by comparing the coin's worth to them with the amount offered."""
    state, offers = Staircase(), []
    while not state.done:
        offer = staircase_offer(state, income)
        offers.append(offer)
        worth = certainty_equivalent(gamma, income, income / 2.0)
        state = staircase_answer(state, income, offer, took_sure=worth < offer)
    return state, offers


@pytest.mark.parametrize("income", [100_000.0, 45_000.0, 250_000.0, 1_234_567.0])
@pytest.mark.parametrize("gamma", [1.3, 2.0, 3.5, 4.0, 5.0, 6.5, 8.0, 9.7])
def test_five_choices_recover_a_respondent_s_risk_aversion(gamma, income) -> None:
    """Within 4% anywhere on the scale: the bracket's ratio is about 1.075."""
    state, _ = _answer_truthfully(gamma, income)
    assert state.answered == STAIRCASE_CHOICES
    assert state.low <= gamma <= state.high
    assert state.estimate == pytest.approx(gamma, rel=0.04)


def test_the_answer_does_not_depend_on_the_size_of_the_income() -> None:
    """Only the ratio of the two outcomes matters, so a household on $250,000
    and one on $45,000 with the same risk aversion end in the same place,
    to within the rounding of the amounts they were shown."""
    for gamma in (1.5, 3.0, 5.0, 8.0):
        small, _ = _answer_truthfully(gamma, 45_000.0)
        large, _ = _answer_truthfully(gamma, 250_000.0)
        assert small.estimate == pytest.approx(large.estimate, rel=0.01)


def test_the_first_offer_sits_near_the_middle_of_the_range() -> None:
    """$62,800 on $100,000, against a range of $53,991 to $70,711."""
    offer = staircase_offer(Staircase(), 100_000.0)
    assert offer == 62_800.0
    assert abs(offer - (certainty_equivalent(1.0) + certainty_equivalent(10.0)) / 2) < 600


def test_offers_are_round_amounts_scaled_to_the_income() -> None:
    assert offer_step(100_000.0) == 100.0
    assert offer_step(45_000.0) == 10.0
    assert offer_step(1_234_567.0) == 1_000.0
    _, offers = _answer_truthfully(4.2, 45_000.0)
    assert all(o == round(o / 10.0) * 10.0 for o in offers)


def test_always_taking_the_sure_amount_ends_at_the_cautious_end() -> None:
    state, _ = _answer_truthfully(40.0, 100_000.0)
    assert state.high == 10.0 and state.estimate > 9.0


def test_always_taking_the_coin_ends_at_the_relaxed_end() -> None:
    state, _ = _answer_truthfully(0.2, 100_000.0)
    assert state.low == 1.0 and state.estimate < 1.1


def test_a_sixth_choice_is_refused() -> None:
    state, _ = _answer_truthfully(5.0, 100_000.0)
    with pytest.raises(ValueError, match="answered"):
        staircase_offer(state, 100_000.0)


# --- the self-assessment, as a check on the choices -------------------------

from your_equity_share.risk_aversion import answers_disagree  # noqa: E402


@pytest.mark.parametrize("willingness, gamma, expected", [
    (9, 8.0, True),    # very willing, very cautious
    (7, 7.0, True),    # the edges of both outer thirds
    (2, 1.5, True),    # very unwilling, very relaxed
    (3, 3.99, True),
    (9, 2.0, False),   # willing and relaxed: consistent
    (1, 9.0, False),   # unwilling and cautious: consistent
    (5, 9.5, False),   # a middle self-assessment never contradicts
    (5, 1.0, False),
    (8, 6.9, False),   # cautious only from 7
    (3, 4.0, False),   # relaxed only below 4
])
def test_answers_disagree_only_in_opposite_outer_thirds(willingness, gamma, expected) -> None:
    assert answers_disagree(willingness, gamma) is expected


def test_the_self_assessment_scale_is_zero_to_ten() -> None:
    with pytest.raises(ValueError, match="0 to 10"):
        answers_disagree(11, 5.0)


# --- what the coin pays -------------------------------------------------------

from your_equity_share.risk_aversion import GUIDE_GAMBLE_HIGH, coin_income  # noqa: E402


def test_the_coin_pays_what_the_household_lives_on() -> None:
    """Both wages and any pension being drawn, as the Health and Retirement
    Study frames its gamble on current total family income."""
    assert coin_income(200_000.0) == 200_000.0
    assert coin_income(200_000.0, 80_000.0) == 280_000.0
    assert coin_income(0.0, 0.0, 30_000.0) == 30_000.0


def test_a_retired_person_with_a_working_partner_lives_on_both() -> None:
    """The case the page used to get wrong: the pension was dropped whenever
    anyone in the household earned a wage."""
    assert coin_income(0.0, 80_000.0, 30_000.0) == 110_000.0


def test_with_nothing_coming_in_the_guide_s_own_amount_is_asked() -> None:
    assert coin_income(0.0) == GUIDE_GAMBLE_HIGH
    assert coin_income(400.0, 0.0, 599.0) == GUIDE_GAMBLE_HIGH
    assert coin_income(400.0, 0.0, 600.0) == 1_000.0


def test_the_coin_is_rounded_to_the_dollar_half_up() -> None:
    """Half up, as the browser rounds, not to even as Python's round() does."""
    assert coin_income(100_000.5) == 100_001.0
    assert coin_income(100_002.5) == 100_003.0


@pytest.mark.parametrize("args", [(-1.0, 0.0, 0.0), (1.0, -1.0, 0.0), (1.0, 0.0, -1.0)])
def test_negative_incomes_are_rejected(args) -> None:
    with pytest.raises(ValueError):
        coin_income(*args)
