"""Stage 3: Choi's formula, validated against Choi's own spreadsheet.

The two tabs of the published spreadsheet are the reference implementation, so
their outputs are the regression baseline here. Both are reproduced to within a
rounding error of the figures the workbook stores.
"""

from __future__ import annotations

import pytest

from your_equity_share.allocation import Household, Recommendation, merton_share, recommend
from your_equity_share.human_capital import (
    CGM_CALIBRATION,
    RETIREMENT_AGE,
    Person,
    benefit_discount_rate,
    human_capital,
    imputed_wage,
    project_earnings,
    wage_discount_rate,
)

# Choi's defaults, shared by both tabs.
GAMMA = 5.0
MU = 0.05
REAL_RF = 0.02
# The Merton term in Choi's sheet uses the calibration volatility. The tool
# holds the same 18.5% in both layers (methodology section 7.2), and the
# value is passed explicitly wherever his output is the target.
CHOI_SIGMA = 0.185


# --- against the published spreadsheet -------------------------------------


def test_wage_imputed_tab_reproduces() -> None:
    """Adults 45 and 40 earning 100k and 80k, 500k invested.

    Spreadsheet stores: human capital 2,133,150.455, equity share 0.8920794261.
    """
    household = Household(
        investable_net_worth=500_000.0,
        adults=[Person(45, 100_000.0), Person(40, 80_000.0)],
        risk_aversion=GAMMA,
    )
    result = recommend(household, MU, REAL_RF, CHOI_SIGMA)

    assert result.human_capital == pytest.approx(2_133_150.455, abs=0.01)
    assert result.merton_share == pytest.approx(0.1693939335, abs=1e-10)
    assert result.equity_share == pytest.approx(0.8920794261, abs=1e-9)


def test_full_inputs_tab_reproduces() -> None:
    """Adults 20 and 22 with explicit schedules, not imputed.

    Spreadsheet stores human capital 2,199,507.502.
    """
    adults = [
        Person(
            20, 0.0,
            wages={a: 100_000.0 for a in range(21, 65)},
            benefits={a: 40_000.0 for a in range(65, 101)},
        ),
        Person(
            22, 0.0,
            wages={a: 100_000.0 for a in range(23, 67)},
            benefits={a: 40_000.0 for a in range(67, 101)},
        ),
    ]
    total = sum(human_capital(a, GAMMA, MU, REAL_RF) for a in adults)
    assert total == pytest.approx(2_199_507.502, abs=0.01)

    result = recommend(Household(500_000.0, adults, GAMMA), MU, REAL_RF, CHOI_SIGMA)
    assert result.equity_share == pytest.approx(0.9145603885, abs=1e-9)


# --- discount rates ---------------------------------------------------------


def test_wage_rate_matches_the_published_cell() -> None:
    """Spreadsheet cell O16 at the defaults: 0.09747653125 for age 21."""
    assert wage_discount_rate(21, GAMMA, MU, REAL_RF) == pytest.approx(
        0.09747653125, abs=1e-11
    )


def test_benefit_rate_matches_the_published_cell() -> None:
    """Spreadsheet cell Q60 at the defaults: 0.03306486317 for age 65."""
    assert benefit_discount_rate(65, GAMMA, MU, REAL_RF) == pytest.approx(
        0.03306486317, abs=1e-11
    )


def test_benefits_discount_far_more_gently_than_wages() -> None:
    """An indexed government benefit is close to risk free; a salary is not."""
    wage = wage_discount_rate(70, GAMMA, MU, REAL_RF)
    benefit = benefit_discount_rate(70, GAMMA, MU, REAL_RF)
    assert benefit < wage / 2


def test_risk_aversion_moves_the_wage_rate_but_not_the_benefit_rate() -> None:
    """Loadings of 0.087 against 0.0003. The whole difference in one coefficient."""
    wage_low = wage_discount_rate(40, 1.0, MU, REAL_RF)
    wage_high = wage_discount_rate(40, 10.0, MU, REAL_RF)
    benefit_low = benefit_discount_rate(70, 1.0, MU, REAL_RF)
    benefit_high = benefit_discount_rate(70, 10.0, MU, REAL_RF)

    assert wage_high - wage_low == pytest.approx(0.087 * 0.9, abs=1e-12)
    assert benefit_high - benefit_low == pytest.approx(0.0003 * 0.9, abs=1e-12)


