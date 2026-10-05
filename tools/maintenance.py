"""The figures that age every year, and whether one is due.

    python tools/maintenance.py

The weekly refresh keeps the market data current, but a few numbers come from
annual publications and nothing refreshes them. This lists them and says when
one is out of date. The weekly workflow runs it after the site is published,
so an item that is due turns that run red, and GitHub sends its usual e-mail,
without holding back the data or the site. Updating the figure, and the date
here, clears it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Item:
    what: str
    due: date          # when the figure in use stops being the current one
    where: str         # what to edit
    source: str        # where the new figure is published


ITEMS = (
    Item(
        what="Social Security's maximum benefit at full retirement age: "
             "$4,152 a month, the 2026 figure",
        due=date(2027, 1, 1),
        where="SOCIAL_SECURITY_MAXIMUM in src/your_equity_share/human_capital.py, "
              "benefitCap in src/js/model.js, the US methodology (section 7.7 and "
              "Tables 1, 18 and 21), docs/inputs.md, and the due date here",
        source="SSA's cost-of-living adjustment fact sheet, published each "
               "October for the next January",
    ),
    Item(
        what="AQR's capital market assumptions, the Italian cross-check: "
             "the edition of 31 December 2025",
        due=date(2027, 3, 1),
        where="AQR_REPORT, AQR_AS_OF, AQR_YIELD, AQR_GROWTH and AQR_COMPOUND in "
              "tools/refresh_italy.py, the same three figures in tools/estimators_it.py, "
              "AQR's figures in both methodologies (the American one's section 8.3), "
              "docs/inputs.md and docs/further-work.html, and the due date here",
        source="AQR, Alternative Thinking, first issue of each year",
    ),
)


def due(today: date | None = None) -> list[Item]:
    today = today or date.today()
    return [item for item in ITEMS if today >= item.due]


def main() -> int:
    late = due()
    for item in ITEMS:
        state = "DUE" if item in late else "current until %s" % item.due
        print(f"{item.what}\n  {state}\n  update: {item.where}\n  from: {item.source}\n")
    if late:
        for item in late:
            # A GitHub Actions annotation, shown on the run's summary page.
            print(f"::warning title=Yearly figure out of date::{item.what}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
