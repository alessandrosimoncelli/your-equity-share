"""Estimating the expected real return on equities.

This is the input the recommendation is most sensitive to and the one nobody can
observe. Choi treats it as the user's best guess and defaults to 5%, which his
guide calls "roughly equal to what is implied by current stock market valuation
ratios if those ratios stay constant and future dividend or earnings growth
equals its long-run historical average". That is a construction, not a number, and this
module builds it the way that sentence reads: the dividend yield compounded with
long-run real growth in earnings per share, with repricing at zero. Section
3.1 of the American methodology compares it, once, with four other estimators
and says why each is worse for a lifetime horizon.

A note on which premium is which. Choi fits his approximation over *log* excess
drifts of 2%, 3% and 4%, where the drift is

    pi = ln(1 + mu) - sigma^2 / 2 - ln(1 + r)

An arithmetic premium is not that. At 18.5% volatility the two differ by 1.71
percentage points, enough to move an estimate from inside the fitted range to
outside it, so `log_premium` and `within_fitted_range` are provided and the
tooling reports both.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

__all__ = [
    "CHOI_FITTED_LOG_PREMIUM_RANGE",
    "CHOI_FITTED_LOG_RISK_FREE_RANGE",
    "CHOI_FITTED_RISK_AVERSION_RANGE",
    "log_risk_free",
    "within_fitted_risk_free",
    "Estimate",
    "arithmetic_from_compound",
    "compound_from_arithmetic",
    "building_block_estimate",
    "log_premium",
    "within_fitted_range",
]

# The log excess drifts Choi's approximation was fitted over. Outside this the
# fitted coefficients are an extrapolation with no standing.
#
# These are not a recommended range. They are the three values the model was
# actually solved at, 0.02, 0.03 and 0.04, crossed with everything else to make
# the 5,103 parameter sets. The paper justifies the top and not the bottom:
# "even a 2% log equity premium results in optimal equity allocations that are
# frequently 100%. Therefore, any approximation that accurately fits the
# solution for log equity premia of 4% or less should be accurate for log
# equity premia above 4%." Below 2% he says nothing.
CHOI_FITTED_LOG_PREMIUM_RANGE = (0.02, 0.04)

# The other half of the same grid, and the one that went unchecked here for
# longer. Log real risk-free rates of 0, 0.01 and 0.02; the paper notes that
# its 2% example rate, the top of the grid, approximately equals "the five-year
# TIPS real yield in 2024". The guide then suggests the THIRTY-year yield, which in September 2026 was 2.98% a year and sat above
# every value the coefficients were fitted on. The regressor carries +1.132
# against -0.267 for the premium, so a point of extrapolation here costs four
# times what a point of premium extrapolation costs.
CHOI_FITTED_LOG_RISK_FREE_RANGE = (0.0, 0.02)

# And the third axis of the same grid. The paper solves at 4, 5, 6, 7, 8, 9 and
# 10, which is the seven in 7 x 3^6 = 5,103; the guide publishes a table from 1
# to 10. Below 4 is extrapolation, and by Choi's own argument it is the benign
# side: "at a risk aversion of 4, the optimal equity allocation is very
# frequently at the 100% upper boundary."
CHOI_FITTED_RISK_AVERSION_RANGE = (4.0, 10.0)

# Volatility baked into the fitted coefficients. Used for the log conversion so
# that the comparison against the fitted range is on Choi's own terms.
CALIBRATION_VOLATILITY = 0.185


def arithmetic_from_compound(compound: float, volatility: float) -> float:
    """Convert a compound (geometric) return into an arithmetic mean.

    They are not the same number and the gap is not small. A compound return is
    what money actually grows at; an arithmetic mean is the average of the
    yearly returns, and it sits higher by roughly half the variance. At the
    18.5% volatility the American variant holds, that is 1.8 percentage
    points: 3.41% compound is 5.19% as an average.

    This matters because every forward-looking estimate of equity returns is
    naturally compound. A discounted cash flow yields an internal rate of
    return. Gordon's formula yields a discount rate. A regression on realised
    annualised returns yields an annualised return. All compound. Choi's input
    slot is arithmetic, which is visible in his own regressor subtracting
    sigma^2 / 2. Feeding a compound figure straight in understates the input.
    """
    return math.exp(math.log(1.0 + compound) + 0.5 * volatility**2) - 1.0


def compound_from_arithmetic(arithmetic: float, volatility: float) -> float:
    """The inverse. What an arithmetic mean actually compounds at."""
    return math.exp(math.log(1.0 + arithmetic) - 0.5 * volatility**2) - 1.0


@dataclass(frozen=True)
class Estimate:
    """One expected real return, as a COMPOUND rate, with where it came from.

    The conversion to the arithmetic mean the model reads happens once, at the
    point the number is handed to the model.
    """

    method: str
    value: float
    as_of: date | None = None
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.method}: {self.value:.2%}"


def log_premium(
    expected_real_return: float,
    real_risk_free: float,
    volatility: float = CALIBRATION_VOLATILITY,
) -> float:
    """The quantity Choi's grid is expressed in, and his regressions consume."""
    return (
        math.log(1.0 + expected_real_return)
        - 0.5 * volatility**2
        - math.log(1.0 + real_risk_free)
    )


