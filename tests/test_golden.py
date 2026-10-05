"""The Python of the day against the committed golden fixture.

tools/check_golden.mjs holds the JavaScript to tests/golden.json, and the
fixture is written by the Python. Nothing held the Python to it: a change to
the model that was not followed by a new fixture left the JavaScript matching
an old Python, and both checks passed. This recomputes every case.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import make_golden  # noqa: E402


def _differences(got, want, where="cases", out=None):
    """Every place two JSON trees differ, numbers to 1e-12 relative, since
    another platform's exp and log may differ in the last bit."""
    out = [] if out is None else out
    if isinstance(want, dict) and isinstance(got, dict):
        if set(got) != set(want):
            out.append(f"{where}: keys {sorted(set(got) ^ set(want))}")
        for key in set(got) & set(want):
            _differences(got[key], want[key], f"{where}.{key}", out)
    elif isinstance(want, list) and isinstance(got, list):
        if len(got) != len(want):
            out.append(f"{where}: {len(got)} items, the fixture has {len(want)}")
        for i, (g, w) in enumerate(zip(got, want)):
            _differences(g, w, f"{where}[{i}]", out)
    elif (isinstance(want, (int, float)) and isinstance(got, (int, float))
          and not isinstance(want, bool) and not isinstance(got, bool)):
        if not math.isclose(got, want, rel_tol=1e-12, abs_tol=1e-12):
            out.append(f"{where}: {got!r} against {want!r}")
    elif got != want:
        out.append(f"{where}: {got!r} against {want!r}")
    return out


def test_the_python_still_writes_the_committed_fixture() -> None:
    fixture = json.loads((ROOT / "tests" / "golden.json").read_text(encoding="utf-8"))
    fresh = json.loads(json.dumps(make_golden.all_cases()))
    problems = _differences(fresh, fixture["cases"])
    assert not problems, (
        "the model no longer writes tests/golden.json; run tools/make_golden.py "
        "if the change is meant:\n  " + "\n  ".join(problems[:10]))
