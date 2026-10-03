"""Italian tax rates, and why the model itself does not apply them.

The model reads the market figures before tax in both variants, as Choi, Liu
and Liu do: their model has no tax in it, "so all variables are implicitly
after-tax where relevant". For Italy that was measured rather than assumed,
because the law taxes the two assets differently:

    26%    on the gain of an equity fund
    12.5%  on a fund of government bonds of Italy and white-list states, in
           proportion to what it holds in them (Agenzia delle Entrate,
           Circolare 19/E of 2014, section 5)
    0.2%   a year of imposta di bollo on the value of each

Both rates fall on the nominal gain and only when units are sold, death counts
as a sale (Circolare 19/E of 2013, section 2.4), and a loss on one fund cannot
be set against a gain on another.

A fund held for years is usually in gain when it is sold (on the snapshot,
85% of the time at seven years and 98% at thirty), so the state takes a share
of the swings as well as of the average return, which is the
effect Domar and Musgrave (1944) described. Taken through the law sale by sale,
the tax lowers the equity share a household should choose by about a quarter
for money sold within three years and by a tenth or less beyond seven, and
ignoring it costs under two basis points a year at three years and under half a
basis point beyond seven. Lowering only the expected return, as this variant
did until October 2026, cut the share by a little more than the law at three
years and by two to four times as much beyond seven. tools/tax_check.py measures it; section 8 of the
Italian methodology sets it out.

The rates are kept here for the tools that simulate the law: tax_check.py and
backtest.py.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["TaxRegime", "ITALY_TAX", "NO_TAX"]


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

# The comparison case: the figures before tax, which is what the model reads.
NO_TAX = TaxRegime(0.0, 0.0, 0.0, "none")
