"""Section 3.3 of Choi, Liu and Liu (2025), the paper's own worked example.

This is a stronger check than the spreadsheet comparison in two ways.

It is independent of the spreadsheet. The workbook could implement the paper
wrongly and our matching it would prove only that we copied the same mistake.
The paper states its intermediate values, so each layer is checked separately:
two wage discount rates, one benefit discount rate, the human capital total,
the Merton share, the multiplier and the final allocation.

And it exercises the path where wages and benefits are supplied year by year
rather than imputed from one salary. That is the workbook's "Full inputs" mode,
and nothing else in the suite covers it.

It also fixes the units question. The paper works in *log* quantities: a log
risk-free rate of 2% and a log equity premium of 2%. It states the conversion
itself, in footnote 12 and in the text:

    level equity premium = exp(r_f + pi + sigma^2 / 2) - exp(r_f) = 3.86%

so the model's expected return input is a *level*, that is arithmetic, return.
That is why the refresh converts its compound estimates before writing them,
and why log_premium subtracts sigma^2 / 2 while merton_share does not.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from your_equity_share.allocation import (  # noqa: E402
    Household,
    merton_share,
    recommend,
)
from your_equity_share.expected_return import log_premium  # noqa: E402
from your_equity_share.human_capital import (  # noqa: E402
    Person,
    benefit_discount_rate,
    human_capital,
    wage_discount_rate,
)

# The paper's stated parameters.
SIGMA = 0.185
LOG_RISK_FREE = 0.02
LOG_EQUITY_PREMIUM = 0.02
RISK_AVERSION = 7.0
AGE = 55
PORTFOLIO = 1_000_000.0

# Converted to the level returns the interface takes, using the paper's own
# expression for the conversion.
REAL_RISK_FREE = math.exp(LOG_RISK_FREE) - 1.0
EXPECTED_RETURN = math.exp(LOG_RISK_FREE + LOG_EQUITY_PREMIUM + 0.5 * SIGMA**2) - 1.0


@pytest.fixture(scope="module")
def person() -> Person:
    """$100,000 a year through 66, then a $40,000 benefit for life."""
    return Person(
        AGE,
        100_000.0,
        0.0,
        wages={age: 100_000.0 for age in range(AGE + 1, 67)},
        benefits={age: 40_000.0 for age in range(67, 101)},
    )


def test_the_level_equity_premium_conversion() -> None:
    """Paper: exp(0.02+0.02+0.5x0.185^2) - exp(0.02) = 3.86%."""
    level = (1.0 + EXPECTED_RETURN) - (1.0 + REAL_RISK_FREE)
    assert level == pytest.approx(0.0386, abs=5e-5)


def test_log_premium_recovers_the_paper_s_pi() -> None:
    """Round trip: converting the level return back gives 2% again."""
    assert log_premium(EXPECTED_RETURN, REAL_RISK_FREE, SIGMA) == pytest.approx(
        LOG_EQUITY_PREMIUM, abs=1e-12
    )


@pytest.mark.parametrize("age", [56, 57])
def test_wage_discount_rate_matches_the_paper(age: int) -> None:
    """Paper states 0.0981 for both, computed from the third column of Table 1."""
    rate = wage_discount_rate(age, RISK_AVERSION, EXPECTED_RETURN, REAL_RISK_FREE)
    assert rate == pytest.approx(0.0981, abs=5e-5)


def test_benefit_discount_rate_matches_the_paper() -> None:
    """Paper states 0.0334, from the third column of Table 2."""
    rate = benefit_discount_rate(67, RISK_AVERSION, EXPECTED_RETURN, REAL_RISK_FREE)
    assert rate == pytest.approx(0.0334, abs=5e-5)


def test_human_capital_matches_the_paper(person: Person) -> None:
    """Paper states $924,805."""
    value = human_capital(person, RISK_AVERSION, EXPECTED_RETURN, REAL_RISK_FREE)
    assert value == pytest.approx(924_805.0, abs=1.0)


def test_merton_share_matches_the_paper() -> None:
    """Paper: "her optimal equity share would be given by equation (8) as 15.5%"."""
    beta = merton_share(EXPECTED_RETURN, REAL_RISK_FREE, RISK_AVERSION, SIGMA)
    assert beta == pytest.approx(0.155, abs=5e-4)


def test_the_multiplier_matches_the_paper(person: Person) -> None:
    """Paper: 1 + H/W = 1 + 924,805/1,000,000 = 1.92."""
    value = human_capital(person, RISK_AVERSION, EXPECTED_RETURN, REAL_RISK_FREE)
    assert 1.0 + value / PORTFOLIO == pytest.approx(1.92, abs=5e-3)


def test_the_recommendation_matches_the_paper(person: Person) -> None:
    """Paper: "giving an optimal equity share of 30%"."""
    result = recommend(
        Household(PORTFOLIO, [person], RISK_AVERSION),
        EXPECTED_RETURN,
        REAL_RISK_FREE,
        SIGMA,
    )
    assert result.equity_share == pytest.approx(0.30, abs=2e-3)


def test_supplied_wages_override_the_imputed_path(person: Person) -> None:
    """The point of this example: the wages are given, not imputed from one
    salary. Without that the CGM cubic would produce a rising then falling
    profile rather than the flat $100,000 the paper specifies."""
    from your_equity_share.human_capital import imputed_wage, project_earnings

    years = {y.age: y for y in project_earnings(person)}
    assert years[60].wage == 100_000.0
    assert years[66].wage == 100_000.0
    assert years[67].wage == 0.0
    assert years[67].benefit == 40_000.0
    assert years[100].benefit == 40_000.0
    # The imputed path would have disagreed, which is what makes this a
    # genuine test of the supplied-values branch.
    assert imputed_wage(60, AGE, 100_000.0) != pytest.approx(100_000.0, abs=100.0)
