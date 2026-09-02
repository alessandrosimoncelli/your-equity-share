"""Equity allocation from the Merton share and a human capital multiplier.

Stage 1 (current): `legacy` reproduces the source spreadsheet exactly, defects
included, as the regression baseline for everything that follows.
"""

from merton_share.legacy import (
    LegacyInputs,
    LegacySleeve,
    bull_formula_share,
    gamma,
    merton_share,
)

__all__ = [
    "LegacyInputs",
    "LegacySleeve",
    "bull_formula_share",
    "gamma",
    "merton_share",
]
__version__ = "0.1.0"
