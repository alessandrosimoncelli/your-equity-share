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
# Both countries' documents are published beside the tool, the Italian one
# in its own folder. Still an exact set: a stray file is still a failure.
EXPECTED = {"index.html", "model.js", "market.json", "methodology.html",
            "it/index.html", "it/market.json", "it/methodology.html",
            "further-work.html"}
# Published too, but pictures: the preview a shared link shows.
PICTURES = {"og.png", "it/og.png"}


@pytest.fixture(scope="module")
def built() -> Path:
    """Run the real build once, so these assertions are about real output."""
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_web.py")],
        cwd=ROOT, check=True, capture_output=True,
    )
    return OUT


def test_the_folder_holds_exactly_the_published_files(built: Path) -> None:
    """Walked recursively, so a file in a subfolder cannot hide from the check."""
    found = {p.relative_to(built).as_posix() for p in built.rglob("*")
             if p.is_file()}
    assert found == EXPECTED | PICTURES


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


@pytest.mark.parametrize("name", ["index.html", "methodology.html",
                                  "it/methodology.html", "further-work.html"])
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


def test_the_page_says_who_it_is_calibrated_for(built: Path) -> None:
    page = (built / "index.html").read_text(encoding="utf-8")
    assert "calibrated for a college-educated household" in page


def test_the_italian_page_is_written_from_the_english_one(built: Path) -> None:
    """One source, two pages: the Italian one carries the Italian variant,
    loads the shared model from one folder up, and says whom it is for."""
    page = (built / "it" / "index.html").read_text(encoding="utf-8")
    assert '<html lang="it">' in page
    assert 'from "../model.js"' in page
    assert "calibration: ITALY_CALIBRATION" in page
    assert "taxed" not in page
    assert "dipendente del settore privato" in page
    assert "Devi spendere tutto e non puoi chiedere prestiti." in page


def test_the_italian_partner_opens_on_the_first_adult_s_salary(built: Path) -> None:
    """A second adult ticked on the Italian page earns what the first one does.

        The English page's 80,000 sits beside a first adult on 100,000. Carried
    unchanged into the Italian page, it gave the partner several times the
    first adult's pay.
    """
    import re

    page = (built / "it" / "index.html").read_text(encoding="utf-8")
    first = re.search(r'id="wage" value="(\d+)"', page).group(1)
    partner = re.search(r'id="partner-wage" value="(\d+)"', page).group(1)
    assert partner == first


def test_the_italian_page_has_no_english_left(built: Path) -> None:
    """Every string a visitor can see is translated. Comments stay English;
    they are for whoever edits the source, which is the English page."""
    import re

    page = (built / "it" / "index.html").read_text(encoding="utf-8")
    start = page.index('<script type="module">')
    script = page[start:page.index("</script>", start)]
    script = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
    script = "\n".join(line for line in script.splitlines()
                       if not line.strip().startswith(("//", "*")))
    strings = re.findall(r'"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`', script)
    english = [s for s in strings
               if re.search(r"\b(the|your|you|and|of|is|are|to|with|for|from)\b", s)]
    assert not english, english[:5]
    markup = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", page, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", markup)
    for phrase in ("Exhibit", "Investable", "Results", "Inputs", "Social Security",
                   "United States", "coin flip", "safe asset", "Loading"):
        assert phrase not in visible, phrase


def test_the_italian_market_file_is_before_tax(built: Path) -> None:
    """The page reads the Italian market figures as they are, like the
    American ones: no after-tax figure, no regime, no horizon."""
    import tomllib

    data = json.loads((built / "it" / "market.json").read_text(encoding="utf-8"))
    raw = tomllib.loads((ROOT / "variants" / "it" / "market_data.toml").read_text(encoding="utf-8"))
    assert data["expected_stock_real_return"] == raw["market"]["expected_stock_real_return"]
    assert data["real_risk_free"] == raw["market"]["real_risk_free"]
    assert not [k for k in data if "tax" in k or "deferral" in k]
    page = (built / "it" / "index.html").read_text(encoding="utf-8")
    assert "afterTax" not in page and "deferralYears" not in page
    assert data["stock_volatility"] == raw["market"]["stock_volatility"]


def test_every_model_call_on_the_pages_carries_the_variant(built: Path) -> None:
    """Without VARIANT.calibration a call falls back to the American career,
    so the Italian page would quietly value an Italian as an American. A
    string check, because the page glue has no unit tests of its own."""
    import re

    for name in ("index.html", "it/index.html"):
        page = (built / name).read_text(encoding="utf-8")
        script = page[page.index('<script type="module">'):]
        calls = re.findall(r"\b(?:recommend|projectEarnings|humanCapital)\((.*)", script)
        assert len(calls) >= 7, name
        for call in calls:
            assert "VARIANT.calibration" in call, (name, call[:80])


def test_the_coin_question_keeps_the_guide_s_conditions(built: Path) -> None:
    """The guide's question says the whole amount is spent and nothing can be
    borrowed. The page dropped the second half once, and without it a bad year
    reads as one to borrow through. The amounts come from the household's
    income as the reference implementation adds it up."""
    page = (built / "index.html").read_text(encoding="utf-8")
    assert "You must spend it all and cannot borrow." in page
    assert "coinIncome(" in page


def test_the_page_reaches_the_methodology(built: Path) -> None:
    assert 'href="./methodology.html' in (built / "index.html").read_text(
        encoding="utf-8")


def test_the_page_reaches_every_document(built: Path) -> None:
    """A published document nothing links to is one no visitor finds."""
    tool = (built / "index.html").read_text(encoding="utf-8")
    for name in ("methodology.html", "it/index.html", "it/methodology.html",
                 "further-work.html"):
        assert f'href="./{name}"' in tool, name


def test_every_link_works_below_a_subfolder(built: Path) -> None:
    """The site is served from /your-equity-share/, not from the root.

    A link written "/methodology.html" works on a host that serves from the
    root and breaks on this one, where it points at the account's top level.
    So links are relative, and each must name a file the build produced.
    """
    import re

    for name in ("index.html", "methodology.html", "it/index.html",
                 "it/methodology.html", "further-work.html"):
        body = (built / name).read_text(encoding="utf-8")
        here = (built / name).parent
        # Links, fetches, and the module import that loads the model.
        pulls = [r'(?:src|href)="', r'fetch\(\s*["\']', r'\bfrom\s+["\']']
        rooted = [hit for p in pulls for hit in re.findall(p + r'(/[^"\']*)', body)]
        assert not rooted, f"{name} links from the root: {rooted}"
        links = [hit for p in pulls
                 for hit in re.findall(p + r'(\.{1,2}/[^"\'#?]*)', body)]
        for link in links:
            target = (here / link).resolve()
            assert target.is_file(), f"{name} links to missing {link}"
            assert built.resolve() in target.parents, f"{name} leaves the site: {link}"


def test_nothing_is_fetched_from_anywhere_else(built: Path) -> None:
    """The privacy claim is architectural, so it is worth asserting."""
    import re

    for name in EXPECTED:
        body = (built / name).read_text(encoding="utf-8")
        remote = re.findall(r'(?:src|href)="(https?://[^"]+)"', body)
        assert not remote, f"{name} reaches out to {remote}"


def test_the_archive_serves_from_its_root(built: Path) -> None:
    """A host that takes the zip unpacks it and serves the top of it, so
    index.html has to sit there rather than inside a folder."""
    with zipfile.ZipFile(ZIP) as archive:
        names = set(archive.namelist())
    assert names == EXPECTED | PICTURES
