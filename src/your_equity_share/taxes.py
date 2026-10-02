"""What the Italian tax code does to the choice between the two assets.

Italy taxes government bonds at 12.5% and almost everything else at 26%. That
is not a household's circumstance, like an American choosing between a taxable
account and an IRA. It is a fixed feature of the law that applies to every
resident, it applies to exactly the two assets this model chooses between, and
it favours the safe one. So it belongs in the model rather than in a footnote
telling the reader to adjust the numbers themselves. Choi, Liu and Liu ask for
it too: their model has no tax in it, "so all variables are implicitly
after-tax where relevant".

It lives here rather than in variants/it/market_data.toml for the same reason
ITALY_CALIBRATION lives in human_capital.py: a tax rate is not market data. It
does not go stale in days, no provider publishes it, and refreshing the market
figures must not silently rewrite it.

BOTH ASSETS ARE ACCUMULATING FUNDS, which is how an Italian household holds
them: a world equity ETF and a euro government bond ETF that reinvest what they
earn. FIVE THINGS ARE MODELLED.

RATES. 26% on the equity fund. 12.5% on the bond fund, because a fund's income
is taxed at 12.5% in proportion to what it holds in government bonds of Italy
and of white-list states (Agenzia delle Entrate, Circolare 19/E of 2014,
section 5), and the safe asset here is AAA euro area government bonds, all of
them white-listed. Both are flat withholding rates, not marginal income tax,
so they do not depend on the household's income.

TAX IS ON NOMINAL GAINS, so inflation is taxed. Both sides are grossed up to
nominal, taxed, and deflated back, rather than having a rate applied to a real
return.

THE 0.2% STAMP DUTY, imposta di bollo, is charged every year on the market
value of both funds. It is not an income tax and it is levied whether or not
anything was earned, so it is a straight annual drag.

DEFERRAL. An accumulating fund distributes nothing, so nothing is taxed until
the units are sold, and the untaxed compounding is worth more the longer the
sale is put off. Both funds get it, at their own rates.

WHEN THE SALE HAPPENS, which is the one thing the model has to assume. Italian
law treats death as a sale for funds: the gain is taxed when the units pass to
the heirs (Agenzia delle Entrate, Circolare 19/E of 2013, section 2.4). So the
tax can be put off at most for the rest of a life, and the model takes the
sooner of thirty years and the household's expected remaining lifetime, from
the 2019 life table inside Choi's coefficients; for two adults, the average of
their two. Thirty is the maturity of the safe asset Choi's guide asks for. It
binds below about fifty, where most answers are already 100%, and is cautious
there, since a young saver's money stays invested for longer.

AND ONE THING IS DELIBERATELY NOT MODELLED, which is the interesting part.

A tax on investment returns normally makes a risky asset MORE attractive, not
less. If the state takes 26% of your gains and refunds 26% of your losses it
has taken a 26% stake in the position, and the household can restore the risk
it wanted by holding more. That is the Domar and Musgrave (1944) result, and
under it the right move would be to scale the volatility down by one minus the
rate, which would raise the recommendation.

It does not apply here, because Italian law does not do the refund half. Gains
on funds and ETFs are redditi di capitale; losses on the same funds are
minusvalenze, which are redditi diversi, and the two categories cannot be
netted against each other. The state takes a quarter of the upside and declines
a quarter of the downside. So the volatility is left alone, which is both the
conservative choice and the correct one for a household whose equity sleeve is
a fund. A household holding individual shares would be in the other regime,
where gains are redditi diversi too and losses do offset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from your_equity_share.expected_return import (
    arithmetic_from_compound,
    compound_from_arithmetic,
)
from your_equity_share.mortality import remaining_life_expectancy

__all__ = [
    "TaxRegime",
    "ITALY_TAX",
    "NO_TAX",
    "TAX_DEFERRAL_YEARS",
    "deferral_years",
    "after_tax_equity_compound",
    "after_tax_bond_fund",
    "after_tax_returns",
]


@dataclass(frozen=True)
class TaxRegime:
    """Flat withholding rates and an annual levy on value.

    `label` is carried so a report can say which regime produced a number
    without the caller having to remember.
    """

    government_bond_rate: float
    other_financial_income_rate: float
    wealth_tax_rate: float
    label: str

    def __post_init__(self) -> None:
        for name in ("government_bond_rate", "other_financial_income_rate",
                     "wealth_tax_rate"):
            rate = getattr(self, name)
            if not 0.0 <= rate < 1.0:
                raise ValueError(f"{name} must be in [0, 1), got {rate}")


# Italy, as of 2026. 12.5% on government bonds of Italy and of white-list
# states, 26% on other financial income, 0.2% a year of imposta di bollo on
# the value of the holding.
ITALY_TAX = TaxRegime(
    government_bond_rate=0.125,
    other_financial_income_rate=0.26,
    wealth_tax_rate=0.002,
    label="Italy",
)

# The longest the tax is put off: thirty years, the maturity of the safe asset
# Choi's guide asks for. A household with less life expected than that sells
# sooner; see deferral_years.
TAX_DEFERRAL_YEARS = 30.0

# The comparison case. Not "an American household", which pays plenty of tax,
# but the pre-tax figures the market data actually contains.
NO_TAX = TaxRegime(0.0, 0.0, 0.0, "none")


def deferral_years(ages: Iterable[int]) -> float:
    """How long the household's funds stay unsold: the sooner of thirty years
    and the expected remaining lifetime, averaged over the adults.

    Averaged because Italian law taxes each adult's units at that adult's own
    death, so a couple's savings are sold in two halves.
    """
    lifetimes = [remaining_life_expectancy(age) for age in ages]
    if not lifetimes:
        raise ValueError("a household needs at least one adult")
    return min(TAX_DEFERRAL_YEARS, sum(lifetimes) / len(lifetimes))


def _deferred(compound_real: float, expected_inflation: float, years: float,
              rate: float, levy: float) -> float:
    """The real compound return of a fund taxed once, on sale after `years`.

    The gross return compounds untaxed and the state takes its share of the
    whole nominal gain at the end, which is worth far more than the same rate
    applied every year. The stamp duty is charged annually on the value, so it
    is a drag on the growth rate rather than a share of the final gain.
    """
    if years <= 0:
        raise ValueError(f"years must be positive, got {years}")
    nominal = (1.0 + compound_real) * (1.0 + expected_inflation) - 1.0
    after_levy = (1.0 + nominal) * (1.0 - levy) - 1.0
    gross_multiple = (1.0 + after_levy) ** years
    taxed_multiple = 1.0 + (1.0 - rate) * (gross_multiple - 1.0)
    real_multiple = taxed_multiple / (1.0 + expected_inflation) ** years
    return real_multiple ** (1.0 / years) - 1.0


def after_tax_equity_compound(compound_real: float, expected_inflation: float,
                              years: float,
                              regime: TaxRegime = ITALY_TAX) -> float:
    """The real compound return the equity fund keeps after tax and stamp duty.

    Returns a compound rate. The model takes an arithmetic mean, so callers
    convert with expected_return.arithmetic_from_compound afterwards, at the
    same volatility as before: see the module docstring for why tax does not
    reduce the volatility under Italian rules.
    """
    return _deferred(compound_real, expected_inflation, years,
                     regime.other_financial_income_rate, regime.wealth_tax_rate)


def after_tax_bond_fund(real_yield: float, expected_inflation: float,
                        years: float, regime: TaxRegime = ITALY_TAX) -> float:
    """The real return the government bond fund keeps after tax and stamp duty.

    The safe asset has no volatility in this model, so its compound and
    arithmetic returns are the same number and no conversion follows.
    """
    return _deferred(real_yield, expected_inflation, years,
                     regime.government_bond_rate, regime.wealth_tax_rate)


def after_tax_returns(expected_return: float, real_risk_free: float,
                      volatility: float, expected_inflation: float,
                      years: float,
                      regime: TaxRegime = ITALY_TAX) -> tuple[float, float]:
    """The pair the model reads, after tax, for funds sold after `years`.

    `expected_return` is the arithmetic mean before tax, as the market file
    states it. It is taxed as a compound return, because tax falls on what the
    money actually grows to, and converted back at the same volatility.
    """
    compound = compound_from_arithmetic(expected_return, volatility)
    kept = after_tax_equity_compound(compound, expected_inflation, years, regime)
    return (arithmetic_from_compound(kept, volatility),
            after_tax_bond_fund(real_risk_free, expected_inflation, years, regime))