def log_risk_free(real_risk_free: float) -> float:
    """The safe rate as Choi's regressions take it, which is in logs."""
    return math.log(1.0 + real_risk_free)


def within_fitted_risk_free(real_risk_free: float) -> bool:
    """Whether the safe rate sits inside the grid the coefficients were fitted on.

    Following Choi's own guide puts a reader outside Choi's own grid: it names
    the 30-year TIPS yield, and the grid tops out at a log rate of 0.02, which
    the 30-year yield has been above since well before this tool existed.
    """
    low, high = CHOI_FITTED_LOG_RISK_FREE_RANGE
    return low <= log_risk_free(real_risk_free) <= high


def within_fitted_range(
    expected_real_return: float,
    real_risk_free: float,
    volatility: float = CALIBRATION_VOLATILITY,
) -> bool:
    low, high = CHOI_FITTED_LOG_PREMIUM_RANGE
    return low <= log_premium(expected_real_return, real_risk_free, volatility) <= high


# --- the Gordon building blocks --------------------------------------------


def building_block_estimate(
    dividend_yield: float,
    real_growth: float,
    repricing: float = 0.0,
    as_of: date | None = None,
    growth_basis: str = "",
) -> Estimate:
    """Dividend yield compounded with real per-share growth and any repricing.

    With the price-to-dividend ratio held constant, a TRAILING yield D0/P0 and
    growth g give exactly 1 + R = (1 + D0/P0)(1 + g): next year's dividend is
    D0(1 + g), and the price grows with it. Adding the two instead drops the
    cross term, about three hundredths of a point here. The worked example
    below pays its dividend over the year it measures, where the sum is exact.

    The two terms have to be measured on the same basis, and this is easy to get
    wrong. Cash reaches a shareholder as dividends and as buybacks, so a *total*
    payout yield looks like the more complete measure of income. It is, but it
    cannot be paired with *per-share* growth, because retiring shares is exactly
    what makes per-share earnings grow. Counting a buyback as income and again
    as growth counts it twice.

    Take a company of 100 shares at $15, earning $100, paying $30 of dividends
    and buying back $20, with aggregate earnings flat in real terms. The buyback
    retires 1.33 shares, so earnings per share rise 1.35%, and with the multiple
    held constant so does the price. The holder earns 2.00% + 1.35% = 3.35%.

        dividend yield + per-share growth   2.00% + 1.35% = 3.35%   correct
        payout yield   + aggregate growth   3.33% + 0.00% = 3.33%   correct
        payout yield   + per-share growth   3.33% + 1.35% = 4.69%   too high

    The last overstates by the buyback yield. Aggregate growth is not in any
    series this project reads, since the S&P earnings history is per share and
    carries no share count, so the first pairing is the one used. Straehl and
    Ibbotson (2017) make the same point at length, and Bernstein and Arnott
    (2003) measure the historical gap between the two growth rates.

    Repricing defaults to zero, which is Choi's stated assumption. It is an
    assumption and not a neutral one: a market priced above its own history has
    a negative expected repricing term that a zero ignores.
    """
    return Estimate(
        method="building blocks",
        value=(1.0 + dividend_yield) * (1.0 + real_growth) * (1.0 + repricing) - 1.0,
        as_of=as_of,
        detail=(
            f"{dividend_yield:.2%} dividend yield compounded with {real_growth:.2%} real "
            f"earnings growth per share"
            f"{f' ({growth_basis})' if growth_basis else ''}"
            + (f" plus {repricing:.2%} repricing" if repricing else ", no repricing")
        ),
    )
