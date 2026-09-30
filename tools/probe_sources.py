"""Ask every data source for a response before the refresh asks for data.

    python tools/probe_sources.py

The weekly refresh runs on GitHub's servers, and a provider that answers a
laptop can refuse a data centre: FRED did exactly that on the first run. The
refresh stops at the first source that fails, so one failure hides every
source after it. This asks all of them at once, with a short timeout, and
prints one line per source. On GitHub it also writes the result as an
annotation, which anyone can read on the run's summary page, because step
logs are shown only to signed-in users.

It never fails. It reports, and the refresh decides what a failure costs.
The URLs are the scripts' own constants rather than copies of them, so the
probe cannot drift from what the refresh actually requests.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import update  # noqa: E402
import refresh_italy as italy  # noqa: E402

TIMEOUT = 20
TODAY = date.today()

# (what the source is for, URL, the user agent the script sends)
SOURCES = [
    ("US safe rate, Treasury",
     update.TREASURY_REAL_YIELD_URL.format(year=TODAY.year), update.USER_AGENT),
    ("US safe rate, FRED fallback",
     update.FRED_URL.format(series=update.FRED_REAL_RISK_FREE), update.USER_AGENT),
    ("US volatility, Yahoo SPY",
     update.PRICE_URL.format(ticker="SPY", range="5y"), update.USER_AGENT),
    ("Shiller, page", update.SHILLER_PAGE, update.USER_AGENT),
    ("Shiller, Yale copy", update.SHILLER_YALE_URL, update.USER_AGENT),
    ("Shiller, mirror", update.SHILLER_MIRROR_URL, update.USER_AGENT),
    ("Damodaran premium", update.ERP_URL, update.USER_AGENT),
    ("CAPE, multpl", update.CAPE_URL, update.USER_AGENT),
    ("Italian safe rate, ECB",
     italy.ECB.format(italy.NOMINAL_30Y), italy.USER_AGENT),
    ("Italian break-even, Finanzagentur", italy.LINKER_PAGE, italy.USER_AGENT),
    ("Italian yield, MSCI",
     italy.MSCI.format(cur="EUR", var="STRD", code=italy.ACWI,
                       start="20250101", end=TODAY.strftime("%Y%m%d")),
     italy.USER_AGENT),
    ("Italian volatility, Yahoo VWCE",
     update.PRICE_URL.format(ticker=italy.VOLATILITY_TICKER, range="5y"),
     update.USER_AGENT),
]


def _contexts() -> list:
    """The system's certificates first, then certifi's, as refresh_italy does.

    Some machines lack an intermediate certificate the ECB's chain needs, and
    the Italian refresh retries with certifi for that reason. Probing with
    the system store alone would report a failure the refresh never meets.
    """
    contexts = [None]
    try:
        import ssl

        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except ImportError:
        pass
    return contexts


def probe(source: tuple[str, str, str]) -> tuple[str, bool, str]:
    name, url, agent = source
    start = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": agent})
    contexts = _contexts()
    for n, context in enumerate(contexts):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT,
                                        context=context) as response:
                size = len(response.read(200_000))
                return name, True, "HTTP %d, %s bytes read, %.1fs" % (
                    response.status, format(size, ","), time.monotonic() - start)
        except urllib.error.HTTPError as exc:
            return name, False, "HTTP %d %s" % (exc.code, exc.reason)
        except urllib.error.URLError as exc:
            if n + 1 < len(contexts) and "CERTIFICATE" in str(exc.reason).upper():
                continue
            return name, False, "unreachable: %s" % exc.reason
        except TimeoutError:
            return name, False, "no answer in %ds" % TIMEOUT
        except Exception as exc:  # report anything, never raise
            return name, False, "%s: %s" % (type(exc).__name__, exc)
    return name, False, "no certificate store worked"


def main() -> int:
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        results = list(pool.map(probe, SOURCES))
    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print("  %-*s  %-6s %s" % (width, name, "ok" if ok else "FAILED", detail))

    failed = [(name, detail) for name, ok, detail in results if not ok]
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # One annotation per run, not one per source. In a workflow command a
        # % is an escape everywhere, and in the title a comma or a colon ends
        # it, which is how the first title was cut to "Data sources".
        summary = ("every source answered" if not failed else
                   "; ".join("%s: %s" % item for item in failed))
        title = "Data sources: %d of %d answered" % (
            len(results) - len(failed), len(results))
        title = title.replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
        level = "warning" if failed else "notice"
        print("::%s title=%s::%s" % (level, title, summary.replace("%", "%25")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
