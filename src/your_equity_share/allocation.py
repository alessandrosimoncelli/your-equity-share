"""The recommendation: how much of the portfolio belongs in equities.

Two layers, as set out in docs/methodology.html.

    layer one   the Merton share: the equity share of TOTAL wealth
    layer two   rescale it, because most of a working household's total wealth
                is future wages that cannot be traded

    w_fin = clip( beta * (1 + HC/W), 0, 1 )

The clip is a no-leverage, no-shorting constraint imposed from outside. It is
not a result of the model, and the uncapped figure is reported alongside so the
difference is visible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from your_equity_share.human_capital import (
    CGM_CALIBRATION,
    Calibration,
    Person,
    human_capital,
)

__all__ = [
    "Household",
    "Recommendation",
    "merton_share",
    "recommend",
]


def merton_share(
    expected_stock_real_return: float,
    real_risk_free: float,
    risk_aversion: float,
    stock_volatility: float,
) -> float:
    """Equity share of TOTAL wealth. Merton (1969).

        w* = [ln(1+mu) - ln(1+r)] / (gamma * sigma^2)

    The numerator is a difference of drifts, not of quoted returns. Under
    geometric Brownian motion an expected annual return of mu corresponds to a
    drift of ln(1+mu), and the Merton numerator is a drift difference.

    This is the answer for someone with no future earnings. Almost nobody is
    that person, which is what layer two corrects.
    """
    if stock_volatility <= 0:
        raise ValueError("stock volatility must be positive")
    if risk_aversion <= 0:
        raise ValueError("risk aversion must be positive")
    if expected_stock_real_return <= -1 or real_risk_free <= -1:
        raise ValueError("returns below -100% are not meaningful")

    numerator = math.log(1.0 + expected_stock_real_return) - math.log(
        1.0 + real_risk_free
    )
    return numerator / (risk_aversion * stock_volatility**2)


@dataclass
class Household:
    """Everything the model needs about the people.

    Market inputs come separately, from config/market_data.toml. See
    docs/inputs.md for what each of these means, in particular that wages are
    after tax and in today's dollars, and that investable net worth excludes
    housing and is net of tax owed on withdrawal.
    """

    investable_net_worth: float
    adults: list[Person] = field(default_factory=list)
    risk_aversion: float = 5.0

    def __post_init__(self) -> None:
        if self.investable_net_worth <= 0:
            raise ValueError(
                "investable net worth must be positive: the recommendation is a "
                "share of it, so there is nothing to allocate at zero"
            )
        if not self.adults:
            raise ValueError("a household needs at least one adult")
        if len(self.adults) > 2:
            raise ValueError(
                "the approximation was fitted for households of one or two adults"
            )
        if not 1.0 <= self.risk_aversion <= 10.0:
            raise ValueError(
                f"risk aversion {self.risk_aversion} is outside the 1 to 10 scale "
                f"Choi's guide uses. His model was solved over 4 to 10; below 4 "
                f"is accepted here because it is the side where the answer "
                f"saturates at 100%. See docs/inputs.md for how to determine yours."
            )


@dataclass(frozen=True)
class Recommendation:
    """What the model says, and enough working to see why."""

    equity_share: float
    merton_share: float
    human_capital: float
    financial_wealth: float
    uncapped_share: float
    per_adult_human_capital: tuple[float, ...]

    @property
    def human_capital_ratio(self) -> float:
        """HC/W. This, not age, is what drives the recommendation."""
        return self.human_capital / self.financial_wealth

    @property
    def is_capped(self) -> bool:
        """True when the model wanted leverage and the constraint bound."""
        return self.uncapped_share > 1.0

    @property
    def bond_share(self) -> float:
        return 1.0 - self.equity_share

    @property
    def equity_dollars(self) -> float:
        """A property, like its three siblings above.

        It was the one plain method among the four, so `r.equity_dollars`
        returned a bound method: truthy in a condition, and an error only at
        the point somebody tried to format it. The JavaScript port has always
        exposed it as a value.
        """
        return self.equity_share * self.financial_wealth


def recommend(
    household: Household,
    expected_stock_real_return: float,
    real_risk_free: float,
    stock_volatility: float,
    calibration: Calibration = CGM_CALIBRATION,
) -> Recommendation:
    """Run both layers and return the recommendation with its working.

    `stock_volatility` is the volatility of the portfolio actually held, used in
    the Merton term. The discount rates inside layer two keep the calibration's
    18.5% regardless, because their coefficients were fitted with that value in
    place. Section 7.1 of the methodology explains why the two are not forced
    to agree.
    """
    beta = merton_share(
        expected_stock_real_return,
        real_risk_free,
        household.risk_aversion,
        stock_volatility,
    )

    per_adult = tuple(
        human_capital(
            adult,
            household.risk_aversion,
            expected_stock_real_return,
            real_risk_free,
            calibration,
        )
        for adult in household.adults
    )
    total_hc = sum(per_adult)

    uncapped = beta * (1.0 + total_hc / household.investable_net_worth)

    return Recommendation(
        equity_share=max(0.0, min(1.0, uncapped)),
        merton_share=beta,
        human_capital=total_hc,
        financial_wealth=household.investable_net_worth,
        uncapped_share=uncapped,
        per_adult_human_capital=per_adult,
    )
