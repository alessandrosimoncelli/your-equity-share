"""Faithful port of the "Merton Share" worksheet.

This module reproduces the source spreadsheet exactly, including the parts that
are wrong. It exists to be a regression baseline: every later correction is
measured against it, so the effect of each change is demonstrated rather than
asserted. Nothing here should be used to give advice.

Known defects, reproduced deliberately and corrected in later modules:

1. `_weighted_average_variance` averages the sleeves' individual variances
   instead of computing the portfolio variance w'Σw. It ignores correlations,
   which always overstates risk and so always understates the allocation.
2. `merton_share` uses the arithmetic excess return mu - r. The Merton
   numerator is a difference of drifts, so it should be ln(1+mu) - ln(1+r).
3. `gamma` averages three scores on a 2 to 5 scale. The discount-rate equations
   of the human capital layer expect a 1 to 10 scale.
4. Expected inflation is hardcoded at 2.5% inside `real_risk_free_rate`.

See docs/methodology.html sections 3.2, 2.1, 3.4 and 7.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "LegacyInputs",
    "LegacySleeve",
    "forward_earnings_yield",
    "real_risk_free_rate",
    "real_expected_excess_return",
    "gamma",
    "merton_share",
    "bull_formula_share",
]

# Cell B10 subtracts a literal 2.5% from the nominal rate.
HARDCODED_EXPECTED_INFLATION = 0.025


@dataclass(frozen=True)
class LegacySleeve:
    """One risky asset, as columns B, C and D of the worksheet."""

    label: str
    weight: float               # row 4
    forward_pe: float           # row 5
    standard_deviation: float   # row 8


@dataclass(frozen=True)
class LegacyInputs:
    """Every input cell of the worksheet.

    The default values are the ones stored in the source workbook, so
    `merton_share(LegacyInputs())` reproduces cell G4.
    """

    sleeves: tuple[LegacySleeve, ...] = field(
        default_factory=lambda: (
            LegacySleeve("S&P 500", 0.65, 22.4, 0.1575),
            LegacySleeve("MSCI exUS", 0.28, 12.0, 0.1526),
            # Cell D4 is =1-(B4+C4) rather than a typed constant. Computing it
            # the same way reproduces the same double, 0.06999999999999995.
            LegacySleeve("MSCI EM", 1.0 - (0.65 + 0.28), 15.5, 0.1683),
        )
    )
    nominal_risk_free_rate: float = 0.035  # B9
    age: int = 20                          # B12
    risk_tolerance: float = 2.0            # B13, tolleranza al rischio
    risk_capacity: float = 2.0             # B14, capacita di rischio
    risk_need: float = 3.0                 # B15, necessita di rischio


def forward_earnings_yield(forward_pe: float) -> float:
    """Row 6. `=1/B5`."""
    return 1.0 / forward_pe


def real_risk_free_rate(nominal_risk_free_rate: float) -> float:
    """Cell B10. `=B9-2.5%`, with expected inflation hardcoded."""
    return nominal_risk_free_rate - HARDCODED_EXPECTED_INFLATION


def real_expected_excess_return(forward_pe: float, real_rf: float) -> float:
    """Row 7. `=B6-$B$10`.

    The earnings yield stands in for the expected real return, so the excess
    return is that yield less the real safe rate.
    """
    return forward_earnings_yield(forward_pe) - real_rf


def gamma(risk_tolerance: float, risk_capacity: float, risk_need: float) -> float:
    """Cell B16. `=AVERAGE(B13:B15)`.

    Defect 3: the worksheet scores each dimension from 2 to 5 and takes a plain
    mean. Higher means more risk averse.
    """
    return (risk_tolerance + risk_capacity + risk_need) / 3.0


def _weighted_excess_return(inputs: LegacyInputs, real_rf: float) -> float:
    """Numerator of G4: `B7*B4 + C7*C4 + D7*D4`."""
    total = 0.0
    for sleeve in inputs.sleeves:
        total += real_expected_excess_return(sleeve.forward_pe, real_rf) * sleeve.weight
    return total


def _weighted_average_variance(inputs: LegacyInputs) -> float:
    """Denominator term of G4: `B8^2*B4 + C8^2*C4 + D8^2*D4`.

    Defect 1: this is a weighted mean of the individual variances, not the
    portfolio variance. It equals the portfolio variance only when the sleeves
    are perfectly correlated, and otherwise exceeds it.
    """
    total = 0.0
    for sleeve in inputs.sleeves:
        total += sleeve.standard_deviation**2 * sleeve.weight
    return total


def merton_share(inputs: LegacyInputs | None = None) -> float:
    """Cell G4, the equity share of total wealth.

    `=(B7*B4+C7*C4+D7*D4)/((B8^2*B4+C8^2*C4+D8^2*D4)*B16)`

    Returned unclipped, exactly as the worksheet leaves it.
    """
    inputs = inputs if inputs is not None else LegacyInputs()
    real_rf = real_risk_free_rate(inputs.nominal_risk_free_rate)
    numerator = _weighted_excess_return(inputs, real_rf)
    denominator = _weighted_average_variance(inputs) * gamma(
        inputs.risk_tolerance, inputs.risk_capacity, inputs.risk_need
    )
    return numerator / denominator


def bull_formula_share(inputs: LegacyInputs | None = None) -> float:
    """Cell G9. `=(125-B12-B9*500)/100`.

    Reproduced so the baseline covers the worksheet completely. It is not part
    of the tool's recommendation: see docs/methodology.html Table 6, where the
    age-based rule costs 2.00% of lifetime consumption against 0.06% for the
    approach this project implements.
    """
    inputs = inputs if inputs is not None else LegacyInputs()
    return (125 - inputs.age - inputs.nominal_risk_free_rate * 500) / 100
