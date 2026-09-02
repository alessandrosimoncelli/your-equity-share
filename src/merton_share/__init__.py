"""Equity allocation from the Merton share and a human capital multiplier.

Implements the approximation of Choi, Liu and Liu (2025). See docs/inputs.md
for what each input means and docs/methodology.html for the derivation.

Stage 1 (current): `legacy` reproduces the source spreadsheet exactly, defects
included, as the regression baseline for everything that follows.
"""

from merton_share.legacy import (
    LegacyInputs,
    LegacySleeve,
    bull_formula_share,
    merton_share,
)
from merton_share.risk_aversion import (
    certainty_equivalent,
    gamma_from_certainty_equivalent,
    guide_table,
)

__all__ = [
    "LegacyInputs",
    "LegacySleeve",
    "bull_formula_share",
    "certainty_equivalent",
    "gamma_from_certainty_equivalent",
    "guide_table",
    "merton_share",
]
__version__ = "0.1.0"
