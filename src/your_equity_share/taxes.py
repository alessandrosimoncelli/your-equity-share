"""What the Italian tax code does to the choice between the two assets.

Italy taxes government bonds at 12.5% and almost everything else at 26%. That
is not a household's circumstance, like an American choosing between a taxable
account and an IRA. It is a fixed feature of the law that applies to every
resident, it applies to exactly the two assets this model chooses between, and
it favours the safe one. So it belongs in the model rather than in a footnote
telling the reader to adjust the numbers themselves.

It lives here rather than in config/market_data_it.toml for the same reason
ITALY_CALIBRATION lives in human_capital.py: a tax rate is not market data. It
does not go stale in days, no provider publishes it, and refreshing the market
figures must not silently rewrite it.

FOUR THINGS ARE MODELLED, and the fourth is the one that surprises.

RATES. 12.5% on interest and capital gains from Italian government bonds and
from the government bonds of white-list states, which includes Germany, so the
safe asset in this variant gets the low rate. 26% on everything else, which
includes every equity fund. Both are flat withholding rates, not marginal
income tax, so they do not depend on the household's income.

TAX IS ON NOMINAL INCOME, so inflation is taxed. This matters more than the
rate difference at low real yields. A 3.78% nominal yield against 2.04%
expected inflation is a 1.71% real yield, but the 12.5% is levied on the whole
3.78%, which is 0.47 points, and that comes out of the 1.71%. Better than a
quarter of the real yield is tax on inflation. Both sides are therefore grossed
up to nominal, taxed, and deflated back, rather than having a rate applied to a
real return.

THE 0.2% STAMP DUTY, imposta di bollo, is charged every year on the market
value of financial assets, on both sides. It is not an income tax and it is
levied whether or not anything was earned, so it is a straight annual drag.

DEFERRAL, which pulls the other way and is the reason the 26% hurts less than
it looks. An accumulating fund distributes nothing, so nothing is taxed until
the units are sold. Over a lifetime the untaxed compounding is worth a great
deal: at these figures over thirty years it recovers roughly three quarters of
a point a year, so the effective rate on equities is well under 26%. The safe
asset gets none of this, because its coupons are taxed as they arrive.

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

__all__ = [
    "TaxRegime",
    "ITALY_TAX",
    "NO_TAX",
    "after_tax_safe_rate",
    "after_tax_equity_compound",
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

# The comparison case. Not "an American household", which pays plenty of tax,
# but the pre-tax figures the market data actually contains.
NO_TAX = TaxRegime(0.0, 0.0, 0.0, "none")


def after_tax_safe_rate(nominal_yield: float, expected_inflation: float,
                        regime: TaxRegime = ITALY_TAX) -> float:
    """The real yield left after tax on the coupon and the stamp duty.

    Coupons are taxed as they arrive, so there is no deferral on this side.
    The tax falls on the nominal coupon, which is why the answer is not simply
    the real yield times one minus the rate: the part of the coupon that only
    compensates for inflation is taxed as though it were income.
    """
    after_tax_nominal = nominal_yield * (1.0 - regime.government_bond_rate)
    after_levy = after_tax_nominal - regime.wealth_tax_rate
    return (1.0 + after_levy) / (1.0 + expected_inflation) - 1.0


def after_tax_equity_compound(compound_real: float, expected_inflation: float,
                              years: float,
                              regime: TaxRegime = ITALY_TAX) -> float:
    """The real compound return left after tax on sale and the stamp duty.

    An accumulating fund is taxed once, on the whole nominal gain, when it is
    sold. So the gross return compounds untaxed for `years` and the state takes
    its share at the end, which is worth far more than a lower rate applied
    every year would be.

    The stamp duty is not deferred: it is charged annually on the value, so it
    is taken as a drag on the growth rate rather than out of the final gain.

    Returns a compound rate. The model takes an arithmetic mean, so callers
    convert with expected_return.arithmetic_from_compound afterwards, at the
    same volatility as before: see the module docstring for why tax does not
    reduce the volatility under Italian rules.
    """
    if years <= 0:
        raise ValueError(f"years must be positive, got {years}")

    nominal = (1.0 + compound_real) * (1.0 + expected_inflation) - 1.0
    after_levy = (1.0 + nominal) * (1.0 - regime.wealth_tax_rate) - 1.0

    gross_multiple = (1.0 + after_levy) ** years
    taxed_multiple = 1.0 + (1.0 - regime.other_financial_income_rate) * (
        gross_multiple - 1.0)
    real_multiple = taxed_multiple / (1.0 + expected_inflation) ** years
    return real_multiple ** (1.0 / years) - 1.0
