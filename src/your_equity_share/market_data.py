"""Read the static market data file.

The model needs three numbers: the expected real return on the stock market
and the real risk-free rate, which Choi's user guide asks for, and the
volatility of the stock market, which his spreadsheet fixes at 18.5% inside its
formulas. They live in the `[market]` section and
that section alone is required.

The safe rate is stored as a *real* rate. The American variant reads it off
the 30-year TIPS yield. The Italian one takes a 30-year nominal yield less the
market break-even of the longest German linker, which keeps both legs long:
the obvious free American pair, a 3-month bill and a 10-year breakeven, would
produce neither a 3-month nor a 10-year real rate.

The model never reaches the network. Data is refreshed by
`update.py`, a separate program run deliberately, so a demo
cannot fail because a provider is slow or gone.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "MarketData",
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
class MarketData:
    """The three inputs the model needs."""

    expected_stock_real_return: float
    real_risk_free_rate: float
    stock_volatility: float
    as_of: date
    source_path: Path

    # How each number was obtained. Descriptive only; the model ignores it.
    provenance: dict = field(default_factory=dict)

    @property
    def provisional_fields(self) -> tuple[str, ...]:
        """Inputs the configuration admits nobody has measured.

        None is today. The Italian variant once shipped a safe rate and a
        volatility that had been reasoned about rather than read off a market,
        and an answer built on those is not the same kind of object as one
        built on measured data, so a guess put in by hand is marked here, and
        the Italian refresh clears the mark when it writes a measured rate.
        """
        raw = self.provenance.get("provisional_fields", "")
        return tuple(f.strip() for f in str(raw).split(",") if f.strip())

    @property
    def is_provisional(self) -> bool:
        return bool(self.provisional_fields)

    @property
    def equity_risk_premium(self) -> float:
        """Expected real return above the real safe rate."""
        return self.expected_stock_real_return - self.real_risk_free_rate

    def stale_fields(self, today: date | None = None) -> list[StaleDataWarning]:
        """Every field older than its limit. Empty means the file is current."""
        today = today or datetime.now(timezone.utc).date()
        warnings: list[StaleDataWarning] = []

        age = (today - self.as_of).days
        if age > STALE_AFTER_DAYS:
            warnings.append(
                StaleDataWarning("market inputs", self.as_of, age, STALE_AFTER_DAYS)
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

    The returns come back as the file states them, before tax, which is what
    the model reads in both variants (taxes.py says why).

    Raises ValueError on anything structurally wrong. Staleness is not an error,
    since a deliberately frozen file is a legitimate way to run the tool; call
    `stale_fields` to report it.

    Keys the model does not read are ignored rather than refused. `update.py`
    loads the existing file before it writes the new one, so a file still
    carrying a key that has since been dropped has to load, or the refresh
    that would rewrite it without that key could not run.
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
    except KeyError as exc:
        raise ValueError(f"{path}: [market] is missing {exc.args[0]!r}") from exc

    if volatility <= 0:
        raise ValueError(f"{path}: stock_volatility must be positive")
    if expected <= real_rf:
        raise ValueError(
            f"{path}: expected_stock_real_return ({expected}) is not above "
            f"real_risk_free ({real_rf}), so there is no reason to hold equities"
        )

    return MarketData(
        expected_stock_real_return=expected,
        real_risk_free_rate=real_rf,
        stock_volatility=volatility,
        as_of=_as_date(market["as_of"], "market.as_of"),
        source_path=path,
        provenance=dict(raw.get("provenance", {})),
    )
