"""Estimating the expected real return on equities.

This is the input the recommendation is most sensitive to and the one nobody can
observe. Choi treats it as the user's best guess and defaults to 5%, justified as
"what current valuation ratios imply if those ratios stay constant and growth
matches its long-run average". That is a construction, not a number, so this
module builds it three independent ways from free public data and reports the
spread rather than pretending to one answer.

    A  implied premium     Damodaran's implied equity risk premium plus the real
                           risk-free rate. Forward looking, market implied,
                           monthly. Embeds analyst growth forecasts.
    B  building blocks     dividend yield plus long-run real growth in earnings
                           per share, the Gordon identity with repricing at
                           zero. This is Choi's own sentence read literally.
    C  valuation           regress realised subsequent real return on the
                           cyclically adjusted earnings yield across Shiller's
                           history, then read off today's valuation.

They do not agree, and the disagreement is the point. See `spread`.

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
import statistics
from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "CHOI_FITTED_LOG_PREMIUM_RANGE",
    "CHOI_FITTED_LOG_RISK_FREE_RANGE",
    "log_risk_free",
    "within_fitted_risk_free",
    "Estimate",
    "arithmetic_from_compound",
    "compound_from_arithmetic",
    "building_block_estimate",
    "consensus",
    "implied_premium_estimate",
    "log_premium",
    "real_total_return_index",
    "spread",
    "valuation_regression_estimate",
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
# equity premia above 4%." Below 2% he says nothing, because AQR's 1.9%
# forecast was the low end of what looked plausible when he wrote.
CHOI_FITTED_LOG_PREMIUM_RANGE = (0.02, 0.04)

# The other half of the same grid, and the one that went unchecked here for
# longer. Log real risk-free rates of 0, 0.01 and 0.02, calibrated in the paper
# to "the five-year TIPS real yield in 2024". The guide then tells a reader to
# enter the THIRTY-year yield, which in September 2026 is 2.96% and sits above
# every value the coefficients were fitted on. The regressor carries +1.132
# against -0.267 for the premium, so a point of extrapolation here costs four
# times what a point of premium extrapolation costs.
CHOI_FITTED_LOG_RISK_FREE_RANGE = (0.0, 0.02)

# Volatility baked into the fitted coefficients. Used for the log conversion so
# that the comparison against the fitted range is on Choi's own terms.
CALIBRATION_VOLATILITY = 0.185


def arithmetic_from_compound(compound: float, volatility: float) -> float:
    """Convert a compound (geometric) return into an arithmetic mean.

    They are not the same number and the gap is not small. A compound return is
    what money actually grows at; an arithmetic mean is the average of the
    yearly returns, and it sits higher by roughly half the variance. At 17%
    volatility that is 1.5 percentage points.

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
    """One expected real return, with enough to judge how much to trust it.

    `basis` records whether `value` is a compound or an arithmetic return.
    Every estimator here produces compound returns; the conversion happens once,
    at the point the number is handed to the model.
    """

    method: str
    value: float
    as_of: date | None = None
    detail: str = ""
    standard_error: float | None = None
    observations: int = 0
    independent_observations: int = 0
    basis: str = "compound"

    def as_arithmetic(self, volatility: float) -> "Estimate":
        """The same estimate expressed as an arithmetic mean."""
        if self.basis == "arithmetic":
            return self
        converted = arithmetic_from_compound(self.value, volatility)
        return Estimate(
            method=self.method,
            value=converted,
            as_of=self.as_of,
            detail=self.detail,
            standard_error=self.standard_error,
            observations=self.observations,
            independent_observations=self.independent_observations,
            basis="arithmetic",
        )

    def __str__(self) -> str:
        error = (
            f" +/- {self.standard_error:.2%}" if self.standard_error is not None else ""
        )
        return f"{self.method}: {self.value:.2%}{error}"


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


# --- A: the market's implied premium ---------------------------------------


def implied_premium_estimate(
    implied_erp: float, real_risk_free: float, as_of: date | None = None
) -> Estimate:
    """Damodaran's implied premium plus the real risk-free rate.

    The premium is quoted against the 10-year nominal Treasury. Adding it to a
    30-year real yield treats it as neutral to both maturity and inflation. The
    maturity part of that is measurable: the 30-year real yield currently sits
    about half a point above the 10-year, and that difference passes straight
    into this estimate.
    """
    return Estimate(
        method="implied premium",
        value=implied_erp + real_risk_free,
        as_of=as_of,
        detail=(
            f"{implied_erp:.2%} implied premium (Damodaran, a discounted cash "
            f"flow on the index) plus {real_risk_free:.2%} real risk-free rate"
        ),
    )


# --- B: the Gordon building blocks ------------------------------------------


