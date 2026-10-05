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
        what="The Italian pension's replacement rate: the Ragioneria Generale "
             "dello Stato's 66.0% net, Rapporto n. 26 (2025), Table 6.3.a, base "
             "case 2050",
        due=date(2026, 9, 22),
        where="benefit_replacement_rate in ITALY_CALIBRATION "
              "(src/your_equity_share/human_capital.py) and benefitReplacementRate "
              "in src/js/model.js, both 0.66 / 1.075; the Italian methodology "
              "(sections 2 and 7.2 and every figure derived from 61.4%), the "
              "Italian market files, docs/inputs.md, tests/test_italy.py, and the "
              "due date here",
        source="the Ragioneria's yearly report on the pension system, Table "
               "6.3.a; Rapporto n. 27, dated July 2026 and online since 22 "
               "September 2026, gives 66.4%",
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
