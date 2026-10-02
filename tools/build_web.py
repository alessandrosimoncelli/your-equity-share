"""Assemble the browser build.

    python tools/build_web.py

Any static host serves the folder this produces, and it needs no server. Four
files, about 120 KB, no runtime to download and nothing to install: the page
opens immediately.

    index.html        the tool, hand written
    model.js          the model, ported from Python
    market.json       the three numbers, from variants/us/market_data.toml
    methodology.html  the technical document the footer links to
    it/               the Italian page and its market file, written from the
                      same index.html: see build_italian_page

The earlier build shipped Streamlit compiled to WebAssembly, which ran the
Python itself in the browser. It was faithful, and it took about thirty seconds
to start, because the cost is Pyodide booting rather than downloading and no
amount of caching touches that. The model is a few hundred lines of pure
arithmetic, so it runs natively instead.

Python remains the reference implementation. `src/js/model.js` is held to it by
tests/golden.json; see tools/check_golden.mjs. Only the model crossed over.
Fetching, parsing, volatility, the expected-return estimators and the frozen
spreadsheet baseline all stay in Python because they run on the author's
machine, not the reader's.

Nothing a visitor types is transmitted, because there is nowhere to transmit it
to. That is a property of the architecture rather than a promise.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "web"
ZIP = ROOT / "your-equity-share-site.zip"

# Source on the left, name in the built site on the right. Copied as they are
# except that a fragment is given a document shell; see `as_document`.
# The tool and its documentation should be distinguishable in a browser tab.
# build_artifact.py makes the same substitution for the artifact copy.
TITLES = {"methodology.html": "Equity Share Methodology"}

COPIED = {
    "src/web/index.html": "index.html",
    "src/js/model.js": "model.js",
    "variants/us/methodology.html": "methodology.html",
    # Both countries' documents are published from the one site, beside the
    # tool, so a reader following a link from either never lands on a copy
    # that has drifted from the code that produced it.
    "variants/it/methodology.html": "it/methodology.html",
    "docs/further-work.html": "further-work.html",
}

CONFIG = ROOT / "variants" / "us" / "market_data.toml"

# The Italian variant, read only so the page can print its expected return
# beside the American one. The tool itself runs on CONFIG; this is context,
# because "3.38% real" means little until a reader can see what the same
# construction produces for a global index. Optional on purpose: a checkout
# without the Italian file still builds.
CONFIG_GLOBAL = ROOT / "variants" / "it" / "market_data.toml"

# The Italian page is not a second copy of the tool. It is written from
# src/web/index.html at build time: the VARIANT block is swapped for the one
# below and the words are translated with the table in TRANSLATION. A fix to
# the page therefore reaches both, and an edit to its English that the table
# does not carry stops the build rather than leaving English on the page.
PAGE = ROOT / "src" / "web" / "index.html"
TRANSLATION = ROOT / "src" / "web" / "it" / "translation.toml"
ITALIAN_VARIANT = """const VARIANT = {
  locale: "it-IT",
  currency: "EUR",
  // Money as people type it: the thousands separator and the decimal mark.
  group: ".",
  decimal: ",",
  calibration: ITALY_CALIBRATION,
};"""


def as_document(body: str, title_override: str | None = None) -> str:
    """Give an HTML fragment the head a web server needs, and leave a page alone.

    Only ever call this on HTML. It once ran over model.js as well, which
    produced a JavaScript file beginning "<!doctype html>" and a site that
    failed to boot.

    variants/us/methodology.html is written without a doctype or a head, because the
    artifact host supplies both. A static host supplies neither, and the file
    is also opened straight off disk, so the copy written here needs its own.
    """
    if body.lstrip().lower().startswith("<!doctype"):
        return body

    title = "Your Equity Share"
    marker = "<title>"
    if marker in body:
        start = body.index(marker) + len(marker)
        end = body.index("</title>", start)
        title = body[start:end]
        # Hoisted into the head, not copied there. A second <title> in the body
        # is ignored by browsers and reads as a mistake in the source.
        body = body[: start - len(marker)] + body[end + len("</title>"):]
        body = body.lstrip("\n")

    return _shell(title_override or title, body)


def _shell(title: str, body: str) -> str:
    """The head a static host will not supply and a local file has no source for."""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


def build_global_block() -> dict | None:
    """The global sleeve's expected return, for the comparison on the page.

    Only the figures the page prints, not enough to run the model on, because
    running it would need the Italian human capital calibration too and this is
    a comparison rather than a second tool.
    """
    if not CONFIG_GLOBAL.exists():
        return None
    with CONFIG_GLOBAL.open("rb") as handle:
        raw = tomllib.load(handle)
    market = raw.get("market", {})
    provenance = raw.get("provenance", {})
    if "expected_stock_real_return" not in market:
        return None
    return {
        "expected_stock_real_return": float(market["expected_stock_real_return"]),
        "expected_stock_real_return_compound": (
            float(provenance["expected_return_compound"])
            if "expected_return_compound" in provenance else None),
        "dividend_yield": (float(provenance["dividend_yield"])
                           if "dividend_yield" in provenance else None),
        "real_growth": (float(provenance["real_growth"])
                        if "real_growth" in provenance else None),
        "real_risk_free": float(market["real_risk_free"]),
        "stock_volatility": float(market["stock_volatility"]),
        "index": str(provenance.get("equity_index", "a global index")),
        "as_of": str(market.get("as_of", "")),
    }


def _flexible(text: str) -> re.Pattern:
    """A pattern for `text` that ignores how its words are wrapped."""
    return re.compile(r"\s+".join(re.escape(word) for word in text.split()))


def build_italian_page() -> str:
    """The Italian page: the English one with the Italian variant and words.

    Every entry of the table must match exactly once, and no two may overlap,
    so the translation can neither miss its target nor land twice.
    """
    page = PAGE.read_text(encoding="utf-8")
    block = re.compile(r"const VARIANT = \{.*?\n\};", re.S)
    if len(block.findall(page)) != 1:
        raise SystemExit(f"{PAGE}: expected one VARIANT block")
    page = block.sub(lambda _m: ITALIAN_VARIANT, page)

    with TRANSLATION.open("rb") as handle:
        entries = tomllib.load(handle).get("t", [])
    spans = []
    for entry in entries:
        hits = list(_flexible(entry["en"]).finditer(page))
        if len(hits) != 1:
            raise SystemExit(
                f"{TRANSLATION.name}: {len(hits)} matches for {entry['en'][:70]!r}; "
                "the English page changed, so update the table")
        spans.append((hits[0].start(), hits[0].end(), entry["it"]))
    spans.sort()
    for (_, end, _), (start, _, _) in zip(spans, spans[1:]):
        if start < end:
            raise SystemExit(f"{TRANSLATION.name}: two entries overlap at {start}")
    for start, end, italian in reversed(spans):
        page = page[:start] + italian + page[end:]
    return page


def build_italian_market_json() -> str:
    """The Italian market file, before tax like the American one.

    The model reads market figures as they are in both variants; section 8 of
    the Italian methodology says why Italian tax is left out.
    """
    with CONFIG_GLOBAL.open("rb") as handle:
        raw = tomllib.load(handle)
    market, provenance = raw["market"], raw.get("provenance", {})
    window = re.search(r"(\d+) years", str(provenance.get("volatility_source", "")))
    payload = {
        "expected_stock_real_return": float(market["expected_stock_real_return"]),
        "expected_stock_real_return_compound": float(provenance["expected_return_compound"]),
        "real_risk_free": float(market["real_risk_free"]),
        "stock_volatility": float(market["stock_volatility"]),
        "market_ticker": str(market.get("market_ticker", provenance.get("market_ticker", ""))),
        "as_of": str(market["as_of"]),
        "provenance": {
            **{k: str(v) if not isinstance(v, (int, float, bool)) else v
               for k, v in provenance.items()},
            "volatility_window_years": int(window.group(1)) if window else None,
        },
    }
    return json.dumps(payload, indent=1)


def build_market_json() -> str:
    """Convert the TOML the model reads into the JSON the page fetches.

    The page cannot parse TOML and should not have to. This keeps
    variants/us/market_data.toml the single source that `update.py` writes and that
    every Python entry point reads, and makes the monthly refresh a matter of
    replacing one small file in the deploy.
    """
    if not CONFIG.exists():
        raise SystemExit(f"no market data at {CONFIG}. Run: python update.py")

    with CONFIG.open("rb") as handle:
        raw = tomllib.load(handle)

    try:
        market = raw["market"]
    except KeyError:
        raise SystemExit(f"{CONFIG}: missing section 'market'")

    for required in ("expected_stock_real_return", "real_risk_free",
                     "stock_volatility", "as_of"):
        if required not in market:
            raise SystemExit(f"{CONFIG}: [market] is missing {required!r}")

    # The model consumes the arithmetic mean. The page shows the compound
    # figure beside it, because that is the basis every published capital
    # market assumption is quoted on and the only one a reader can compare.
    provenance = raw.get("provenance", {})
    compound = provenance.get("expected_return_compound")
    if compound is None and "expected_return_estimates" in provenance:
        import re as _re

        found = _re.search(r"building blocks ([0-9.]+)",
                           str(provenance["expected_return_estimates"]))
        compound = float(found.group(1)) if found else None

    payload = {
        "global": build_global_block(),
        "expected_stock_real_return": float(market["expected_stock_real_return"]),
        "expected_stock_real_return_compound": (
            float(compound) if compound is not None else None
        ),
        "real_risk_free": float(market["real_risk_free"]),
        "stock_volatility": float(market["stock_volatility"]),
        "market_ticker": str(market.get("market_ticker", "SPY")),
        # tomllib returns a date object; the page wants an ISO string.
        "as_of": str(market["as_of"]),
        "provenance": {k: str(v) if not isinstance(v, (int, float, bool)) else v
                       for k, v in raw.get("provenance", {}).items()},
    }
    return json.dumps(payload, indent=1)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for source, name in COPIED.items():
        src = ROOT / source
        if not src.exists():
            raise SystemExit(f"missing: {source}")
        body = src.read_text(encoding="utf-8")
        # Only HTML gets a document shell. This wrapped model.js once, which
        # made the browser parse JavaScript as HTML and took the whole site
        # down with "Unexpected token '<'".
        if name.endswith(".html"):
            body = as_document(body, TITLES.get(name))
        (OUT / name).parent.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text(body, encoding="utf-8")
        written.append(name)

    (OUT / "market.json").write_text(build_market_json(), encoding="utf-8")
    written.append("market.json")

    (OUT / "it").mkdir(parents=True, exist_ok=True)
    (OUT / "it" / "index.html").write_text(as_document(build_italian_page()),
                                           encoding="utf-8")
    written.append("it/index.html")
    (OUT / "it" / "market.json").write_text(build_italian_market_json(),
                                            encoding="utf-8")
    written.append("it/market.json")

    # Remove anything left from an earlier build, so the folder that gets
    # uploaded contains only what this build put there. The WebAssembly build
    # left a whole Python package behind.
    keep = set(written)
    for path in sorted(OUT.rglob("*"), reverse=True):
        if path.is_file() and str(path.relative_to(OUT)).replace("\\", "/") not in keep:
            path.unlink()
            print(f"  removed stale {path.relative_to(OUT)}")
    for path in sorted(OUT.rglob("*"), key=lambda q: len(q.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            try:
                path.rmdir()
                print(f"  removed empty {path.relative_to(OUT)}")
            except OSError:
                # OneDrive holds directory handles briefly. An untidy folder is
                # not a reason to fail the build.
                pass

    # Also as an archive, for a static host that takes an upload rather than
    # building from the repository. Such hosts unpack it and serve the root,
    # so index.html must sit at the top of the archive.
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(q for q in OUT.rglob("*") if q.is_file()):
            archive.write(path, path.relative_to(OUT).as_posix())

    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"built {OUT}")
    for name in written:
        print(f"  {(OUT / name).stat().st_size:>7,}  {name}")
    print(f"  {total:>7,}  total ({total / 1024:.0f} KB)")
    print(f"  {ZIP.stat().st_size:>7,}  {ZIP.name}  (for any other host)")

    print("\nServe locally:  python -m http.server 8600 --directory web")
    print("Publish:        push to main. GitHub Actions rebuilds and deploys to")
    print("                https://alessandrosimoncelli.github.io/your-equity-share/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
