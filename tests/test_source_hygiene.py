"""Guards against a class of bug that bit this project three times.

Patching source files through shell heredocs turned an intended `\b` word
boundary into a literal backspace byte more than once. The regex then silently
matched nothing and a parser returned an empty result instead of failing loudly.
These checks make that impossible to reintroduce unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(
    [*(ROOT / "src").rglob("*.py"), ROOT / "update.py", ROOT / "recommend.py"]
)

# Tab and newline are legitimate; everything else in this range is not.
FORBIDDEN = {c for c in range(0x00, 0x20)} - {0x09, 0x0A, 0x0D}


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_control_characters_in_source(path: Path) -> None:
    raw = path.read_bytes()
    found = {
        (i, byte)
        for i, byte in enumerate(raw)
        if byte in FORBIDDEN
    }
    if found:
        offset, byte = sorted(found)[0]
        line = raw[:offset].count(b"\n") + 1
        pytest.fail(
            f"{path.name} line {line} contains a control character "
            f"0x{byte:02x}. A backspace here is almost always a regex word "
            f"boundary that lost its backslash during a patch."
        )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_source_is_valid_utf8_and_parses(path: Path) -> None:
    import ast

    ast.parse(path.read_bytes().decode("utf-8"))
