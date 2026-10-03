"""Layer two: valuing future wages and retirement benefits.

Implements the approximation of Choi, Liu and Liu (2025), which fits closed-form
discount rates to the numerical solution of Cocco, Gomes and Maenhout (2005).

Three things happen here:

    the earnings path      a career projected from one current salary
    the discount rates     what a future wage or benefit is worth today
    the present value      those two combined into human capital

The discount rates are *one-year-ahead* rates. The rate attached to age `a` is
the rate the age `a-1` self applies to age `a` income, which is why the age
term uses `(a-1)/100`. Present value at any age therefore divides by the
running product of every one-year rate between here and there, not by a single
rate raised to a power.

A household follows one discount path, not two. Through the last year with a
wage it is the wage rate; after that it drops to the benefit rate, which is far
lower because an inflation-indexed government benefit is close to risk free.
Both kinds of income in a given year are discounted by that same running
product, as equation (1) of the paper describes. The switch comes once, at the
end of work, the paper's retirement threshold; Choi's spreadsheet switches in
the first year with a benefit, which is the same thing on every ordinary path
and differs only when a pension is typed in a year with wages or a gap year.
The one stream outside this rule is a pension already being paid: it is
riskless, so it is divided by the benefit rates from today.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "CGM_CALIBRATION",
    "ITALY_CALIBRATION",
    "Calibration",
    "EarningsYear",
    "Person",
    "benefit_discount_rate",
    "human_capital",
    "imputed_wage",
    "project_earnings",
    "wage_discount_rate",
]

FINAL_AGE = 100
# Wages stop at this age: the last year worked is 66.
RETIREMENT_AGE = 67


@dataclass(frozen=True)
class Calibration:
    """Values fixed inside the fitted approximation.

    These are not user inputs. The defaults are the Cocco, Gomes and Maenhout
    calibration to United States household earnings for the average **college
    graduate**, which Choi's spreadsheet uses. The paper solves separately for
    other education levels.
    """

    stock_volatility: float = 0.185
    permanent_shock_volatility: float = 0.13
    temporary_shock_volatility: float = 0.242
    # One quantity, used twice: it sets the retirement benefit as a
    # share of the final wage, and it is a regressor in equation (12).
    # This carried a second copy called wage_equity_beta, described as a
    # labour income to equity beta. The paper has no such regressor: its
    # Table 1 row is the retirement income replacement rate, and its
    # worked example reads 0.010 x 0.40 with 0.40 the replacement rate.
    benefit_replacement_rate: float = 0.40
    # The earnings profile: the coefficients on age, age squared and age
    # cubed in log earnings, which project a career from one salary. It is
    # not a regressor in equation (12); it only sets the expected wages that
    # the fitted rates discount.
    age_profile: tuple[float, float, float] = (0.3194, -0.00577, 0.000033)
    # The largest pension the model imputes, a year of it after tax, or None
    # for no limit. Only the imputed pension: one the person types is used as
    # typed.
    benefit_cap: float | None = None


# Social Security's largest benefit at full retirement age in 2026, $4,152 a
# month (SSA, 2026 cost-of-living adjustment), after tax at the guide's 0.8:
# up to 85% of benefits are taxable, so a high earner keeps about 80% of it.
# Choi's spreadsheet has no limit, and its 40% of the final wage would give a
# household earning $200,000 after tax a pension of about $76,000 a year,
# which Social Security cannot pay. The limit binds from a final wage of about
# $100,000 after tax.
SOCIAL_SECURITY_MAXIMUM = 0.8 * 4152.0 * 12

CGM_CALIBRATION = Calibration(benefit_cap=SOCIAL_SECURITY_MAXIMUM)

# The Italian variant: an Italian private-sector employee's career and pension.
#
# THE PENSION. Choi's equation (12) takes the replacement rate as a regressor,
# fitted over 0.4, 0.6 and 0.8, so Italy's 66% sits inside the grid. It is the
# Italian Treasury's projected net replacement rate for a private employee
# retiring in 2050 at 66 years and 2 months with 38 years of contributions:
# Ragioneria Generale dello Stato, Rapporto n. 26 (2025), Table 6.3.a, base
# case. The model retires everyone at 67, where Choi fitted his coefficients,
# and today's 45-year-old reaches 67 in 2048, close to that row; the table's other cases near
# 67 give 63% to 64%, and its old-age case at 69 gives 73%. It replaced the
# OECD's 79% in October 2026, a figure for 48 years of contributions ending at
# 70: Italian pensions are contributory, so retiring at 67 pays less.
#
# THE CAREER. Daminato and Padula (2024, Journal of the European Economic
# Association), Table 7 of the working paper, CSEF 585: the earnings process
# of Italian private-sector employees, estimated on the Bank of Italy's Survey
# on Household Income and Wealth, 1986 to 2008, in Cocco, Gomes and Maenhout's
# own form, a cubic in age plus permanent and transitory shocks, for a
# life-cycle model of saving and portfolio choice of the same family as
# Choi's. Earnings are after income tax, the definition of Jappelli and
# Pistaferri (2010), as the page's wage is. The sample is married household
# heads employed in the private or public sector, aged about 25 to 60.
#
# Permanent variance 0.015156, which they report inside the confidence
# interval of Jappelli and Pistaferri (2010): 12.3%, inside the 10.2% to
# 13.0% Choi fitted over. Transitory 0.023609: 15.4%, below his 24.2% to
# 32.5%, but it enters equation (12) through a coefficient of 0.028 and moves
# the discount rate by a tenth of a point. The age profile is not a regressor,
# and Choi's own worked example, section 3.3 of the paper, uses an earnings
# path outside his fitted set and lands within 3 points of the full solution.
#
# The age coefficients are imprecise one by one, so the shape was checked
# against INPS's 2024 Osservatorio on private employees, whose daily pay by
# age also keeps rising into the early sixties, by 10% from 45-49 to 60-64
# for men. The American graduate's profile instead peaks at 45 and falls.
#
# Mortality stays American: it is inside the fitted discount rates.
ITALY_CALIBRATION = Calibration(
    permanent_shock_volatility=math.sqrt(0.015156),
    temporary_shock_volatility=math.sqrt(0.023609),
    benefit_replacement_rate=0.66,
    age_profile=(-0.001022, 0.000613, -0.000006),
)


def _log_excess_drift(
    expected_stock_real_return: float,
    real_risk_free: float,
    calibration: Calibration,
    volatility: float | None = None,
) -> float:
    """The regressor Choi writes as pi: the log risk premium of the risky asset.

    Choi defines it as the asset's expected log return over the safe rate. The
    arithmetic mean the model is handed was converted from a compound return
    at the held asset's volatility, so undoing it at that same volatility
    recovers ln(1 + compound) - ln(1 + safe rate). Undoing it at the
    calibration's 18.5% instead, for an asset with another volatility, would
    feed the regression a premium the asset does not have. When the held
    volatility is 18.5%, as in Choi's spreadsheet and the American variant,
    the two are the same number.
    """
    sigma = calibration.stock_volatility if volatility is None else volatility
    return (
        math.log(1.0 + expected_stock_real_return)
        - 0.5 * sigma**2
        - math.log(1.0 + real_risk_free)
    )


def wage_discount_rate(
    age: int,
    risk_aversion: float,
    expected_stock_real_return: float,
    real_risk_free: float,
    calibration: Calibration = CGM_CALIBRATION,
    volatility: float | None = None,
) -> float:
    """One-year-ahead discount rate applied to a wage received at `age`.

    Far above the risk-free rate, and not because wages track the market: for
    the average household that correlation is about 0.007. The premium is the
    price of a claim that cannot be diversified, sold, or borrowed against.
    """
    x = (age - 1) / 100.0
    pi = _log_excess_drift(expected_stock_real_return, real_risk_free,
                           calibration, volatility)
    return (
        -0.020
        + 0.087 * (risk_aversion / 10.0)
        - 0.267 * pi
        + 1.132 * math.log(1.0 + real_risk_free)
        + 4.332 * calibration.permanent_shock_volatility**2
        + 0.028 * calibration.temporary_shock_volatility**2
        + 0.010 * calibration.benefit_replacement_rate
        - 0.149 * x
        + 0.142 * x**2
    )


def benefit_discount_rate(
    age: int,
    risk_aversion: float,
    expected_stock_real_return: float,
    real_risk_free: float,
    calibration: Calibration = CGM_CALIBRATION,
    volatility: float | None = None,
) -> float:
    """One-year-ahead discount rate applied to a retirement benefit at `age`.

    Much lower than the wage rate, because Social Security is an
    inflation-indexed claim on the federal government. Note the loading on
    risk aversion is 0.0003 against 0.087 for wages: a cautious household marks
    down a risky salary sharply and a government annuity not at all.
    """
    x = (age - 1) / 100.0
    pi = _log_excess_drift(expected_stock_real_return, real_risk_free,
                           calibration, volatility)
    rate = (
        -0.166
        + 0.0003 * (risk_aversion / 10.0)
        - 0.217 * pi
        + 0.893 * math.log(1.0 + real_risk_free)
        + 0.476 * x
        - 0.295 * x**2
    )
    # Floored at the safe rate, which binds only outside the ages Choi fitted.
    #
    # He fits this equation on retirement years alone: 63 parameter sets times
    # 34 years, and 34 years is age 67 to 100. Evaluated at 30 it returns
    # -2.7%, which values a future payment above its face amount. The page
    # reaches that, because it offers a pension field to everybody and a
    # thirty-year-old on a disability pension is not exotic.
    #
    # A government inflation-linked annuity cannot be worth more than a
    # risk-free bond paying the same schedule, so the safe rate is the floor.
    # Across ages 67 to 100 it binds in 5 of 4,250 parameter combinations, all
    # of them where the raw rate is itself below zero.
    return max(rate, real_risk_free)


def imputed_wage(
    age: int,
    current_age: int,
    current_wage: float,
    calibration: Calibration = CGM_CALIBRATION,
) -> float:
    """Expected wage at `age`, projected from one salary today.

    The cubic in age is the calibration's earnings profile. Cocco, Gomes and
    Maenhout's for an American graduate rises steeply through the thirties,
    peaks in the mid forties and then falls; the Italian one keeps rising,
    slowly, to retirement.

    The leading term is a statistical correction rather than a feature of
    careers. Wage shocks are multiplicative, so projected wages are lognormal,
    and a lognormal's mean sits above its median by half its variance. Adding
    that half variance turns the typical path into the expected path, which is
    what a present value needs. The permanent part accumulates with years
    elapsed, hence its multiplication by (age - current_age).
    """
    if age >= RETIREMENT_AGE:
        return 0.0
    elapsed = age - current_age
    linear, square, cube = calibration.age_profile
    return current_wage * math.exp(
        0.5
        * (
            elapsed * calibration.permanent_shock_volatility**2
            + calibration.temporary_shock_volatility**2
        )
        + linear * elapsed
        + square * (age**2 - current_age**2)
        + cube * (age**3 - current_age**3)
    )


@dataclass(frozen=True)
class EarningsYear:
    """One projected year for one person."""

    age: int
    wage: float
    benefit: float

    @property
    def income(self) -> float:
        return self.wage + self.benefit


@dataclass
class Person:
    """One adult in the household.

    `current_benefit` is a pension already being paid, a year of it after tax:
    a retiree's, or one drawn while still working (an earlier career's, a
    survivor's, a disability pension). It is paid every year from now. The
    retirement benefit for the person's own wages is imputed from the final
    wage and added once the wages stop.
    """

    current_age: int
    current_wage: float
    current_benefit: float = 0.0
    wages: dict[int, float] | None = field(default=None)
    benefits: dict[int, float] | None = field(default=None)

    def __post_init__(self) -> None:
        if not 20 <= self.current_age <= 99:
            raise ValueError(
                f"current age {self.current_age} is outside the 20 to 99 range "
                f"the approximation was fitted over"
            )
        if self.current_wage < 0 or self.current_benefit < 0:
            raise ValueError("wages and benefits cannot be negative")


def project_earnings(
    person: Person, calibration: Calibration = CGM_CALIBRATION
) -> list[EarningsYear]:
    """Wages and benefits for every year from next year to age 100.

    Uses whatever the person supplied year by year, and imputes the rest. A
    pension already being paid continues every year. The retirement benefit
    for the person's own career is a fixed share of the final wage, paid from
    the first year without wages onward, which matches the guide's rule of
    thumb of 40% of the last after-tax wage; someone with no wages ahead has
    no career benefit to impute.
    """
    years: list[EarningsYear] = []
    final_wage = 0.0
    career_benefit = 0.0

    for age in range(person.current_age + 1, FINAL_AGE + 1):
        if person.wages is not None and age in person.wages:
            wage = person.wages[age]
        else:
            wage = imputed_wage(age, person.current_age, person.current_wage, calibration)

        if person.benefits is not None and age in person.benefits:
            benefit = person.benefits[age]
        elif wage > 0:
            benefit = person.current_benefit
        else:
            # First year without wages: fix the career benefit off the last
            # wage earned, then hold it for life, on top of any pension
            # already being paid. With no wage left to project (someone of 66
            # or more still earning) today's wage is the last one, unless a
            # pension is already being paid, which then is that career's.
            if career_benefit == 0.0:
                if final_wage > 0:
                    base = final_wage
                elif person.current_benefit == 0:
                    base = person.current_wage
                else:
                    base = 0.0
                career_benefit = base * calibration.benefit_replacement_rate
                if calibration.benefit_cap is not None:
                    career_benefit = min(career_benefit, calibration.benefit_cap)
            benefit = person.current_benefit + career_benefit

        if wage > 0:
            final_wage = wage
        years.append(EarningsYear(age=age, wage=wage, benefit=benefit))

    return years


def human_capital(
    person: Person,
    risk_aversion: float,
    expected_stock_real_return: float,
    real_risk_free: float,
    calibration: Calibration = CGM_CALIBRATION,
    volatility: float | None = None,
) -> float:
    """Present value today of one person's future wages and benefits.

    One discount path, as in Choi: the wage rate through the last year with
    wages, the benefit rate after it, both income types divided by the same
    running product. The switch comes once, at the end of work, which is
    Choi's retirement threshold; a year without wages before work ends (a
    break typed year by year) stays on the wage rate.

    A pension already being paid while the person still works is the one
    stream Choi's model does not have. It is riskless, so it is divided by the
    benefit rates from today rather than carried on the wage chain. For a
    retiree, whose whole path is on the benefit rate, the two are the same.
    """
    years = project_earnings(person, calibration)
    last_work = max((y.age for y in years if y.wage > 0), default=0)
    total = 0.0
    chain = 1.0
    safe_chain = 1.0
    for year in years:
        benefit_rate = benefit_discount_rate(
            year.age, risk_aversion, expected_stock_real_return,
            real_risk_free, calibration, volatility,
        )
        if year.age <= last_work:
            rate = wage_discount_rate(
                year.age, risk_aversion, expected_stock_real_return,
                real_risk_free, calibration, volatility,
            )
        else:
            rate = benefit_rate
        chain *= 1.0 + rate
        safe_chain *= 1.0 + benefit_rate
        # Whether or not the year was typed: the page passes its prefilled
        # path as typed as soon as the year-by-year box is ticked, and a
        # pension already being paid is riskless either way.
        pension = min(person.current_benefit, year.benefit)
        total += (year.income - pension) / chain + pension / safe_chain
    return total