def test_permanent_shocks_dominate_the_wage_rate() -> None:
    """Methodology Table 5: that term alone is 7.32 of the 9.75 points."""
    from dataclasses import replace

    base = wage_discount_rate(21, GAMMA, MU, REAL_RF)
    without = wage_discount_rate(
        21, GAMMA, MU, REAL_RF,
        replace(CGM_CALIBRATION, permanent_shock_volatility=0.0),
    )
    assert base - without == pytest.approx(4.332 * 0.13**2, abs=1e-12)
    assert base - without > 0.07


def test_temporary_shocks_barely_matter() -> None:
    """They average out over a career, so the coefficient is tiny."""
    from dataclasses import replace

    base = wage_discount_rate(21, GAMMA, MU, REAL_RF)
    without = wage_discount_rate(
        21, GAMMA, MU, REAL_RF,
        replace(CGM_CALIBRATION, temporary_shock_volatility=0.0),
    )
    assert base - without < 0.002


# --- the earnings path ------------------------------------------------------


def test_wages_stop_at_retirement() -> None:
    assert imputed_wage(RETIREMENT_AGE, 45, 100_000.0) == 0.0
    assert imputed_wage(RETIREMENT_AGE - 1, 45, 100_000.0) > 0.0


def test_earnings_hump_peaks_near_fifty() -> None:
    """The CGM cubic: rising through the thirties, peaking near fifty."""
    path = {a: imputed_wage(a, 30, 80_000.0) for a in range(31, RETIREMENT_AGE)}
    peak = max(path, key=path.__getitem__)
    assert 45 <= peak <= 57
    assert path[40] > path[31]


def test_projection_runs_to_one_hundred() -> None:
    years = project_earnings(Person(45, 100_000.0))
    assert years[0].age == 46
    assert years[-1].age == 100
    assert len(years) == 55


def test_benefit_starts_when_wages_stop_and_never_ends() -> None:
    years = {y.age: y for y in project_earnings(Person(45, 100_000.0))}
    assert years[66].benefit == 0.0
    assert years[66].wage > 0.0
    assert years[67].wage == 0.0
    assert years[67].benefit > 0.0
    assert years[100].benefit == pytest.approx(years[67].benefit)


def test_benefit_is_the_replacement_share_of_the_final_wage() -> None:
    years = {y.age: y for y in project_earnings(Person(45, 100_000.0))}
    expected = years[66].wage * CGM_CALIBRATION.benefit_replacement_rate
    assert years[67].benefit == pytest.approx(expected)


def test_someone_already_retired_keeps_their_current_benefit() -> None:
    years = project_earnings(Person(70, 0.0, current_benefit=30_000.0))
    assert all(y.benefit == 30_000.0 for y in years)
    assert all(y.wage == 0.0 for y in years)


def test_explicit_schedules_override_the_projection() -> None:
    person = Person(50, 100_000.0, wages={51: 1.0, 52: 2.0})
    years = {y.age: y for y in project_earnings(person)}
    assert years[51].wage == 1.0
    assert years[52].wage == 2.0
    assert years[53].wage > 1000.0  # imputed again


# --- the Merton share -------------------------------------------------------


def test_merton_share_uses_a_difference_of_drifts() -> None:
    import math

    got = merton_share(0.05, 0.02, 5.0, 0.185)
    expected = (math.log(1.05) - math.log(1.02)) / (5.0 * 0.185**2)
    assert got == pytest.approx(expected)


def test_doubling_volatility_quarters_the_share() -> None:
    """Variance sits in the denominator, so the effect is quadratic."""
    base = merton_share(0.05, 0.02, 5.0, 0.16)
    doubled = merton_share(0.05, 0.02, 5.0, 0.32)
    assert doubled == pytest.approx(base / 4.0)


def test_doubling_risk_aversion_halves_the_share() -> None:
    base = merton_share(0.05, 0.02, 3.0, 0.16)
    doubled = merton_share(0.05, 0.02, 6.0, 0.16)
    assert doubled == pytest.approx(base / 2.0)


def test_merton_share_has_no_horizon_term() -> None:
    """Section 2.3. Nothing about age or holding period enters."""
    import inspect

    signature = inspect.signature(merton_share)
    assert set(signature.parameters) == {
        "expected_stock_real_return",
        "real_risk_free",
        "risk_aversion",
        "stock_volatility",
    }


