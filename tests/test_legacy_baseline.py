"""The regression baseline.

Every expected value is read from tests/baseline_cells.json, which is generated
from the source workbook by tools/extract_baseline.py. Nothing here is
transcribed by hand, so a passing run is evidence that the port reproduces the
spreadsheet rather than evidence that both agree with the same typo.

Equality is exact. The port recomputes each cell with the same operations in
the same order as the worksheet formula, so the results are bit-identical
doubles. Any drift means the port stopped matching, which is what a baseline is
for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from your_equity_share.legacy import (
    LegacyInputs,
    _weighted_average_variance,
    _weighted_excess_return,
    bull_formula_share,
    forward_earnings_yield,
    gamma,
    your_equity_share,
    real_expected_excess_return,
    real_risk_free_rate,
)

BASELINE = json.loads(
    (Path(__file__).parent / "baseline_cells.json").read_text(encoding="utf-8")
)
CELLS: dict[str, float] = BASELINE["cells"]

INPUTS = LegacyInputs()
SLEEVE_COLUMNS = ("B", "C", "D")


def cell(ref: str) -> float:
    return CELLS[ref]


# --- inputs are the ones the workbook actually stores -----------------------


@pytest.mark.parametrize("column, index", list(zip(SLEEVE_COLUMNS, range(3))))
def test_sleeve_weight_matches(column: str, index: int) -> None:
    assert INPUTS.sleeves[index].weight == cell(f"{column}4")


@pytest.mark.parametrize("column, index", list(zip(SLEEVE_COLUMNS, range(3))))
def test_sleeve_forward_pe_matches(column: str, index: int) -> None:
    assert INPUTS.sleeves[index].forward_pe == cell(f"{column}5")


@pytest.mark.parametrize("column, index", list(zip(SLEEVE_COLUMNS, range(3))))
def test_sleeve_standard_deviation_matches(column: str, index: int) -> None:
    assert INPUTS.sleeves[index].standard_deviation == cell(f"{column}8")


def test_sleeve_labels_match() -> None:
    assert [s.label for s in INPUTS.sleeves] == BASELINE["sleeve_labels"]


def test_scalar_inputs_match() -> None:
    assert INPUTS.nominal_risk_free_rate == cell("B9")
    assert INPUTS.age == cell("B12")
    assert INPUTS.risk_tolerance == cell("B13")
    assert INPUTS.risk_capacity == cell("B14")
    assert INPUTS.risk_need == cell("B15")


def test_weights_sum_to_one() -> None:
    assert sum(s.weight for s in INPUTS.sleeves) == pytest.approx(1.0, abs=1e-15)


# --- intermediate rows -----------------------------------------------------


@pytest.mark.parametrize("column, index", list(zip(SLEEVE_COLUMNS, range(3))))
def test_forward_earnings_yield_row_6(column: str, index: int) -> None:
    computed = forward_earnings_yield(INPUTS.sleeves[index].forward_pe)
    assert computed == cell(f"{column}6")


def test_real_risk_free_rate_b10() -> None:
    assert real_risk_free_rate(INPUTS.nominal_risk_free_rate) == cell("B10")


@pytest.mark.parametrize("column, index", list(zip(SLEEVE_COLUMNS, range(3))))
def test_real_expected_excess_return_row_7(column: str, index: int) -> None:
    computed = real_expected_excess_return(
        INPUTS.sleeves[index].forward_pe,
        real_risk_free_rate(INPUTS.nominal_risk_free_rate),
    )
    assert computed == cell(f"{column}7")


def test_gamma_b16() -> None:
    computed = gamma(INPUTS.risk_tolerance, INPUTS.risk_capacity, INPUTS.risk_need)
    assert computed == cell("B16")


# --- the outputs -----------------------------------------------------------


def test_your_equity_share_g4() -> None:
    assert your_equity_share(INPUTS) == cell("G4")


def test_safe_asset_share_g5() -> None:
    assert 1 - your_equity_share(INPUTS) == cell("G5")


def test_bull_formula_share_g9() -> None:
    assert bull_formula_share(INPUTS) == cell("G9")


def test_bull_formula_remainder_g10() -> None:
    assert 1 - bull_formula_share(INPUTS) == cell("G10")


# --- the defects are present, and pinned so a later fix is visible ---------


def test_denominator_ignores_correlations() -> None:
    """Defect 1. The denominator is a mean of variances, not w'Sigma w.

    Averaging variances equals the portfolio variance only under perfect
    correlation, so the value pinned here must fall once correlations are used.
    """
    weighted_mean_variance = _weighted_average_variance(INPUTS)
    assert weighted_mean_variance == pytest.approx(0.0246270976, abs=1e-12)

    # Perfect correlation gives (sum of w_i * sigma_i) ** 2, which is the
    # closest the correct calculation can come to the shortcut.
    perfectly_correlated = sum(
        s.weight * s.standard_deviation for s in INPUTS.sleeves
    ) ** 2
    assert perfectly_correlated < weighted_mean_variance


def test_numerator_uses_arithmetic_not_log_excess_return() -> None:
    """Defect 2. The correct numerator is a difference of drifts."""
    import math

    real_rf = real_risk_free_rate(INPUTS.nominal_risk_free_rate)
    arithmetic = _weighted_excess_return(INPUTS, real_rf)

    log_excess = sum(
        (
            math.log1p(forward_earnings_yield(s.forward_pe))
            - math.log1p(real_rf)
        )
        * s.weight
        for s in INPUTS.sleeves
    )
    assert arithmetic > log_excess
    assert arithmetic / log_excess == pytest.approx(1.0363, abs=0.0001)


def test_gamma_is_on_the_two_to_five_scale() -> None:
    """Defect 3. The human capital layer needs 1 to 10, not 2 to 5."""
    assert 2.0 <= cell("B16") <= 5.0


def test_expected_inflation_is_hardcoded() -> None:
    """Defect 4. B10 subtracts a literal 2.5%, not a supplied assumption."""
    assert cell("B9") - cell("B10") == pytest.approx(0.025, abs=1e-15)


# --- the share is unclipped, which matters once the multiplier arrives -----


def test_your_equity_share_is_not_clipped() -> None:
    """The worksheet applies no bounds. Raising the premium pushes it over 1."""
    aggressive = LegacyInputs(risk_tolerance=2.0, risk_capacity=2.0, risk_need=2.0)
    assert your_equity_share(aggressive) > 0.9
    assert your_equity_share(aggressive) == pytest.approx(0.9515396, abs=1e-7)
