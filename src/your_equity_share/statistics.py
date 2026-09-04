"""Return statistics over a price series.

Pure functions. No network, no file access, no dependencies, so the refresh
tool and the model both use the same estimator and the tests run offline.

Volatility is estimated from **dividend-adjusted** closes, so successive ratios
are total returns. `parse_price_json` prefers Yahoo's `adjclose` for exactly
that reason: a split-only series leaves a small downward step on every
ex-dividend day, which on five years of SPY overstates annual volatility by
about four basis points.

The expected return is not estimated here and never from this series. It is
built three independent ways in `expected_return`, and the median is taken.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "TRADING_DAYS_PER_YEAR",
    "PriceSeriesProblem",
    "align_series",
    "annualised_volatility",
    "correlation_matrix",
    "covariance_matrix",
    "log_returns",
    "validate_prices",
]

TRADING_DAYS_PER_YEAR = 252

# A single day's log return larger than this is treated as a data fault rather
# than a market move. Even the worst sessions on record sit well inside it, so a
# breach almost always means an unadjusted split, a currency change part-way
# through a series, or a bad tick around a listing date.
MAX_PLAUSIBLE_DAILY_LOG_RETURN = 0.25


@dataclass(frozen=True)
class PriceSeriesProblem:
    """One reason a series should not be used."""

    ticker: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.ticker}: {self.kind}: {self.detail}"


def log_returns(prices: list[float]) -> list[float]:
    """Daily log returns from a price series in chronological order."""
    if len(prices) < 2:
        return []
    return [math.log(b / a) for a, b in zip(prices, prices[1:])]


def annualised_volatility(
    returns: list[float], periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """Sample standard deviation of `returns`, scaled to one year.

    Uses the n-1 denominator. Scaling by the square root of the period count
    assumes returns are independent across days, which is the same assumption
    the allocation model makes.
    """
    n = len(returns)
    if n < 2:
        raise ValueError("need at least two returns to estimate a standard deviation")
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(variance) * math.sqrt(periods_per_year)


def correlation_matrix(series: list[list[float]]) -> list[list[float]]:
    """Pearson correlations between equal-length return series."""
    if not series:
        return []
    lengths = {len(s) for s in series}
    if len(lengths) != 1:
        raise ValueError(f"series have differing lengths: {sorted(lengths)}")
    if lengths.pop() < 2:
        raise ValueError("need at least two observations per series")

    n = len(series[0])
    means = [sum(s) / n for s in series]
    deviations = [[v - m for v in s] for s, m in zip(series, means)]
    norms = [math.sqrt(sum(d * d for d in dev)) for dev in deviations]

    size = len(series)
    out = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i, size):
            if norms[i] == 0.0 or norms[j] == 0.0:
                raise ValueError(f"series {i if norms[i] == 0 else j} does not vary")
            rho = sum(a * b for a, b in zip(deviations[i], deviations[j])) / (
                norms[i] * norms[j]
            )
            # Clamp to remove floating point overshoot on the diagonal.
            rho = max(-1.0, min(1.0, rho))
            out[i][j] = out[j][i] = rho
    for i in range(size):
        out[i][i] = 1.0
    return out


def covariance_matrix(
    volatilities: list[float], correlations: list[list[float]]
) -> list[list[float]]:
    """Assemble Sigma from annualised volatilities and a correlation matrix."""
    size = len(volatilities)
    if len(correlations) != size or any(len(row) != size for row in correlations):
        raise ValueError("correlation matrix shape does not match volatilities")
    return [
        [volatilities[i] * volatilities[j] * correlations[i][j] for j in range(size)]
        for i in range(size)
    ]


def align_series(
    series_by_ticker: dict[str, dict[str, float]],
) -> tuple[list[str], dict[str, list[float]]]:
    """Restrict every series to the dates all of them share.

    Takes {ticker: {date: close}} and returns the sorted common dates together
    with each series over exactly those dates. Correlations estimated on
    differing calendars are not comparable, and markets in different countries
    keep different holidays, so this step is not optional.
    """
    if not series_by_ticker:
        return [], {}
    common = set.intersection(*(set(s) for s in series_by_ticker.values()))
    dates = sorted(common)
    return dates, {t: [s[d] for d in dates] for t, s in series_by_ticker.items()}


def validate_prices(
    ticker: str,
    dates: list[str],
    prices: list[float],
    minimum_observations: int = 250,
) -> list[PriceSeriesProblem]:
    """Report every reason `prices` should not be trusted.

    Returns an empty list when the series is usable. Checks are deliberately
    blunt: they catch the faults that silently corrupt a covariance estimate
    rather than trying to judge whether a move was real.
    """
    problems: list[PriceSeriesProblem] = []

    if len(prices) < minimum_observations:
        problems.append(
            PriceSeriesProblem(
                ticker,
                "too short",
                f"{len(prices)} observations, need at least {minimum_observations}",
            )
        )

    non_positive = [d for d, p in zip(dates, prices) if p <= 0]
    if non_positive:
        problems.append(
            PriceSeriesProblem(
                ticker,
                "non-positive price",
                f"{len(non_positive)} on {', '.join(non_positive[:3])}",
            )
        )

    if len(dates) != len(set(dates)):
        problems.append(
            PriceSeriesProblem(ticker, "duplicate dates", "series contains repeats")
        )

    if dates != sorted(dates):
        problems.append(
            PriceSeriesProblem(ticker, "out of order", "dates are not ascending")
        )

    if all(p > 0 for p in prices) and len(prices) >= 2:
        jumps = [
            (dates[i + 1], r)
            for i, r in enumerate(log_returns(prices))
            if abs(r) > MAX_PLAUSIBLE_DAILY_LOG_RETURN
        ]
        if jumps:
            worst = max(jumps, key=lambda j: abs(j[1]))
            problems.append(
                PriceSeriesProblem(
                    ticker,
                    "implausible jump",
                    f"{len(jumps)} day(s) beyond "
                    f"{MAX_PLAUSIBLE_DAILY_LOG_RETURN:.0%}, worst "
                    f"{worst[1]:+.1%} on {worst[0]}; usually an unadjusted split "
                    f"or a currency change part-way through the series",
                )
            )

    return problems
