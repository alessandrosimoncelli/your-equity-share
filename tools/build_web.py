"""Assemble the browser build.

Any static host serves the folder this produces, and the app inside it needs no
server: stlite compiles Python itself to WebAssembly, so the interpreter is
downloaded by the browser like a font. A visitor needs a browser and nothing
else. Nothing they type is transmitted anywhere, because there is nowhere to
transmit it to.

The app is byte-identical to the one `streamlit run app.py` runs. The same
app.py, the same package and the same market data file are mounted at the same
paths inside the browser filesystem that they occupy on disk, so app.py's
sys.path insert and market_data.py's DEFAULT_CONFIG_PATH resolve unchanged. No
web-specific fork exists, which is what lets the test suite stand behind what
visitors actually run.

    python tools/build_web.py

Then drag the `web` folder onto app.netlify.com/drop.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web"
STLITE = "1.8.1"

# Fetched by the browser at these paths. The layout mirrors the repository
# because the Python resolves its own paths and must not be told otherwise.
FETCHED = ["app.py", "config/market_data.toml"]

# Copied for the visitor to open directly, not mounted into the Python
# filesystem. The footer links to it, so without this the link is dead.
STATIC = {"docs/methodology.html": "methodology.html"}

# Inlined instead of fetched. Some static hosts will not serve a dot-prefixed
# directory, and this file is twelve lines.
INLINED = ".streamlit/config.toml"

INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
<title>Your Equity Share</title>
<meta name="description" content="How much of your portfolio belongs in equities. Merton (1969) with the human capital adjustment of Choi, Liu and Liu (2025).">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@__STLITE__/build/stlite.css">
<style>
  html, body { margin: 0; padding: 0; background: #FFFFFF; }
  #boot {
    position: fixed; inset: 0; z-index: 9999; background: #FFFFFF;
    display: flex; align-items: center; justify-content: center;
    font-family: Aptos, Calibri, "Segoe UI", Arial, Helvetica, sans-serif;
    color: #0B0B0B; transition: opacity .45s ease;
  }
  #boot.done { opacity: 0; pointer-events: none; }
  .boot-inner { max-width: 30rem; padding: 0 1.6rem; }
  .boot-title {
    font-size: 2.1rem; font-weight: 700; color: #1F3864;
    letter-spacing: -0.01em; margin: 0 0 .35rem;
  }
  .boot-rule { border: 0; border-top: 2px solid #1F3864; margin: .7rem 0 1.2rem; }
  .boot-text { font-size: 1rem; line-height: 1.55; color: #52514E; margin: 0; }
  .boot-track {
    height: 4px; background: #E7E6DF; margin-top: 1.6rem; overflow: hidden;
  }
  .boot-bar {
    height: 100%; width: 35%; background: #2A78D6;
    animation: slide 1.5s ease-in-out infinite;
  }
  @keyframes slide {
    0%   { transform: translateX(-100%); }
    100% { transform: translateX(320%); }
  }
</style>
</head>
<body>
<div id="boot">
  <div class="boot-inner">
    <p class="boot-title">Your Equity Share</p>
    <hr class="boot-rule">
    <p class="boot-text">
      Starting the calculator. The first visit downloads a Python runtime,
      which takes a few moments. It is cached afterwards, so later visits
      start straight away.
    </p>
    <div class="boot-track"><div class="boot-bar"></div></div>
  </div>
</div>
<div id="root"></div>
<script type="module">
import { mount } from "https://cdn.jsdelivr.net/npm/@stlite/browser@__STLITE__/build/stlite.js";

mount(
  {
    entrypoint: "app.py",
    requirements: [],
    files: __FILES__,
    streamlitConfig: { "client.toolbarMode": "viewer" },
    // The splash already says the runtime is loading. stlite's own progress
    // toasts stack down the right-hand side on top of the finished page, which
    // reads as something going wrong. Error toasts stay on, so a genuine
    // failure is still visible rather than silent.
    disableProgressToasts: true,
    disableModuleAutoLoadToasts: true,
  },
  document.getElementById("root"),
);

// Clear the splash when the app has produced output, not when the React shell
// appears. Streamlit mounts its skeleton within a second of the page loading,
// long before Python has run, so waiting on that showed grey placeholder blocks
// for twenty seconds. `.headline` is this app's own class on the headline
// percentage, and exists only once the model has actually returned an answer.
const boot = document.getElementById("boot");
const ready = () =>
  document.querySelector("#root .headline") ||
  document.querySelector('#root [data-testid="stException"]');
const clear = () => {
  if (!boot.isConnected) return;
  boot.classList.add("done");
  setTimeout(() => boot.remove(), 600);
};
const observer = new MutationObserver(() => {
  if (ready()) {
    observer.disconnect();
    clear();
  }
});
observer.observe(document.getElementById("root"), { childList: true, subtree: true });
// If anything goes wrong, show the page rather than a splash that never leaves.
setTimeout(() => { observer.disconnect(); clear(); }, 120000);
</script>
</body>
</html>
"""


def main() -> int:
    package = sorted((ROOT / "src" / "your_equity_share").glob("*.py"))
    if not package:
        print("no package sources found; is this the right directory?")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for rel in FETCHED + [str(p.relative_to(ROOT)).replace("\\", "/") for p in package]:
        src = ROOT / rel
        if not src.exists():
            print(f"missing: {rel}")
            return 1
        dst = OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)

    extra: list[str] = []
    for src_rel, dst_rel in STATIC.items():
        src = ROOT / src_rel
        if not src.exists():
            print(f"missing: {src_rel}")
            return 1
        dst = OUT / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        extra.append(dst_rel)

    config = (ROOT / INLINED).read_text(encoding="utf-8")
    entries = [f'  {_q(INLINED)}: {_q(config)},']
    entries += [f'  {_q(rel)}: {{ url: {_q("./" + rel)} }},' for rel in copied]
    files = "{\n" + "\n".join(entries) + "\n}"

    index = INDEX.replace("__STLITE__", STLITE).replace("__FILES__", files)
    (OUT / "index.html").write_text(index, encoding="utf-8")

    # Clear anything a previous build left behind. Files only, never
    # directories: this repository sits inside OneDrive, which keeps directory
    # handles open long enough that removing a folder fails at random, and a
    # build step that fails at random is worse than a stale empty folder.
    keep = {OUT / "index.html"} | {OUT / rel for rel in copied + extra}
    for path in OUT.rglob("*"):
        if path.is_file() and path not in keep:
            path.unlink()
            print(f"  removed stale {path.relative_to(OUT)}")

    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"built {OUT}")
    for rel in ["index.html"] + copied + extra:
        print(f"  {(OUT / rel).stat().st_size:>7,}  {rel}")
    print(f"  {total:>7,}  total ({total / 1024:.0f} KB)")
    print("\nServe locally:  python -m http.server 8600 --directory web")
    print("Publish:        drag the web folder onto app.netlify.com/drop")
    return 0


def _q(text: str) -> str:
    """A JSON string literal. json.dumps is exactly the right escaping here."""
    import json

    return json.dumps(text)


if __name__ == "__main__":
    raise SystemExit(main())