def test_merton_share_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="volatility must be positive"):
        merton_share(0.05, 0.02, 5.0, 0.0)
    with pytest.raises(ValueError, match="risk aversion must be positive"):
        merton_share(0.05, 0.02, 0.0, 0.16)


# --- the recommendation -----------------------------------------------------


def _household(**kwargs) -> Household:
    base = dict(
        investable_net_worth=500_000.0,
        adults=[Person(45, 100_000.0)],
        risk_aversion=GAMMA,
    )
    base.update(kwargs)
    return Household(**base)


def test_human_capital_ratio_not_age_drives_the_answer() -> None:
    """Two 55 year olds, one still earning, one not. Section 4."""
    earning = recommend(
        _household(adults=[Person(55, 120_000.0)]), MU, REAL_RF, 0.17
    )
    retired = recommend(
        _household(adults=[Person(55, 0.0, current_benefit=0.0)]), MU, REAL_RF, 0.17
    )
    assert earning.equity_share > retired.equity_share
    assert retired.human_capital < earning.human_capital


def test_the_cap_is_reported_separately_from_the_answer() -> None:
    """The formula alone goes above the model's no-borrowing constraint, so the
    raw figure stays visible beside the capped one."""
    young = recommend(
        _household(investable_net_worth=10_000.0, adults=[Person(25, 70_000.0)]),
        MU, REAL_RF, 0.17,
    )
    assert young.equity_share == 1.0
    assert young.uncapped_share > 1.0
    assert young.is_capped


def test_a_household_with_no_earnings_gets_the_merton_share_alone() -> None:
    """No human capital means no multiplier. Layer two does nothing."""
    result = recommend(
        _household(adults=[Person(80, 0.0)]), MU, REAL_RF, 0.17
    )
    assert result.human_capital == pytest.approx(0.0)
    assert result.equity_share == pytest.approx(result.merton_share)


def test_two_adults_accumulate_human_capital() -> None:
    one = recommend(_household(adults=[Person(45, 100_000.0)]), MU, REAL_RF, 0.17)
    two = recommend(
        _household(adults=[Person(45, 100_000.0), Person(40, 80_000.0)]),
        MU, REAL_RF, 0.17,
    )
    assert two.human_capital > one.human_capital
    assert len(two.per_adult_human_capital) == 2
    assert sum(two.per_adult_human_capital) == pytest.approx(two.human_capital)


def test_shares_and_dollars_agree() -> None:
    result = recommend(_household(), MU, REAL_RF, 0.17)
    assert result.equity_share + result.bond_share == pytest.approx(1.0)
    assert result.equity_dollars == pytest.approx(
        result.equity_share * 500_000.0
    )


def test_recommendation_is_a_share_between_zero_and_one() -> None:
    for age in range(25, 95, 5):
        result = recommend(
            _household(adults=[Person(age, 90_000.0)]), MU, REAL_RF, 0.17
        )
        assert 0.0 <= result.equity_share <= 1.0


def test_glide_path_declines_with_age() -> None:
    """Not because horizon shortens, but because HC/W falls. Section 4."""
    shares = [
        recommend(
            _household(
                investable_net_worth=400_000.0, adults=[Person(age, 90_000.0)]
            ),
            MU, REAL_RF, 0.17,
        ).uncapped_share
        for age in range(35, 90, 5)
    ]
    assert all(b <= a for a, b in zip(shares, shares[1:]))


# --- input validation -------------------------------------------------------


def test_rejects_risk_aversion_outside_the_guide_scale() -> None:
    """The 1 to 10 scale is the guide's. The paper solves over 4 to 10, and the
    message must not conflate the two, which it did until it was checked."""
    with pytest.raises(ValueError, match="1 to 10 scale"):
        _household(risk_aversion=0.5)
    with pytest.raises(ValueError, match="1 to 10 scale"):
        _household(risk_aversion=12.0)


def test_rejects_an_age_outside_the_fitted_range() -> None:
    with pytest.raises(ValueError, match="20 to 99"):
        Person(19, 50_000.0)
    with pytest.raises(ValueError, match="20 to 99"):
        Person(100, 50_000.0)


def test_rejects_zero_investable_wealth() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _household(investable_net_worth=0.0)


