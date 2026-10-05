"""The page's input logic, on the built page: tests/page_checks.mjs.

check_golden.mjs holds the model to the Python. The code around it, which
turns the fields, the ticks and the year-by-year box into households and
decides what to show when there is no answer, had no test at all, and a
review found four defects there that every other check passed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_the_page_turns_its_inputs_into_the_right_households() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; run tests/page_checks.mjs elsewhere")
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py")],
                   cwd=ROOT, check=True, capture_output=True)
    run = subprocess.run([node, str(ROOT / "tests" / "page_checks.mjs"), str(ROOT / "web")],
                         capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, run.stdout + run.stderr
