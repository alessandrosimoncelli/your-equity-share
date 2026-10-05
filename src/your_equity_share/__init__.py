"""Equity allocation from the Merton share and a human capital multiplier.

Implements the approximation of Choi, Liu and Liu (2025), validated against
their published spreadsheet. See docs/inputs.md for what each input means and
variants/us/methodology.html for the derivation.

    from your_equity_share import Household, Person, recommend
    from your_equity_share.market_data import load_market_data

    market = load_market_data()
    result = recommend(
        Household(500_000, [Person(45, 100_000)], risk_aversion=5),
        market.expected_stock_real_return,
        market.real_risk_free_rate,
        market.stock_volatility,
    )
    result.equity_share
"""

from your_equity_share.allocation import (
    Household,
    Recommendation,
    merton_share,
    recommend,
)
from your_equity_share.human_capital import (
    CGM_CALIBRATION,
    ITALY_CALIBRATION,
    Calibration,
    Person,
    benefit_discount_rate,
    human_capital,
    imputed_wage,
    project_earnings,
    wage_discount_rate,
)
from your_equity_share.taxes import ITALY_TAX, NO_TAX, TaxRegime
from your_equity_share.risk_aversion import (
    certainty_equivalent,
    gamma_from_certainty_equivalent,
    guide_table,
)

__all__ = [
    "CGM_CALIBRATION",
    "ITALY_CALIBRATION",
    "ITALY_TAX",
    "NO_TAX",
    "TaxRegime",
    "Calibration",
    "Household",
    "Person",
    "Recommendation",
    "benefit_discount_rate",
    "certainty_equivalent",
    "gamma_from_certainty_equivalent",
    "guide_table",
    "human_capital",
    "imputed_wage",
    "merton_share",
    "project_earnings",
    "recommend",
    "wage_discount_rate",
]
__version__ = "0.3.0"