def test_rejects_more_than_two_adults() -> None:
    with pytest.raises(ValueError, match="one or two adults"):
        _household(adults=[Person(40, 1.0), Person(41, 1.0), Person(42, 1.0)])


def test_rejects_an_empty_household() -> None:
    with pytest.raises(ValueError, match="at least one adult"):
        _household(adults=[])


def test_rejects_negative_wages() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        Person(40, -1.0)


# --- what actually drives the answer ----------------------------------------


def test_the_answer_depends_on_the_ratio_and_not_on_age() -> None:
    """Age is not an input. It enters only by changing what future earnings are
    worth, so two households of different ages holding the same ratio of human
    capital to savings get the same recommendation exactly.

    This is the claim the savings chart on the page rests on, so it is asserted
    rather than assumed.
    """
    gamma, mu, rf, sigma = 5.0, 0.0635, 0.0298, 0.1718
    target = 2.0
    shares = []
    for age, wage in ((28, 60_000.0), (40, 90_000.0), (52, 130_000.0), (61, 150_000.0)):
        capital = human_capital(Person(age, wage), gamma, mu, rf, volatility=sigma)
        household = Household(capital / target, [Person(age, wage)], gamma)
        result = recommend(household, mu, rf, sigma)
        assert result.human_capital_ratio == pytest.approx(target, rel=1e-12)
        shares.append(result.equity_share)
    assert max(shares) - min(shares) == 0.0


def test_savings_move_the_answer_at_a_fixed_age() -> None:
    """The converse, and the reason the chart puts savings on the axis."""
    gamma, mu, rf, sigma = 5.0, 0.0635, 0.0298, 0.1718
    shares = [
        recommend(Household(w, [Person(45, 100_000.0)], gamma), mu, rf, sigma).equity_share
        for w in (200_000.0, 600_000.0, 1_800_000.0)
    ]
    assert all(b < a for a, b in zip(shares, shares[1:]))
    assert shares[0] - shares[-1] > 0.5


# --- supplied earnings paths ------------------------------------------------


def test_the_imputed_american_pension_stops_at_social_security_s_maximum() -> None:
    """40% of a high final wage is more than Social Security pays anyone, so
    the imputed pension stops at the maximum, after tax. A pension the person
    types is used as typed, and the Italian calibration has no such limit."""
    from your_equity_share.human_capital import ITALY_CALIBRATION, SOCIAL_SECURITY_MAXIMUM

    assert SOCIAL_SECURITY_MAXIMUM == pytest.approx(0.8 * 4152 * 12)
    high = {y.age: y.benefit for y in project_earnings(Person(60, 200_000.0))}
    assert high[67] == pytest.approx(SOCIAL_SECURITY_MAXIMUM)
    low = {y.age: y.benefit for y in project_earnings(Person(60, 60_000.0))}
    assert low[67] < SOCIAL_SECURITY_MAXIMUM
    typed = Person(60, 200_000.0, 0.0, benefits={a: 70_000.0 for a in range(67, 101)})
    assert {y.age: y.benefit for y in project_earnings(typed)}[67] == 70_000.0
    italian = {y.age: y.benefit
               for y in project_earnings(Person(60, 200_000.0), ITALY_CALIBRATION)}
    assert italian[67] > 100_000.0


def test_a_typed_zero_benefit_suppresses_the_imputed_one() -> None:
    """The distinction the page's year-by-year box depends on.

    Leaving a year out means "use the projection", and the projection starts a
    benefit worth 40% of the last wage in the first year without wages. Typing
    a zero means "no benefit that year". A reader who stops working at 55 and
    claims nothing until 67 needs the second, and would otherwise be credited
    with twelve years of income they never receive.
    """
    wages = {**{a: 90_000.0 for a in range(46, 56)},
             **{a: 0.0 for a in range(56, 67)}}
    late = {a: 20_000.0 for a in range(67, 101)}

    omitted = Person(45, 90_000.0, 0.0, wages=wages, benefits=late)
    typed = Person(45, 90_000.0, 0.0, wages=wages,
                   benefits={**{a: 0.0 for a in range(56, 67)}, **late})

    gap = {y.age: y.benefit for y in project_earnings(omitted)}
    assert gap[56] == pytest.approx(36_000.0)

    gap = {y.age: y.benefit for y in project_earnings(typed)}
    assert gap[56] == 0.0

    assert (human_capital(typed, 5.0, 0.0635, 0.0298)
            < human_capital(omitted, 5.0, 0.0635, 0.0298))


