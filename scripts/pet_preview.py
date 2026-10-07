"""Render a visual preview strip of a pet atlas so it can be eyeballed.

Usage:
    python scripts/pet_preview.py pets/<name> [out.png]

Output: one PNG, rows top-to-bottom = the atlas rows, each row showing its
frames left-to-right on a checkerboard (so transparency is visible).
Rows are labelled in the margin: 1-9 = behaviour rows, L1/L2 = gaze rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROW_NAMES = ["1 idle", "2 walk R", "3 walk L", "4 waving", "5 jumping",
             "6 failed", "7 waiting", "8 running", "9 review",
             "L1 gaze 0-7", "L2 gaze 8-15"]
DEFAULT_FH = 208
MARGIN = 90


def checker(w: int, h: int, size: int = 12) -> Image.Image:
    img = Image.new("RGB", (w, h), (240, 240, 246))
    d = ImageDraw.Draw(img)
    for y in range(0, h, size):
        for x in range(0, w, size):
            if (x // size + y // size) % 2:
                d.rectangle([x, y, x + size - 1, y + size - 1], fill=(214, 216, 226))
    return img


def main() -> None:
    import json
    pet_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pets/boba")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("state") / f"preview_{pet_dir.name}.png"
    meta = json.loads((pet_dir / "pet.json").read_text(encoding="utf-8"))
    sheet = Image.open(pet_dir / (meta.get("spritesheetPath") or "spritesheet.webp")).convert("RGBA")
    fh = int(meta.get("frameHeight") or 0) or DEFAULT_FH
    fw = sheet.width // 8
    rows = min(11, sheet.height // fh)

    # find per-row valid frame counts (contiguous non-empty)
    counts = []
    for r in range(rows):
        n = 0
        for c in range(8):
            cell = sheet.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh))
            a = cell.getchannel("A")
            hist = a.histogram()
            drawn = sum(hist[21:])
            if drawn > fw * fh * 0.02:
                n += 1
            else:
                break
        counts.append(max(1, n) if r else n)

    total_w = MARGIN + 8 * fw
    total_h = sum(fh for _ in range(rows))
    canvas = checker(total_w, total_h)
    draw = ImageDraw.Draw(canvas)
    y = 0
    for r in range(rows):
        label = ROW_NAMES[r] if r < len(ROW_NAMES) else f"row {r + 1}"
        draw.text((8, y + fh // 2 - 6), label, fill=(30, 30, 40))
        for c in range(counts[r]):
            cell = sheet.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh))
            canvas.paste(cell, (MARGIN + c * fw, y), cell)
        y += fh
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print("preview ->", out, f"({canvas.width}x{canvas.height})",
          "| frames per row:", counts)


if __name__ == "__main__":
    main()
