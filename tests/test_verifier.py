"""The verifier has to work on a machine that is not the author's.

Part four compares this project's answers against Choi's own spreadsheet, which
is his and not ours to redistribute, so the repository does not carry it. That
made the path a hazard: it was hardcoded to one directory on one machine, and a
clean clone recorded a FAILED check and exited 1. Someone running the checks for
the first time was told the model is broken when the only thing missing was a
file they were never given.

These tests fix the behaviour in place: the workbook is found by search or by
an environment variable, and its absence is a skip rather than a failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools" / "verify_model.py"

sys.path.insert(0, str(ROOT / "tools"))


def run_verifier(workbook: str | None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if workbook is None:
        env.pop("CHOI_WORKBOOK", None)
    else:
        env["CHOI_WORKBOOK"] = workbook
    return subprocess.run(
        [sys.executable, str(VERIFIER)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


def test_a_missing_workbook_is_a_skip_and_not_a_failure() -> None:
    """The whole point: a stranger's first run must not report a failure.

    Exit code included, because that is what a continuous integration run
    reads, and a red build over a file nobody has is worse than no build.
    """
    result = run_verifier("Z:/not/a/real/path/nothing.xlsx")
    assert result.returncode == 0, result.stdout[-2000:]
    assert "SKIP" in result.stdout
    assert "skipped" in result.stdout
    assert "0 failed" in result.stdout


def test_the_skip_says_what_is_missing_and_how_to_supply_it() -> None:
    """A skip that does not say what to do about it is just a silence."""
    result = run_verifier("Z:/not/a/real/path/nothing.xlsx")
    assert "CHOI_WORKBOOK" in result.stdout
    assert "Choi, Liu and Liu (2025)" in result.stdout


def test_the_other_four_parts_still_run_without_the_workbook() -> None:
    """Skipping part four must not skip anything else.

    The count is not asserted exactly, since checks get added. What is
    asserted is that every other part reached its own heading and that a
    substantial number of checks passed, so a skip cannot quietly become an
    early return.
    """
    result = run_verifier("Z:/not/a/real/path/nothing.xlsx")
    for heading in ("1. The model", "2. Market data", "3. The expected return",
                    "5. The methodology document"):
        assert heading in result.stdout, heading
    passed = int(result.stdout.split(" passed,")[0].split("\n")[-1])
    assert passed > 50, f"only {passed} checks ran without the workbook"


def test_an_explicit_override_is_not_second_guessed() -> None:
    """A wrong CHOI_WORKBOOK must report itself, not find another copy.

    Falling back to a search after an explicit path would mean checking a
    file the caller did not ask for while telling them it was theirs.
    """
    import verify_model

    candidates = verify_model.workbook_candidates("Z:/somewhere/else.xlsx")
    assert candidates == [Path("Z:/somewhere/else.xlsx")]


def test_without_an_override_the_workbook_is_searched_for() -> None:
    import verify_model

    candidates = verify_model.workbook_candidates(None)
    assert len(candidates) == 2
    assert all(c.name == verify_model.WORKBOOK_NAME for c in candidates)
    assert not any(c.is_absolute() and "LORENZO" in str(c).upper()
                   for c in candidates if not str(c).startswith(str(ROOT.parent)))


def test_the_verifier_carries_no_path_from_one_particular_machine() -> None:
    """The defect itself, asserted directly.

    This is the line that shipped: a path under one user's home directory,
    committed to a public repository.
    """
    source = VERIFIER.read_text(encoding="utf-8")
    assert "C:\\Users" not in source
    assert "C:/Users" not in source


@pytest.mark.skipif(
    not (ROOT.parent / "Chai - Yale.xlsx").exists(),
    reason="Choi's workbook is not present on this machine",
)
def test_the_workbook_is_still_found_where_the_author_keeps_it() -> None:
    """The other direction: the search must keep working here.

    Making the path portable is worthless if it stops finding the file that
    is actually there, since part four is 58 of the strongest checks in the
    project.
    """
    result = run_verifier(None)
    assert result.returncode == 0, result.stdout[-2000:]
    assert "SKIP" not in result.stdout
    assert 'tab "Wage imputed"' in result.stdout
