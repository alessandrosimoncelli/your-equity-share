"""The JavaScript port must agree with the Python, and the fixture must be current.

The browser runs `src/js/model.js`; everything validated against Choi's
spreadsheet is Python. Two implementations drift unless something checks them.

Two failure modes, one test each:

    the port drifted        model.js no longer reproduces tests/golden.json
    the fixture went stale  the Python changed and nobody regenerated it

The second is the sneakier one. A fixture regenerated from a changed Python
would keep the port passing while the port silently no longer matches the
model the tests actually exercise.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from your_equity_share.allocation import (  # noqa: E402
    Household,
    merton_share,
    recommend,
)
from your_equity_share.human_capital import (  # noqa: E402
    Person,
    benefit_discount_rate,
    human_capital,
    imputed_wage,
    wage_discount_rate,
)
from your_equity_share.risk_aversion import (  # noqa: E402
    certainty_equivalent,
    gamma_from_certainty_equivalent,
)

GOLDEN = ROOT / "tests" / "golden.json"
CHECKER = ROOT / "tools" / "check_golden.mjs"
MODEL_JS = ROOT / "src" / "js" / "model.js"


@pytest.fixture(scope="module")
def fixture() -> dict:
    if not GOLDEN.exists():
        pytest.fail(f"{GOLDEN} is missing. Run: python tools/make_golden.py")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_the_port_and_the_checker_exist() -> None:
    assert MODEL_JS.exists(), "the browser front end has no model to run"
    assert CHECKER.exists()


def test_javascript_reproduces_python() -> None:
    """Runs the port against the fixture. Skipped where Node is absent, since
    the model itself does not need it and a contributor without Node should
    still be able to run the suite."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; run tools/check_golden.mjs elsewhere")

    result = subprocess.run(
        [node, str(CHECKER)], capture_output=True, text=True, cwd=ROOT
    )
    if result.returncode != 0:
        pytest.fail(
            "the JavaScript port no longer reproduces the Python:\n"
            f"{result.stdout}\n{result.stderr}"
        )


# --- the fixture must still describe the current Python ---------------------


def test_fixture_still_matches_merton_share(fixture: dict) -> None:
    for case in fixture["cases"]["merton_share"]:
        mu, rf, gamma, sigma = case["args"]
        assert merton_share(mu, rf, gamma, sigma) == pytest.approx(
            case["expect"], rel=1e-12
        )


def test_fixture_still_matches_discount_rates(fixture: dict) -> None:
    for case in fixture["cases"]["wage_discount_rate"]:
        age, gamma, mu, rf = case["args"]
        assert wage_discount_rate(age, gamma, mu, rf) == pytest.approx(
            case["expect"], rel=1e-12
        )
    for case in fixture["cases"]["benefit_discount_rate"]:
        age, gamma, mu, rf = case["args"]
        assert benefit_discount_rate(age, gamma, mu, rf) == pytest.approx(
            case["expect"], rel=1e-12
        )


def test_fixture_still_matches_imputed_wage(fixture: dict) -> None:
    for case in fixture["cases"]["imputed_wage"]:
        age, current_age, current_wage = case["args"]
        assert imputed_wage(age, current_age, current_wage) == pytest.approx(
            case["expect"], rel=1e-12
        )


def test_fixture_still_matches_risk_aversion(fixture: dict) -> None:
    for case in fixture["cases"]["certainty_equivalent"]:
        assert certainty_equivalent(case["args"][0]) == pytest.approx(
            case["expect"], rel=1e-12
        )
    for case in fixture["cases"]["gamma_from_certainty_equivalent"]:
        assert gamma_from_certainty_equivalent(case["args"][0]) == pytest.approx(
            case["expect"], rel=1e-12
        )


def test_fixture_still_matches_human_capital(fixture: dict) -> None:
    for case in fixture["cases"]["human_capital"]:
        p = case["person"]
        person = Person(p["current_age"], p["current_wage"], p["current_benefit"])
        gamma, mu, rf = case["args"]
        assert human_capital(person, gamma, mu, rf) == pytest.approx(
            case["expect"], rel=1e-12
        )


def test_fixture_still_matches_the_recommendation(fixture: dict) -> None:
    for case in fixture["cases"]["recommend"]:
        adults = [
            Person(a["current_age"], a["current_wage"], a["current_benefit"])
            for a in case["household"]["adults"]
        ]
        household = Household(
            case["household"]["investable_net_worth"],
            adults,
            case["household"]["risk_aversion"],
        )
        mu, rf, sigma = case["args"]
        result = recommend(household, mu, rf, sigma)
        expect = case["expect"]
        assert result.equity_share == pytest.approx(expect["equity_share"], rel=1e-12)
        assert result.merton_share == pytest.approx(expect["merton_share"], rel=1e-12)
        assert result.human_capital == pytest.approx(expect["human_capital"], rel=1e-12)
        assert result.uncapped_share == pytest.approx(expect["uncapped_share"], rel=1e-12)
        assert result.is_capped is expect["is_capped"]


def test_the_calibration_recorded_in_the_fixture_is_current(fixture: dict) -> None:
    from your_equity_share.human_capital import CGM_CALIBRATION

    recorded = fixture["calibration"]
    assert recorded["stock_volatility"] == CGM_CALIBRATION.stock_volatility
    assert recorded["permanent_shock_volatility"] == (
        CGM_CALIBRATION.permanent_shock_volatility
    )
    assert recorded["temporary_shock_volatility"] == (
        CGM_CALIBRATION.temporary_shock_volatility
    )
    assert recorded["wage_equity_beta"] == CGM_CALIBRATION.wage_equity_beta
    assert recorded["benefit_replacement_rate"] == (
        CGM_CALIBRATION.benefit_replacement_rate
    )