# --- pensions Choi's model has no state for ----------------------------------

def test_a_small_pension_paid_while_working_moves_the_answer_a_little() -> None:
    """A pension drawn while still working once switched the whole salary onto
    the near-riskless pension rate: typing one dollar of pension moved the
    answer by eleven points. Now it is valued as what it is, a small riskless
    stream, and the salary stays on the wage rate."""
    from your_equity_share.human_capital import benefit_discount_rate

    args = (5.0, 0.0491, 0.0329)
    without = human_capital(Person(45, 100_000.0), *args)
    with_one = human_capital(Person(45, 100_000.0, 1.0), *args)
    assert 0.0 < with_one - without < 60.0


def test_a_pension_paid_while_working_is_added_to_the_career_one() -> None:
    """A second-career earner with a military pension keeps it, and still gets
    the pension the current job will pay once the wage stops."""
    args = (5.0, 0.0491, 0.0329)
    worker = human_capital(Person(45, 80_000.0), *args)
    with_pension = human_capital(Person(45, 80_000.0, 30_000.0), *args)
    years = project_earnings(Person(45, 80_000.0, 30_000.0))
    assert years[0].benefit == 30_000.0
    assert years[-1].benefit == pytest.approx(30_000.0 + 0.40 * max(y.wage for y in years if y.wage > 0), rel=0.2)
    assert with_pension > worker


def test_a_pension_that_starts_later_is_discounted_as_a_pension() -> None:
    """Someone who has stopped working, with a pension from 67 typed year by
    year: every year is on the benefit rate, because no wage is left to carry
    the wage rate's risk premium. It used to take the wage rate until 67."""
    from your_equity_share.human_capital import benefit_discount_rate

    gamma, mu, rf = 5.0, 0.0491, 0.0329
    benefits = {age: (18_000.0 if age >= 67 else 0.0) for age in range(61, 101)}
    person = Person(60, 0.0, 0.0, benefits=benefits)
    expected, chain = 0.0, 1.0
    for year in project_earnings(person):
        chain *= 1.0 + benefit_discount_rate(year.age, gamma, mu, rf)
        expected += year.income / chain
    assert human_capital(person, gamma, mu, rf) == pytest.approx(expected, rel=1e-12)


def test_someone_of_66_still_earning_retires_on_today_s_wage() -> None:
    """With no wage left to project, the career pension comes off today's wage.
    Another pension is added to it, at every age; one marked as the person's
    state pension replaces it, as in Choi's spreadsheet."""
    working = project_earnings(Person(66, 50_000.0))
    assert working[0].wage == 0.0 and working[0].benefit == pytest.approx(20_000.0)
    other = project_earnings(Person(66, 50_000.0, 24_000.0))
    assert other[0].benefit == pytest.approx(44_000.0)
    state = project_earnings(Person(66, 50_000.0, 24_000.0, benefit_is_state=True))
    assert state[0].benefit == pytest.approx(24_000.0)


def test_a_state_pension_already_claimed_is_not_counted_twice() -> None:
    """An American still working at 63 who already draws Social Security has
    one Social Security, not that plus 40% of the final wage."""
    claimed = Person(63, 80_000.0, 25_000.0, benefit_is_state=True)
    years = {y.age: y.benefit for y in project_earnings(claimed)}
    assert years[64] == years[70] == 25_000.0
    added = {y.age: y.benefit for y in project_earnings(Person(63, 80_000.0, 25_000.0))}
    assert added[70] > 50_000.0


def test_a_pension_that_starts_later_is_paid_from_its_age_and_valued_as_safe() -> None:
    """A fixed pension from 60 for someone working to 66: nothing before 60,
    the amount from 60, and divided by the benefit rates from today, so it is
    worth what the same pension in its own field is worth from that age."""
    args = (5.0, 0.05167, 0.0296, CGM_CALIBRATION, 0.185)
    later = Person(50, 80_000.0, 20_000.0, benefit_start=60)
    years = {y.age: y.benefit for y in project_earnings(later)}
    assert years[59] == 0.0 and years[60] == 20_000.0
    without = human_capital(Person(50, 80_000.0), *args)
    gain = human_capital(later, *args) - without
    safe = 1.0
    expected = 0.0
    for age in range(51, 101):
        safe *= 1.0 + benefit_discount_rate(age, 5.0, 0.05167, 0.0296, CGM_CALIBRATION, 0.185)
        if age >= 60:
            expected += 20_000.0 / safe
    assert gain == pytest.approx(expected, rel=1e-9)


