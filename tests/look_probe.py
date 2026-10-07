"""Verify a pet atlas's 16 gaze directions against the convention used by
``gaze.py`` and ``sprites.py``:

    d = 0   straight up  (drawn facing the viewer)
    d = 4   screen right
    d = 8   straight down (drawn away from the viewer)
    d = 12  screen left

The probe locates the cream-coloured muzzle in each look frame: it swings
to the right when the pet looks right, to the left when it looks left, and
mostly disappears when the pet faces away.  If a new atlas fails these
checks, fix the row indices or the mapping before shipping it.

Run with `python -m tests.look_probe [pet_dir]` (needs Pillow).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

CELL_W, CELL_H = 192, 208
LOOK_ROWS = (9, 10)
LOOK_COUNT = 16


def muzzle_stats(cell: Image.Image) -> tuple[float, int]:
    """(centroid x, pixel count) of cream muzzle pixels."""
    px = cell.convert("RGBA").load()
    w, h = cell.size
    sx = n = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b, a = px[x, y]
            if a > 200 and r > 225 and 200 < g < 250 and 150 < b < 215:
                sx += x
                n += 1
    return ((sx / n) if n else -1.0), n


def find_sheet(pet_dir: Path) -> Path:
    meta_sheet = pet_dir / "spritesheet.webp"
    if meta_sheet.exists():
        return meta_sheet
    for cand in list(pet_dir.glob("*.webp")) + list(pet_dir.glob("*.png")):
        return cand
    raise FileNotFoundError(f"no spritesheet in {pet_dir}")


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> None:
    pet_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pets/boba")
    sheet = Image.open(find_sheet(pet_dir)).convert("RGBA")
    rows = sheet.height // CELL_H
    check(rows > max(LOOK_ROWS),
          f"atlas has {rows} rows - no v2 look rows (need >= 11)")

    stats = []
    for i in range(LOOK_COUNT):
        r, c = LOOK_ROWS[i // 8], i % 8
        cell = sheet.crop((c * CELL_W, r * CELL_H,
                           (c + 1) * CELL_W, (r + 1) * CELL_H))
        cx, n = muzzle_stats(cell)
        stats.append((cx, n))
        print(f"  d={i:2d}: muzzle_cx={cx:6.1f}  pixels={n:5d}")

    cx0, n0 = stats[0]
    cx4, n4 = stats[4]
    cx8, n8 = stats[8]
    cx12, n12 = stats[12]

    check(n0 > 100, f"front view (d=0) should show a muzzle (got {n0})")
    check(cx4 > cx0 + 10, f"looking right (d=4) should shift the muzzle "
                          f"rightward ({cx4:.0f} vs {cx0:.0f})")
    check(cx12 < cx0 - 10, f"looking left (d=12) should shift the muzzle "
                           f"leftward ({cx12:.0f} vs {cx0:.0f})")
    check(n8 < 0.6 * n0, f"facing away (d=8) should hide most of the muzzle "
                         f"({n8} vs {n0})")
    print(f"pet '{pet_dir.name}': 16 gaze directions match the convention")
    print("  d=0 front, d=4 right, d=8 away, d=12 left - all OK")


if __name__ == "__main__":
    main()
