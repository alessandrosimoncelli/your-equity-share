"""Build single-file versions of the tool and the document.

    python tools/build_artifact.py

The Netlify build is four files that fetch each other. Some hosts serve one
file and nothing else, and a page that fetches its own model and its own market
data cannot run there. This inlines both, so each output is a single HTML file
with no external request of any kind.

Nothing about the model changes. `src/js/model.js` is inserted verbatim with
its `export` keywords removed, which is the only edit, and the page's import
statement is deleted because the definitions are then already in scope. The
market data is the same numbers `update.py` wrote, read from the same TOML.

The head and body wrappers are stripped: the host supplies those, and the file
is expected to start at its own <title>.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from build_web import build_market_json  # noqa: E402

OUT = ROOT / "dist"


def strip_wrapper(html: str) -> str:
    """Keep the title, the styles and the body, drop the document scaffolding."""
    title = re.search(r"<title>.*?</title>", html, re.S)
    styles = re.findall(r"<style>.*?</style>", html, re.S)
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if body is not None:
        content = body.group(1)
    else:
        # Already in this shape. The methodology document was written as one
        # from the start, so it has no scaffolding to remove.
        content = html
        if title:
            content = content.replace(title.group(0), "", 1)
        for style in styles:
            content = content.replace(style, "", 1)
        content = re.sub(r"</?(?:html|head|body)[^>]*>", "", content)
    parts = []
    if title:
        parts.append(title.group(0))
    parts.extend(styles)
    parts.append(content.strip())
    return "\n".join(parts) + "\n"


def build_tool(methodology_href: str) -> Path:
    page = (ROOT / "src" / "web" / "index.html").read_text(encoding="utf-8")
    model = (ROOT / "src" / "js" / "model.js").read_text(encoding="utf-8")

    # `export` only marks what leaves the module. With everything in one scope
    # there is no module, and the keyword is the one thing that must go.
    model = re.sub(r"^export\s+", "", model, flags=re.M)

    # The import names things already defined above it.
    page, n = re.subn(r"import \{[^}]*\} from \"\./model\.js\";\n", "", page)
    if n != 1:
        raise SystemExit(f"expected one import of model.js, found {n}")

    # Inline the market data in place of fetching it.
    market = build_market_json()
    old = re.search(
        r"  try \{\n    const response = await fetch.*?\n  \}\n", page, re.S
    )
    if old is None:
        raise SystemExit("could not find the market fetch")
    page = page.replace(old.group(0), f"  market = {market};\n")

    # Put the model above the page's own script.
    marker = '<script type="module">\n'
    if page.count(marker) != 1:
        raise SystemExit("expected exactly one module script")
    page = page.replace(
        marker,
        marker
        + "// ---------------------------------------------------------------\n"
        + "// src/js/model.js, inlined verbatim but for its export keywords.\n"
        + "// The Python it is held to lives in src/your_equity_share/, and\n"
        + "// tests/golden.json binds the two. Do not edit this copy.\n"
        + "// ---------------------------------------------------------------\n"
        + model
        + "\n// --- the page ---------------------------------------------------\n",
    )

    page = page.replace('href="./methodology.html"', f'href="{methodology_href}"')

    OUT.mkdir(exist_ok=True)
    path = OUT / "tool.html"
    path.write_text(strip_wrapper(page), encoding="utf-8")
    return path


def build_methodology() -> Path:
    doc = (ROOT / "docs" / "methodology.html").read_text(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    path = OUT / "methodology.html"
    # A distinct title, so the tool and its documentation are told apart in a
    # list. The heading inside the document is unchanged.
    out = strip_wrapper(doc).replace(
        "<title>Your Equity Share</title>",
        "<title>Equity Share Methodology</title>", 1)
    path.write_text(out, encoding="utf-8")
    return path


def main() -> int:
    doc = build_methodology()
    href = sys.argv[1] if len(sys.argv) > 1 else "#"
    tool = build_tool(href)
    for path in (tool, doc):
        size = path.stat().st_size
        print(f"  {size:>7,}  {path.relative_to(ROOT)}  ({size / 1024:.0f} KB)")
    text = tool.read_text(encoding="utf-8")
    for bad in ("fetch(", "./model.js", "./market.json"):
        if bad in text:
            print(f"  WARNING: the tool still refers to {bad}")
    print(f"\nmethodology link points at: {href}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
