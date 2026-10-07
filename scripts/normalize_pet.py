"""Normalize a pet atlas: pin every frame's foot anchor to one spot per row.

Generative/individually-drawn atlases drift frame to frame (the body slides
left/right inside its cell). The engine does a per-frame whole-body offset,
but residual jitter remains and reads as flicker. This tool removes the drift
at the source: for every row, each drawn frame is translated so its foot
anchor (bottom-band centroid) lands on the row's median anchor.

Usage:
    python scripts/normalize_pet.py pets/<name> [--dry-run]

Writes spritesheet_norm.png, backs up the original as spritesheet_pre.png,
updates pet.json's spritesheetPath, and prints per-row shift ranges.
"""
from __future__ import annotations

import json
import shutil
import sys
import statistics
from pathlib import Path

from PIL import Image

ALPHA = 20
BAND = 8          # rows above the bottom that count as the "feet"


def load(pet_dir: Path):
    meta = json.loads((pet_dir / "pet.json").read_text(encoding="utf-8"))
    sheet = Image.open(pet_dir / (meta.get("spritesheetPath") or "spritesheet.png")).convert("RGBA")
    fh = int(meta.get("frameHeight") or 0) or 208
    fw = sheet.width // 8
    return meta, sheet, fw, fh


def foot_anchor(cell: Image.Image):
    """(cx, bottom) of the drawn feet: centroid-x of the bottom ALPHA band."""
    a = cell.getchannel("A")
    bbox = a.getbbox()
    if not bbox:
        return None
    l, t, r, b = bbox          # PIL bbox: right/lower are EXCLUSIVE
    bottom = b - 1
    px = a.load()
    band_top = max(t, bottom - BAND)
    sx = n = 0
    for y in range(band_top, b):
        for x in range(l, r):
            if px[x, y] > ALPHA:
                sx += x
                n += 1
    cx = (sx / n) if n else (l + r - 1) / 2
    return cx, bottom


def main() -> None:
    pet_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pets/otter")
    dry = "--dry-run" in sys.argv
    meta, sheet, fw, fh = load(pet_dir)
    rows = sheet.height // fh
    out = sheet.copy()
    report = []
    for r in range(rows):
        # per-frame valid count (contiguous prefix)
        frames = [sheet.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh))
                  for c in range(8)]
        n = 0
        for f in frames:
            if sum(f.getchannel("A").histogram()[ALPHA + 1:]) > fw * fh * 0.02:
                n += 1
            else:
                break
        anchors = [foot_anchor(frames[c]) for c in range(n)]
        anchors = [a for a in anchors if a]
        if not anchors:
            report.append((r, 0.0, 0.0, 0)); continue
        med_x = statistics.median(a[0] for a in anchors)
        med_b = statistics.median(a[1] for a in anchors)
        shifts = []
        for c in range(n):
            a = foot_anchor(frames[c])
            if not a:
                continue
            dx = int(round(med_x - a[0]))
            dy = int(round(med_b - a[1]))
            shifts.append((dx, dy))
            shifted = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
            shifted.paste(frames[c], (dx, dy))
            out.paste((0, 0, 0, 0), (c * fw, r * fh, (c + 1) * fw, (r + 1) * fh))
            out.paste(shifted, (c * fw, r * fh))
        dxs = [s[0] for s in shifts]
        dys = [s[1] for s in shifts]
        report.append((r, max(dxs) - min(dxs) if dxs else 0,
                       max(dys) - min(dys) if dys else 0, n))

    print(f"# normalize {pet_dir} ({fw}x{fh}, {rows} rows)")
    print(f"{'row':<5}{'shift X range':>14}{'shift Y range':>14}{'frames':>7}")
    for r, xr, yr, n in report:
        print(f"{r:<5}{xr:>14}{yr:>14}{n:>7}")
    if dry:
        print("(dry run - nothing written)"); return
    src_name = meta.get("spritesheetPath") or "spritesheet.png"
    pre = pet_dir / "spritesheet_pre.png"
    if not pre.exists():
        shutil.copy(pet_dir / src_name, pre)
    norm = pet_dir / "spritesheet_norm.png"
    out.save(norm)
    meta["spritesheetPath"] = "spritesheet_norm.png"
    (pet_dir / "pet.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {norm.name}; original backed up as {pre.name}; pet.json updated")


if __name__ == "__main__":
    main()
