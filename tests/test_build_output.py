"""What `tools/build_web.py` puts in the folder that gets uploaded.

Every other test in this suite exercises the model. None of them looked at the
build output, and a change to the build shipped a `model.js` that began
`<!doctype html>`, which took the whole site down with "Unexpected token '<'".
The unit tests passed, the golden fixture passed, the workbook checks passed,
and the site did not load, because nothing here had ever opened the built files.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web"
ZIP = ROOT / "your-equity-share-site.zip"
EXPECTED = {"index.html", "model.js", "market.json", "methodology.html"}


@pytest.fixture(scope="module")
def built() -> Path:
    """Run the real build once, so these assertions are about real output."""
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_web.py")],
        cwd=ROOT, check=True, capture_output=True,
    )
    return OUT


def test_the_folder_holds_exactly_the_four_files(built: Path) -> None:
    assert {p.name for p in built.iterdir() if p.is_file()} == EXPECTED


def test_the_model_is_javascript_and_not_a_web_page(built: Path) -> None:
    """The regression that broke the site. A module served as HTML fails to
    parse and nothing downstream of the import ever runs."""
    body = (built / "model.js").read_text(encoding="utf-8")
    assert not body.lstrip().startswith("<")
    assert "<!doctype" not in body.lower()
    assert "export function recommend(" in body


def test_the_json_is_json_and_carries_what_the_page_reads(built: Path) -> None:
    data = json.loads((built / "market.json").read_text(encoding="utf-8"))
    for key in ("expected_stock_real_return", "real_risk_free",
                "stock_volatility", "as_of"):
        assert key in data, key
    assert 0.0 < data["expected_stock_real_return"] < 0.25
    assert 0.0 < data["stock_volatility"] < 1.0


@pytest.mark.parametrize("name", ["index.html", "methodology.html"])
def test_each_page_is_a_whole_document(built: Path, name: str) -> None:
    """A static host supplies no head, and the files also get opened from disk.

    Without a charset "Pastor and Stambaugh" renders as mojibake, and without a
    viewport a phone lays the page out at 980px and zooms out.
    """
    body = (built / name).read_text(encoding="utf-8")
    assert body.lstrip().lower().startswith("<!doctype html>")
    assert body.lower().count("<!doctype") == 1
    assert body.count("<html") == 1
    assert 'charset="utf-8"' in body.lower()
    assert 'name="viewport"' in body
    assert body.count("<title>") == 1


def test_the_two_pages_are_told_apart_by_their_titles(built: Path) -> None:
    tool = (built / "index.html").read_text(encoding="utf-8")
    doc = (built / "methodology.html").read_text(encoding="utf-8")
    assert "<title>Your Equity Share</title>" in tool
    assert "<title>Equity Share Methodology</title>" in doc


def test_the_page_reaches_the_methodology(built: Path) -> None:
    assert 'href="./methodology.html' in (built / "index.html").read_text(
        encoding="utf-8")


def test_nothing_is_fetched_from_anywhere_else(built: Path) -> None:
    """The privacy claim is architectural, so it is worth asserting."""
    import re

    for name in EXPECTED:
        body = (built / name).read_text(encoding="utf-8")
        remote = re.findall(r'(?:src|href)="(https?://[^"]+)"', body)
        assert not remote, f"{name} reaches out to {remote}"


def test_the_archive_serves_from_its_root(built: Path) -> None:
    """Netlify unpacks the zip and serves the top of it, so index.html has to
    sit there rather than inside a folder."""
    with zipfile.ZipFile(ZIP) as archive:
        names = set(archive.namelist())
    assert names == EXPECTED
