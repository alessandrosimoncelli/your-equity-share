"""Our answers against the ones stored in Choi's own spreadsheet.

The fixture is `tests/choi_workbook.json`, frozen from the "Wage imputed" tab
of the workbook by hand so this runs offline and does not depend on a file
sitting outside the repository.

The comparison uses the inputs the workbook itself stores. There is no formula
engine here, so its outputs correspond to its own inputs and those are what the
model must be fed. Volatility is 18.5%: the workbook has no volatility input
because that value is baked into the fitted coefficients.

Both the year-by-year earnings path and the three outputs are checked. The path
matters more than the outputs: a present value can come out right by luck from
a wrong path, and it localises any failure to the projection or the discounting
rather than leaving "the answer moved".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.allocation import Household, recommend  # noqa: E402
from your_equity_share.human_capital import Person, project_earnings  # noqa: E402

FIXTURE = Path(__file__).parent / "choi_workbook.json"


@pytest.fixture(scope="module")
def book() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def adults(book: dict) -> list[Person]:
    i = book["inputs"]
    return [
        Person(i["adult1_age"], i["adult1_wage"], i["adult1_benefit"]),
        Person(i["adult2_age"], i["adult2_wage"], i["adult2_benefit"]),
    ]


@pytest.fixture(scope="module")
def result(book: dict, adults: list[Person]):
    i = book["inputs"]
    household = Household(i["investable_net_worth"], adults, i["risk_aversion"])
    return recommend(
        household,
        i["expected_stock_real_return"],
        i["real_risk_free"],
        book["assumed_stock_volatility"],
    )


@pytest.mark.parametrize("who", ["adult1", "adult2"])
def test_projected_wages_match_the_workbook(book, adults, who) -> None:
    person = adults[0 if who == "adult1" else 1]
    expected = book["earnings"][who]
    ours = project_earnings(person)
    assert len(ours) == len(expected)
    for (age, wage, _benefit), year in zip(expected, ours):
        assert year.age == age
        # The workbook stores six significant figures, so a cent is the bar.
        assert year.wage == pytest.approx(wage, abs=0.05)


@pytest.mark.parametrize("who", ["adult1", "adult2"])
def test_projected_benefits_match_the_workbook(book, adults, who) -> None:
    person = adults[0 if who == "adult1" else 1]
    expected = book["earnings"][who]
    ours = project_earnings(person)
    for (age, _wage, benefit), year in zip(expected, ours):
        assert year.age == age
        assert year.benefit == pytest.approx(benefit, abs=0.05)


def test_equity_share_without_human_capital(book, result) -> None:
    """The Merton share alone, cell B32."""
    assert result.merton_share == pytest.approx(
        book["outputs"]["equity_share_without_human_capital"], rel=1e-9
    )


def test_human_capital_value(book, result) -> None:
    """Cell B30, both adults combined."""
    assert result.human_capital == pytest.approx(
        book["outputs"]["human_capital_value"], rel=1e-9
    )


def test_equity_portfolio_share(book, result) -> None:
    """The recommendation itself, cell B28."""
    assert result.equity_share == pytest.approx(
        book["outputs"]["equity_portfolio_share"], rel=1e-9
    )


def test_the_two_layers_multiply_to_the_answer(book, result) -> None:
    """The workbook's own three numbers are internally consistent, and so is
    our reproduction of them: the Merton share times one plus the human capital
    ratio gives the recommendation."""
    out = book["outputs"]
    implied = out["equity_share_without_human_capital"] * (
        1 + out["human_capital_value"] / book["inputs"]["investable_net_worth"]
    )
    assert implied == pytest.approx(out["equity_portfolio_share"], rel=1e-8)
    assert result.uncapped_share == pytest.approx(implied, rel=1e-8)


def test_the_benefit_is_forty_percent_of_the_final_wage(book) -> None:
    """The rule the guide states, visible in the workbook's own numbers."""
    for who in ("adult1", "adult2"):
        rows = book["earnings"][who]
        wages = [w for _age, w, _b in rows if w > 0]
        benefits = [b for _age, _w, b in rows if b > 0]
        if not benefits:
            continue
        assert benefits[0] == pytest.approx(wages[-1] * 0.40, abs=0.05)
        assert len(set(round(b, 4) for b in benefits)) == 1
