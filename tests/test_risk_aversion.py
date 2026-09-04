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

# Transcribed from "User guide for Practical Finance", Choi, Liu and Liu,
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