def building_block_estimate(
    dividend_yield: float,
    real_growth: float,
    repricing: float = 0.0,
    as_of: date | None = None,
    growth_basis: str = "",
) -> Estimate:
    """Dividend yield plus real per-share growth plus any repricing.

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
        value=dividend_yield + real_growth + repricing,
        as_of=as_of,
        detail=(
            f"{dividend_yield:.2%} dividend yield plus {real_growth:.2%} real "
            f"earnings growth per share"
            f"{f' ({growth_basis})' if growth_basis else ''}"
            + (f" plus {repricing:.2%} repricing" if repricing else ", no repricing")
        ),
    )


# --- C: what valuations have historically implied ---------------------------


def real_total_return_index(
    real_prices: list[float], real_dividends: list[float]
) -> list[float]:
    """A real total return index from monthly real prices and annual dividends.

    One twelfth of the annual dividend is reinvested each month. Price alone is
    not a return: over Shiller's history dividends are the larger part of it.
    """
    if len(real_prices) != len(real_dividends):
        raise ValueError("prices and dividends must be the same length")
    index = [1.0]
    for i in range(1, len(real_prices)):
        if real_prices[i - 1] <= 0:
            raise ValueError(f"non-positive real price at position {i - 1}")
        index.append(
            index[-1]
            * (real_prices[i] + real_dividends[i] / 12.0)
            / real_prices[i - 1]
        )
    return index


def _ols(x: list[float], y: list[float]) -> tuple[float, float, float, float]:
    """Intercept, slope, r-squared, residual standard deviation."""
    n = len(x)
    if n < 3:
        raise ValueError("need at least three observations to fit a line")
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx == 0:
        raise ValueError("the regressor does not vary")
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    intercept = my - slope * mx
    residuals = [b - (intercept + slope * a) for a, b in zip(x, y)]
    ss_res = sum(r * r for r in residuals)
    ss_tot = sum((b - my) ** 2 for b in y)
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    return intercept, slope, r2, math.sqrt(ss_res / (n - 2))


def valuation_regression_estimate(
    cape_history: list[float],
    total_return_index: list[float],
    current_cape: float,
    horizon_years: int = 30,
    as_of: date | None = None,
) -> Estimate:
    """Fit realised subsequent real return on the cyclically adjusted yield.

    This is the Campbell and Shiller relation: buy cheap and you earn more. The
    regressor is 1/CAPE, the cyclically adjusted earnings yield, and the
    dependent variable is the annualised real total return actually realised
    over the following `horizon_years`.

    The horizon matters a great deal, and not in the direction people expect.
    The slope falls sharply with horizon, so a stretched valuation predicts a
    much weaker ten-year return than a thirty-year one. A lifetime model should
    use a long horizon.

    The standard error deserves care. The windows overlap almost completely, so
    the naive count of observations wildly overstates how much independent
    information is present. The error reported here divides the residual spread
    by the square root of the number of *non-overlapping* windows, which is a
    handful, not thousands.
    """
    months = horizon_years * 12
    if len(cape_history) != len(total_return_index):
        raise ValueError("CAPE history and return index must be the same length")
    if len(cape_history) <= months + 3:
        raise ValueError(
            f"need more than {horizon_years} years of history to fit a "
            f"{horizon_years} year horizon"
        )
    if current_cape <= 0:
        raise ValueError("CAPE must be positive")

    usable = len(cape_history) - months
    x = [1.0 / cape_history[i] for i in range(usable)]
    y = [
        (total_return_index[i + months] / total_return_index[i]) ** (1.0 / horizon_years)
        - 1.0
        for i in range(usable)
    ]
    intercept, slope, r2, residual_sd = _ols(x, y)
    independent = max(1, len(cape_history) // months)

    return Estimate(
        method=f"valuation regression, {horizon_years}y",
        value=intercept + slope * (1.0 / current_cape),
        as_of=as_of,
        detail=(
            f"CAPE {current_cape:.1f}, slope {slope:.2f}, R2 {r2:.2f}, "
            f"{usable} overlapping windows containing about {independent} "
            f"independent ones"
        ),
        standard_error=residual_sd / math.sqrt(independent),
        observations=usable,
        independent_observations=independent,
    )


# --- combining them ---------------------------------------------------------


def consensus(estimates: list[Estimate]) -> float:
    """The median of the estimates.

    A median rather than a mean because the three methods disagree by several
    percentage points and any one of them can be the outlier. A median is
    unmoved by which one that happens to be.
    """
    if not estimates:
        raise ValueError("no estimates to combine")
    return statistics.median(e.value for e in estimates)


def spread(estimates: list[Estimate]) -> float:
    """Highest minus lowest. The honest measure of how little is known."""
    if not estimates:
        raise ValueError("no estimates to compare")
    values = [e.value for e in estimates]
    return max(values) - min(values)
