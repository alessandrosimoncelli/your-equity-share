"""The picture a link to the site shows when it is shared.

    python tools/make_share_image.py

Writes src/web/og.png and src/web/it/og.png, 1200 by 630, the size link
previews use, in the page's two colours and its typeface. The build copies
them into the site; run this again only if the title or the line under it
changes. Needs Pillow, which nothing else in the project does.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]

GREEN = (6, 64, 43)
INK = (0, 0, 0)
PAPER = (255, 255, 255)
# The page's --tint-2, a 16% wash of the green, flattened onto white.
TINT = tuple(round(255 * 0.84 + c * 0.16) for c in GREEN)

W, H = 1200, 630
LEFT = 90

TEXT = {
    "en": {"line": "How much of your long-term savings to keep in stocks.",
           "stocks": "Stocks", "safe": "Safe assets",
           "foot": "Based on Choi, Liu and Liu (2025)  \u00b7  Runs entirely in your browser",
           "out": ROOT / "src" / "web" / "og.png"},
    "it": {"line": "Quanta parte dei tuoi risparmi di lungo periodo tenere in azioni.",
           "stocks": "Azioni", "safe": "Attivit\u00e0 sicure",
           "foot": "Basato su Choi, Liu e Liu (2025)  \u00b7  Funziona interamente nel tuo browser",
           "out": ROOT / "src" / "web" / "it" / "og.png"},
}


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    """Arial, as the page sets it, or the nearest free equivalent."""
    names = (["arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
             if bold else
             ["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"])
    folders = [Path("C:/Windows/Fonts"), Path("/Library/Fonts"),
               Path("/usr/share/fonts/truetype/liberation"), Path("/usr/share/fonts/truetype/dejavu")]
    for folder in folders:
        for name in names:
            if (folder / name).exists():
                return ImageFont.truetype(str(folder / name), size)
    raise SystemExit("no Arial or equivalent font found")


def wrap(draw: ImageDraw.ImageDraw, text: str, face, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=face) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    return lines + [current]


def draw(lang: str) -> Path:
    t = TEXT[lang]
    image = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(image)
    # The ruled box the page draws round its form, here round the whole card.
    d.rectangle([24, 24, W - 25, H - 25], outline=GREEN, width=3)

    d.text((LEFT, 92), "Your Equity Share", font=font(True, 80), fill=GREEN)
    y = 210
    face = font(False, 40)
    for line in wrap(d, t["line"], face, W - 2 * LEFT):
        d.text((LEFT, y), line, font=face, fill=INK)
        y += 54

    # The answer's bar, at an illustrative split: no figure, because the
    # answer is the reader's own.
    top, height, gap = 360, 70, 4
    split = LEFT + round((W - 2 * LEFT) * 0.62)
    d.rectangle([LEFT, top, split - gap // 2, top + height], fill=GREEN)
    d.rectangle([split + gap // 2, top, W - LEFT, top + height], fill=TINT)
    key = font(False, 30)
    for x, swatch, word in ((LEFT, GREEN, t["stocks"]), (split + gap // 2, TINT, t["safe"])):
        d.rectangle([x, top + height + 26, x + 22, top + height + 48], fill=swatch)
        d.text((x + 34, top + height + 20), word, font=key, fill=INK)

    d.text((LEFT, 532), t["foot"], font=font(False, 28), fill=INK)
    t["out"].parent.mkdir(parents=True, exist_ok=True)
    image.save(t["out"], optimize=True)
    return t["out"]


def main() -> int:
    for lang in TEXT:
        out = draw(lang)
        print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
