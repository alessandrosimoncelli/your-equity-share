"""Read the static market data file.

The model reads `config/market_data.toml` and never reaches the network. Data is
refreshed by `tools/refresh_market_data.py`, which is a separate program run
deliberately. A demo therefore cannot fail because a data provider is slow,
rate-limited or gone.

Every field carries the date it was observed and where it came from, because
the file mixes two kinds of input. Volatilities, correlations and interest rates
are estimated or downloaded. Forward price-to-earnings ratios are not available
from free price data and are entered by hand, so they go stale silently unless
their age is visible.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from merton_share.statistics import covariance_matrix

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "MarketData",
    "Sleeve",
    "StaleDataWarning",
    "load_market_data",
]

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "market_data.toml"
)

# A forward P/E older than this is reported as stale. Earnings estimates move
# slowly, but a figure from last year describes a different market.
FORWARD_PE_STALE_AFTER_DAYS = 120
RATE_STALE_AFTER_DAYS = 30


@dataclass(frozen=True)
class StaleDataWarning:
    field: str
    as_of: date
    age_days: int
    limit_days: int

    def __str__(self) -> str:
        return (
            f"{self.field} was observed {self.age_days} days ago "
            f"({self.as_of.isoformat()}), past the {self.limit_days} day limit"
        )


@dataclass(frozen=True)
class Sleeve:
    label: str
    ticker: str
    weight: float
    forward_pe: float
    forward_pe_as_of: date
    volatility: float

    @property
    def forward_earnings_yield(self) -> float:
        return 1.0 / self.forward_pe


@dataclass(frozen=True)
class MarketData:
    sleeves: tuple[Sleeve, ...]
    correlation: tuple[tuple[float, ...], ...]
    nominal_risk_free_rate: float
    expected_inflation: float
    rates_as_of: date
    covariance_as_of: date
    covariance_observations: int
    source_path: Path

    @property
    def weights(self) -> tuple[float, ...]:
        return tuple(s.weight for s in self.sleeves)

    @property
    def volatilities(self) -> tuple[float, ...]:
        return tuple(s.volatility for s in self.sleeves)

    @property
    def real_risk_free_rate(self) -> float:
        """Nominal rate less expected inflation.

        The forward earnings yield is a real return, so the safe rate it is
        compared against has to be real too.
        """
        return self.nominal_risk_free_rate - self.expected_inflation

    def covariance(self) -> list[list[float]]:
        return covariance_matrix(list(self.volatilities), [list(r) for r in self.correlation])

    def portfolio_variance(self) -> float:
        """w' Sigma w, the quantity the Merton denominator needs."""
        sigma = self.covariance()
        w = self.weights
        return sum(
            w[i] * w[j] * sigma[i][j] for i in range(len(w)) for j in range(len(w))
        )

    def stale_fields(self, today: date | None = None) -> list[StaleDataWarning]:
        """Every field older than its limit. Empty means the file is current."""
        today = today or datetime.now(timezone.utc).date()
        warnings: list[StaleDataWarning] = []

        for name, observed, limit in [
            ("risk-free rate and inflation", self.rates_as_of, RATE_STALE_AFTER_DAYS),
            ("covariance estimate", self.covariance_as_of, RATE_STALE_AFTER_DAYS),
        ]:
            age = (today - observed).days
            if age > limit:
                warnings.append(StaleDataWarning(name, observed, age, limit))

        for sleeve in self.sleeves:
            age = (today - sleeve.forward_pe_as_of).days
            if age > FORWARD_PE_STALE_AFTER_DAYS:
                warnings.append(
                    StaleDataWarning(
                        f"forward P/E for {sleeve.label}",
                        sleeve.forward_pe_as_of,
                        age,
                        FORWARD_PE_STALE_AFTER_DAYS,
                    )
                )
        return warnings


def _as_date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"{field}: expected a date, got {value!r}")


def load_market_data(path: Path | str | None = None) -> MarketData:
    """Load and validate the market data file.

    Raises ValueError on anything structurally wrong. Staleness is not an error,
    because a deliberately frozen file is a legitimate way to run the tool;
    call `stale_fields` to report it.
    """
    path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"no market data at {path}. Run tools/refresh_market_data.py to create it."
        )

    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    try:
        sleeve_rows = raw["sleeve"]
        cov = raw["covariance"]
        rates = raw["rates"]
    except KeyError as exc:
        raise ValueError(f"{path}: missing section {exc.args[0]!r}") from exc

    sleeves = tuple(
        Sleeve(
            label=row["label"],
            ticker=row["ticker"],
            weight=float(row["weight"]),
            forward_pe=float(row["forward_pe"]),
            forward_pe_as_of=_as_date(row["forward_pe_as_of"], "forward_pe_as_of"),
            volatility=float(row["volatility"]),
        )
        for row in sleeve_rows
    )

    if not sleeves:
        raise ValueError(f"{path}: no sleeves defined")

    total_weight = sum(s.weight for s in sleeves)
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError(f"{path}: sleeve weights sum to {total_weight}, not 1")

    correlation = tuple(tuple(float(v) for v in row) for row in cov["correlation"])
    size = len(sleeves)
    if len(correlation) != size or any(len(row) != size for row in correlation):
        raise ValueError(
            f"{path}: correlation matrix is {len(correlation)} rows, expected {size}"
        )
    for i in range(size):
        if abs(correlation[i][i] - 1.0) > 1e-12:
            raise ValueError(f"{path}: correlation[{i}][{i}] is not 1")
        for j in range(i + 1, size):
            if abs(correlation[i][j] - correlation[j][i]) > 1e-12:
                raise ValueError(f"{path}: correlation matrix is not symmetric at {i},{j}")
            if not -1.0 <= correlation[i][j] <= 1.0:
                raise ValueError(f"{path}: correlation[{i}][{j}] outside [-1, 1]")

    return MarketData(
        sleeves=sleeves,
        correlation=correlation,
        nominal_risk_free_rate=float(rates["nominal_risk_free"]),
        expected_inflation=float(rates["expected_inflation"]),
        rates_as_of=_as_date(rates["as_of"], "rates.as_of"),
        covariance_as_of=_as_date(cov["as_of"], "covariance.as_of"),
        covariance_observations=int(cov["observations"]),
        source_path=path,
    )
