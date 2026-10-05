"""The yearly figures list in tools/maintenance.py, held to the code it describes."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import maintenance  # noqa: E402
from your_equity_share.human_capital import SOCIAL_SECURITY_MAXIMUM  # noqa: E402


def test_nothing_is_due_before_its_date_and_everything_after() -> None:
    # The day before the Ragioneria's 2026 report went online.
    assert maintenance.due(date(2026, 9, 21)) == []
    assert len(maintenance.due(date(2030, 1, 1))) == len(maintenance.ITEMS)


def test_the_social_security_item_names_the_figure_the_code_uses() -> None:
    """The list cannot drift from the model: the monthly figure it names is the
    one the cap is built from, in Python and in the page's model."""
    item = maintenance.ITEMS[0]
    monthly = float(re.search(r"\$([0-9,]+) a month", item.what).group(1).replace(",", ""))
    assert SOCIAL_SECURITY_MAXIMUM == 0.8 * monthly * 12
    js = (ROOT / "src" / "js" / "model.js").read_text(encoding="utf-8")
    assert f"0.8 * {monthly:.1f} * 12" in js
    assert item.due.year == int(re.search(r"the (\d{4}) figure", item.what).group(1)) + 1


def test_the_italian_pension_item_names_the_rate_the_code_uses() -> None:
    """The Ragioneria's net rate it names, restated on the wage with the TFR,
    is the rate the Italian calibration uses, in Python and in the page."""
    from your_equity_share.human_capital import ITALY_CALIBRATION
    item = maintenance.ITEMS[1]
    net = float(re.search(r"([0-9.]+)% net", item.what).group(1)) / 100
    assert ITALY_CALIBRATION.benefit_replacement_rate == round(net / 1.075, 3)
    js = (ROOT / "src" / "js" / "model.js").read_text(encoding="utf-8")
    assert f"benefitReplacementRate: {round(net / 1.075, 3)}" in js
