"""What Italian tax does to the equity share a household should choose.

The model reads market figures before tax, as Choi, Liu and Liu do. This
checks that for Italy, where the law taxes the two funds differently, by taking
them through the law as it is written and finding the best equity share
directly, with the tax and without it:

    the equity fund     a lognormal price with the market file's expected
                        return and volatility, taxed 26% on the nominal gain
                        when sold, with no credit for a loss
    the bond fund       the safe rate, taxed 12.5% on the nominal gain when
                        sold
    both                0.2% a year of imposta di bollo on the value

A household with risk aversion gamma holds both for `years`, sells, and the
share is the one that maximises expected CRRA utility of what it keeps. The
expectation is exact (Gauss-Hermite quadrature), so the figures are the same on
every run and the Italian methodology can quote them.

It reports, for each holding period:

    law        the best share with Italian tax, over the best without it
    mean only  the same ratio if tax lowered only the expected returns, which
               is what this variant did until October 2026
    cost       what ignoring the tax costs a household that pays it, in basis
               points a year of certainty-equivalent return
    loss       the probability that the equity fund is below cost when sold

    python tools/tax_check.py                 the Italian methodology's snapshot
    python tools/tax_check.py --live          today's market file

Held to a fixed date without rebalancing, so it is a check on one decision,
not a life-cycle solve.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.expected_return import compound_from_arithmetic  # noqa: E402
from your_equity_share.market_data import load_market_data  # noqa: E402
from your_equity_share.taxes import ITALY_TAX, NO_TAX, TaxRegime  # noqa: E402

SNAPSHOT = ROOT / "variants" / "it" / "snapshot.toml"
LIVE = ROOT / "variants" / "it" / "market_data.toml"
YEARS = (3, 7, 12, 18, 30)

_Z, _W = np.polynomial.hermite_e.hermegauss(161)
_W = _W / math.sqrt(2.0 * math.pi)


def _inputs(path: Path = SNAPSHOT) -> tuple[float, float, float, float]:
    market = load_market_data(path)
    inflation = float(market.provenance["expected_inflation"])
    return (market.expected_stock_real_return, market.real_risk_free_rate,
            market.stock_volatility, inflation)


def _kept(years: float, regime: TaxRegime, path: Path = SNAPSHOT):
    """What one euro in each fund is worth after `years`, after tax: the
    equity fund at each quadrature node, the bond fund as one number."""
    mu, rf, sigma, inflation = _inputs(path)
    levy = math.log(1.0 - regime.wealth_tax_rate)
    drift = math.log(1.0 + compound_from_arithmetic(mu, sigma)) + math.log(1.0 + inflation) + levy
    price = np.exp(years * drift + math.sqrt(years) * sigma * _Z)
    equity = price - regime.other_financial_income_rate * np.maximum(price - 1.0, 0.0)
    bond_price = math.exp(years * (math.log(1.0 + rf) + math.log(1.0 + inflation) + levy))
    bond = bond_price - regime.government_bond_rate * max(bond_price - 1.0, 0.0)
    return equity, bond


def _expected_utility(weight: float, equity, bond: float, gamma: float) -> float:
    wealth = weight * equity + (1.0 - weight) * bond
    return float(np.sum(_W * wealth ** (1.0 - gamma)) / (1.0 - gamma))


def _certainty_equivalent(weight: float, equity, bond: float, gamma: float) -> float:
    wealth = weight * equity + (1.0 - weight) * bond
    return float(np.sum(_W * wealth ** (1.0 - gamma))) ** (1.0 / (1.0 - gamma))


def best_weight(years: float, gamma: float, regime: TaxRegime,
                path: Path = SNAPSHOT) -> float:
    """The equity share that maximises expected utility, searched on [0, 1]."""
    equity, bond = _kept(years, regime, path)
    low, high = 0.0, 1.0
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    for _ in range(80):
        a = high - golden * (high - low)
        b = low + golden * (high - low)
        if _expected_utility(a, equity, bond, gamma) < _expected_utility(b, equity, bond, gamma):
            low = a
        else:
            high = b
    return (low + high) / 2.0


def law_ratio(years: float, gamma: float = 5.0, path: Path = SNAPSHOT) -> float:
    """The best share with Italian tax, over the best without it."""
    return (best_weight(years, gamma, ITALY_TAX, path)
            / best_weight(years, gamma, NO_TAX, path))


def mean_only_ratio(years: float, path: Path = SNAPSHOT) -> float:
    """Merton's share with tax taken off the expected returns only, over his
    share before tax: the accrual-equivalent returns of both funds sold after
    `years`, the volatility left as it is."""
    mu, rf, sigma, inflation = _inputs(path)

    def kept(real: float, rate: float) -> float:
        growth = (1.0 + real) * (1.0 + inflation) * (1.0 - ITALY_TAX.wealth_tax_rate)
        taxed = 1.0 + (1.0 - rate) * (growth ** years - 1.0)
        return (taxed / (1.0 + inflation) ** years) ** (1.0 / years) - 1.0

    compound = kept(compound_from_arithmetic(mu, sigma), ITALY_TAX.other_financial_income_rate)
    mu_after = (1.0 + compound) * math.exp(0.5 * sigma ** 2) - 1.0
    rf_after = kept(rf, ITALY_TAX.government_bond_rate)
    before = math.log(1.0 + mu) - math.log(1.0 + rf)
    after = math.log(1.0 + mu_after) - math.log(1.0 + rf_after)
    return after / before


def cost_of_ignoring(years: float, gamma: float = 5.0, path: Path = SNAPSHOT) -> float:
    """Basis points a year lost by a household that pays the tax but holds the
    share that would be best without it."""
    equity, bond = _kept(years, ITALY_TAX, path)
    taxed = best_weight(years, gamma, ITALY_TAX, path)
    untaxed = best_weight(years, gamma, NO_TAX, path)
    ratio = (_certainty_equivalent(taxed, equity, bond, gamma)
             / _certainty_equivalent(untaxed, equity, bond, gamma))
    return (ratio ** (1.0 / years) - 1.0) * 1e4


def loss_probability(years: float, path: Path = SNAPSHOT) -> float:
    """The chance the equity fund is below cost when it is sold."""
    mu, _, sigma, inflation = _inputs(path)
    drift = (math.log(1.0 + compound_from_arithmetic(mu, sigma)) + math.log(1.0 + inflation)
             + math.log(1.0 - ITALY_TAX.wealth_tax_rate))
    return 0.5 * math.erfc(years * drift / (math.sqrt(years) * sigma) / math.sqrt(2.0))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="use today's market file")
    args = parser.parse_args(argv[1:])
    path = LIVE if args.live else SNAPSHOT
    print(f"{path.relative_to(ROOT)}; risk aversion 5 unless stated")
    print(f"{'years':>5}  {'law':>6}  {'mean only':>9}  {'cost bp':>7}  {'loss':>6}   law at gamma 3 / 8")
    for years in YEARS:
        print(f"{years:>5}  {law_ratio(years, 5.0, path):6.3f}  {mean_only_ratio(years, path):9.3f}"
              f"  {cost_of_ignoring(years, 5.0, path):7.2f}  {loss_probability(years, path):6.1%}"
              f"   {law_ratio(years, 3.0, path):.3f} / {law_ratio(years, 8.0, path):.3f}")
    print(f"best share without tax at 30 years, gamma 5: {best_weight(30, 5.0, NO_TAX, path):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
