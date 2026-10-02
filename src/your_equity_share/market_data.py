"""Read the static market data file.

The model needs three numbers, which are exactly the three Choi's user guide
asks for: the expected real return on the stock market, the real risk-free rate,
and the volatility of the stock market. They live in the `[market]` section and
that section alone is required.

The safe rate is stored as a *real* rate, taken from a long-dated TIPS yield.
Deriving it instead as a nominal yield less an inflation expectation invites a
maturity mismatch, since the obvious free sources are a 3-month bill and a
10-year breakeven, and subtracting one from the other produces neither a
3-month nor a 10-year real rate.

Sleeves and a correlation matrix are **optional**. CGM and Choi model a single
well-diversified equity holding, so one volatility is all the model consumes.
The optional sections exist only for a household that holds several funds and
would rather derive that one number from them than enter it directly. Nothing in
the model requires them, and `stock_volatility` is authoritative either way.

The model never reaches the network. Data is refreshed by
`update.py`, a separate program run deliberately, so a demo
cannot fail because a provider is slow or gone.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from your_equity_share.statistics import covariance_matrix
from your_equity_share.taxes import (
    ITALY_TAX,
    TaxRegime,
    after_tax_returns,
    deferral_years,
)

# The regimes a market file can name. Tax is the law, not market data, so the
# file only says which one applies; the rates live in taxes.py.
TAX_REGIMES = {"Italy": ITALY_TAX}

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "MarketData",
    "Sleeve",
    "StaleDataWarning",
    "load_market_data",
]

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "variants" / "us" / "market_data.toml"
)

STALE_AFTER_DAYS = 90


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
    """One fund in a multi-fund equity holding. Optional throughout."""

    label: str
    ticker: str
    weight: float
    volatility: float


@dataclass(frozen=True)
class MarketData:
    """The three inputs the model needs, plus optional detail behind one of them."""

    expected_stock_real_return: float
    real_risk_free_rate: float
    stock_volatility: float
    market_ticker: str
    as_of: date
    source_path: Path

    # How each number was obtained. Descriptive only; the model ignores it.
    provenance: dict = field(default_factory=dict)

    # Optional: present only when the equity holding is described fund by fund.
    sleeves: tuple[Sleeve, ...] = ()
    correlation: tuple[tuple[float, ...], ...] = ()
    covariance_as_of: date | None = None
    covariance_observations: int = 0

    # Where the returns are taxed, the regime and the inflation the tax is
    # levied through. The two returns above are always BEFORE tax: what a
    # household keeps depends on how long it holds, so it is worked out per
    # household by `returns_for`, never stored.
    tax_regime: TaxRegime | None = None
    expected_inflation: float | None = None

    def returns_for(self, ages) -> tuple[float, float]:
        """The expected return and safe rate this household's model reads.

        Untaxed variants hand back the two figures as stated. A taxed one
        taxes both funds on sale at the household's horizon: the sooner of
        thirty years and its expected remaining lifetime (taxes.py).
        """
        if self.tax_regime is None:
            return self.expected_stock_real_return, self.real_risk_free_rate
        return after_tax_returns(
            self.expected_stock_real_return, self.real_risk_free_rate,
            self.stock_volatility, self.expected_inflation,
            deferral_years(ages), self.tax_regime)

    @property
    def provisional_fields(self) -> tuple[str, ...]:
        """Inputs the configuration admits nobody has measured.

        The Italian variant ships with a safe rate and a volatility that were
        reasoned about rather than read off a market, and an answer built on
        those is not the same kind of object as one built on measured data.
        A tool that cannot tell the two apart will eventually present one as
        the other, so the distinction is carried in the data and surfaced
        everywhere the numbers are.
        """
        raw = self.provenance.get("provisional_fields", "")
        return tuple(f.strip() for f in str(raw).split(",") if f.strip())

    @property
    def is_provisional(self) -> bool:
        return bool(self.provisional_fields)

    @property
    def expected_return_is_market_implied(self) -> bool:
        """True when the expected return was derived from market data."""
        return self.provenance.get("expected_return_method") in {
            "implied",
            "consensus",
            "building blocks",
        }

    @property
    def expected_return_estimates(self) -> str:
        """The individual estimators behind a consensus figure, if recorded."""
        return str(self.provenance.get("expected_return_estimates", ""))

    @property
    def expected_return_spread(self) -> float:
        """Highest minus lowest across the estimators. Zero when set by hand."""
        try:
            return float(self.provenance.get("expected_return_spread", 0.0))
        except (TypeError, ValueError):
            return 0.0

    @property
    def expected_return_source(self) -> str:
        return str(
            self.provenance.get("expected_return_source", "set by hand")
        )

    @property
    def equity_risk_premium(self) -> float:
        """Expected real return above the real safe rate."""
        return self.expected_stock_real_return - self.real_risk_free_rate

    @property
    def has_sleeve_detail(self) -> bool:
        return bool(self.sleeves) and bool(self.correlation)

    def derived_stock_volatility(self) -> float:
        """Volatility implied by the optional sleeve breakdown.

        Raises if no breakdown is present. Compare against `stock_volatility`
        to see whether the number in use reflects the funds actually held.
        """
        if not self.has_sleeve_detail:
            raise ValueError(
                "no sleeve breakdown in this file; stock_volatility is the only "
                "volatility available"
            )
        weights = [s.weight for s in self.sleeves]
        sigma = covariance_matrix(
            [s.volatility for s in self.sleeves], [list(r) for r in self.correlation]
        )
        variance = sum(
            weights[i] * weights[j] * sigma[i][j]
            for i in range(len(weights))
            for j in range(len(weights))
        )
        return math.sqrt(variance)

    def stale_fields(self, today: date | None = None) -> list[StaleDataWarning]:
        """Every field older than its limit. Empty means the file is current."""
        today = today or datetime.now(timezone.utc).date()
        warnings: list[StaleDataWarning] = []

        age = (today - self.as_of).days
        if age > STALE_AFTER_DAYS:
            warnings.append(
                StaleDataWarning("market inputs", self.as_of, age, STALE_AFTER_DAYS)
            )

        if self.covariance_as_of is not None:
            age = (today - self.covariance_as_of).days
            if age > STALE_AFTER_DAYS:
                warnings.append(
                    StaleDataWarning(
                        "sleeve covariance",
                        self.covariance_as_of,
                        age,
                        STALE_AFTER_DAYS,
                    )
                )
        return warnings


def _as_date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"{field}: expected a date, got {value!r}")


def _load_optional_sleeves(
    raw: dict, path: Path
) -> tuple[tuple[Sleeve, ...], tuple[tuple[float, ...], ...], date | None, int]:
    rows = raw.get("sleeve")
    cov = raw.get("covariance")
    if not rows and not cov:
        return (), (), None, 0
    if not rows or not cov:
        raise ValueError(
            f"{path}: a sleeve breakdown needs both [[sleeve]] entries and a "
            f"[covariance] section, or neither"
        )

    sleeves = tuple(
        Sleeve(
            label=row["label"],
            ticker=row["ticker"],
            weight=float(row["weight"]),
            volatility=float(row["volatility"]),
        )
        for row in rows
    )

    total = sum(s.weight for s in sleeves)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"{path}: sleeve weights sum to {total}, not 1")

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
                raise ValueError(
                    f"{path}: correlation matrix is not symmetric at {i},{j}"
                )
            if not -1.0 <= correlation[i][j] <= 1.0:
                raise ValueError(f"{path}: correlation[{i}][{j}] outside [-1, 1]")

    return (
        sleeves,
        correlation,
        _as_date(cov["as_of"], "covariance.as_of"),
        int(cov["observations"]),
    )


def load_market_data(path: Path | str | None = None) -> MarketData:
    """Load and validate the market data file.

    The returns come back as the file states them, before tax. A file whose
    [market] names a tax_regime, as the Italian one does, also carries the
    inflation that tax is levied through, and `MarketData.returns_for` turns
    the pair into what a given household keeps.

    Raises ValueError on anything structurally wrong. Staleness is not an error,
    since a deliberately frozen file is a legitimate way to run the tool; call
    `stale_fields` to report it.
    """
    path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"no market data at {path}. Run: python update.py"
        )

    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    try:
        market = raw["market"]
    except KeyError as exc:
        raise ValueError(f"{path}: missing section 'market'") from exc

    try:
        expected = float(market["expected_stock_real_return"])
        real_rf = float(market["real_risk_free"])
        volatility = float(market["stock_volatility"])
        ticker = str(market.get("market_ticker", "SPY"))
    except KeyError as exc:
        raise ValueError(f"{path}: [market] is missing {exc.args[0]!r}") from exc

    # A file from before tax depended on the household stored one after-tax
    # pair, at a fixed thirty years. Reading it now would apply no tax at all,
    # silently, so it is refused instead.
    if "after_tax_expected_return" in market or "after_tax_real_risk_free" in market:
        raise ValueError(
            f"{path}: after-tax returns are no longer stored, because they depend "
            f"on the household's horizon. Name the regime with tax_regime and "
            f"give expected_inflation; tools/refresh_italy.py writes both."
        )
    regime_name = market.get("tax_regime")
    regime = None
    inflation = None
    if regime_name is not None:
        if regime_name not in TAX_REGIMES:
            raise ValueError(f"{path}: unknown tax_regime {regime_name!r}")
        regime = TAX_REGIMES[regime_name]
        if "expected_inflation" not in market:
            raise ValueError(
                f"{path}: tax_regime needs expected_inflation in [market], "
                f"because the tax falls on nominal gains"
            )
        inflation = float(market["expected_inflation"])

    if volatility <= 0:
        raise ValueError(f"{path}: stock_volatility must be positive")
    if expected <= real_rf:
        raise ValueError(
            f"{path}: expected_stock_real_return ({expected}) is not above "
            f"real_risk_free ({real_rf}), so there is no reason to hold equities"
        )

    sleeves, correlation, cov_as_of, observations = _load_optional_sleeves(raw, path)

    return MarketData(
        expected_stock_real_return=expected,
        real_risk_free_rate=real_rf,
        stock_volatility=volatility,
        market_ticker=ticker,
        as_of=_as_date(market["as_of"], "market.as_of"),
        source_path=path,
        provenance=dict(raw.get("provenance", {})),
        sleeves=sleeves,
        correlation=correlation,
        covariance_as_of=cov_as_of,
        covariance_observations=observations,
        tax_regime=regime,
        expected_inflation=inflation,
    )