def test_an_estimate_ticked_as_social_security_is_valued_like_the_imputed_one() -> None:
    """Entering the same amount the tool would impute, from 67, ticked as the
    person's Social Security, must not change the answer: it is still an
    estimate that the rest of the career moves, so it rides the wage chain
    to the last wage year, as the imputed pension does. Only a pension already
    being paid, or one from an earlier job, is riskless."""
    args = (5.0, 0.05167, 0.0296, CGM_CALIBRATION, 0.185)
    imputed = {y.age: y.benefit for y in project_earnings(Person(45, 100_000.0))}[67]
    estimate = Person(45, 100_000.0, imputed, benefit_start=67, benefit_is_state=True)
    assert human_capital(estimate, *args) == pytest.approx(
        human_capital(Person(45, 100_000.0), *args), rel=1e-12)
    fixed = Person(45, 100_000.0, imputed, benefit_start=67)   # an earlier job's
    assert human_capital(fixed, *args) > human_capital(Person(45, 100_000.0), *args)


def test_the_spousal_switch_pays_half_the_earner_s_pension_from_62() -> None:
    """Choi's switch: the second adult claims half of the first adult's Social
    Security from 62, has no pension of their own, and the half rides the
    earner's chain, because it moves with the earner's career."""
    args = (0.05167, 0.0296, 0.185)
    earner = Person(45, 100_000.0)
    plain = recommend(Household(500_000.0, [earner, Person(43, 0.0)], 5.0), *args)
    spousal = recommend(Household(500_000.0, [earner, Person(43, 0.0, claims_spousal=True)], 5.0), *args)
    assert spousal.per_adult_human_capital[1] == 0.0
    gain = spousal.per_adult_human_capital[0] - plain.per_adult_human_capital[0]
    assert gain > 0
    # Half of the earner's pension, on the earner's own chain: the same as a
    # replacement rate half as large again from the earner's first pension year.
    years = project_earnings(earner)
    last = max(y.age for y in years if y.wage > 0)
    chain, expected = 1.0, 0.0
    for y in years:
        rate = (wage_discount_rate if y.age <= last else benefit_discount_rate)(
            y.age, 5.0, *args[:2], CGM_CALIBRATION, 0.185)
        chain *= 1.0 + rate
        if y.age >= 45 + (62 - 43):
            expected += 0.5 * y.benefit / chain
    assert gain == pytest.approx(expected, rel=1e-9)
    assert spousal.equity_share > plain.equity_share


def test_the_partner_s_pension_counts() -> None:
    """A retired couple who both draw pensions: the second one reaches the
    answer through the partner's own field."""
    one = Household(300_000.0, [Person(70, 0.0, 30_000.0), Person(70, 0.0, 0.0)], 5.0)
    both = Household(300_000.0, [Person(70, 0.0, 30_000.0), Person(70, 0.0, 30_000.0)], 5.0)
    r1 = recommend(one, 0.0491, 0.0329, 0.185)
    r2 = recommend(both, 0.0491, 0.0329, 0.185)
    assert r2.human_capital == pytest.approx(2 * r1.human_capital, rel=1e-12)


def test_ticking_the_year_by_year_box_does_not_move_a_pension() -> None:
    """The page passes its prefilled path as typed as soon as the box is
    ticked, before anyone edits a year. A pension paid while working must stay
    on the benefit rates then too: it once moved onto the wage chain, taking
    the default household with a $20,000 pension from 48.8% to 42.9%."""
    args = (5.0, 0.05167, 0.0296, CGM_CALIBRATION, 0.185)
    person = Person(45, 100_000.0, 20_000.0)
    path = project_earnings(person)
    ticked = Person(45, 100_000.0, 20_000.0,
                    wages={y.age: y.wage for y in path},
                    benefits={y.age: y.benefit for y in path})
    assert human_capital(ticked, *args) == pytest.approx(
        human_capital(person, *args), rel=1e-12)
