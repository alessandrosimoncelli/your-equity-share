"""Extract the computed cell values of the source workbook into a JSON fixture.

The fixture is the regression baseline for the faithful port: the numbers the
port must reproduce come from the spreadsheet itself rather than being copied by
hand. Regenerate with

    python tools/extract_baseline.py "path/to/QUANTO DEVO INVESTIRE IN AZIONI.xlsx"

Reads .xlsx with the standard library only, since the values Excel last stored
are cached in the sheet XML and no formula evaluation is required.
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Cells of the "Merton Share" sheet that the faithful port must reproduce.
# Values are whatever Excel cached the last time the workbook was saved.
CELLS_OF_INTEREST = [
    "B4", "C4", "D4",      # sleeve weights
    "B5", "C5", "D5",      # forward P/E
    "B6", "C6", "D6",      # forward earnings yield
    "B7", "C7", "D7",      # real expected excess return
    "B8", "C8", "D8",      # standard deviation
    "B9", "B10",           # risk-free nominal, real
    "B12",                 # age
    "B13", "B14", "B15",   # the three risk scores
    "B16",                 # gamma
    "G4", "G5",            # Merton share, and the remainder
    "G9", "G10",           # "bull formula" share, and the remainder
]


def _column_of(ref: str) -> str:
    return re.match(r"([A-Z]+)", ref).group(1)


def read_sheet_values(xlsx_path: Path, sheet_name: str) -> dict[str, float | str]:
    """Return {cell_ref: cached value} for one worksheet."""
    with zipfile.ZipFile(xlsx_path) as z:
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))

        rel_target = {
            r.get("Id"): r.get("Target")
            for r in rels.iter("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
        }

        rid = None
        for sheet in workbook.iter(f"{{{NS['m']}}}sheet"):
            if sheet.get("name") == sheet_name:
                rid = sheet.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                )
                break
        if rid is None:
            raise KeyError(f"sheet {sheet_name!r} not found in {xlsx_path.name}")

        target = rel_target[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target

        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sst.iter(f"{{{NS['m']}}}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))

        sheet_xml = ET.fromstring(z.read(target))

    values: dict[str, float | str] = {}
    for cell in sheet_xml.iter(f"{{{NS['m']}}}c"):
        ref = cell.get("r")
        v = cell.find(f"{{{NS['m']}}}v")
        if ref is None or v is None or v.text is None:
            continue
        if cell.get("t") == "s":
            values[ref] = shared[int(v.text)]
        else:
            values[ref] = float(v.text)
    return values


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    xlsx = Path(argv[1])
    values = read_sheet_values(xlsx, "Merton Share")

    missing = [ref for ref in CELLS_OF_INTEREST if ref not in values]
    if missing:
        raise SystemExit(f"cells absent from the workbook: {', '.join(missing)}")

    baseline = {
        "source_workbook": xlsx.name,
        "sheet": "Merton Share",
        "cells": {ref: values[ref] for ref in CELLS_OF_INTEREST},
        "sleeve_labels": [values.get("B3"), values.get("C3"), values.get("D3")],
    }

    out = Path(__file__).resolve().parents[1] / "tests" / "baseline_cells.json"
    out.write_text(json.dumps(baseline, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(baseline['cells'])} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
