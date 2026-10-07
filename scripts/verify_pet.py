"""Structural self-check for a custom pet atlas (works for any art style).

Usage:
    python scripts/verify_pet.py pets/<name>

Checks, in plain numbers:
  1. pet.json loads; spritesheet file exists and has an alpha channel
  2. grid math: width divisible by 8; height = rows x frameHeight
     (frameHeight from pet.json "frameHeight", default 208)
  3. at least 9 rows; each row's contiguous non-empty frame count (4-8 ideal)
  4. v2 look rows (rows 9-10) present and pairwise different -> gaze works
  5. background transparency: frame corners are transparent
  6. ground consistency: idle frames' foot line stays within tolerance
Exit code 0 = ready to play; 1 = problems found.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROW_NAMES = ["idle", "walk-right", "walk-left", "waving", "jumping",
             "failed", "waiting", "running", "review"]
DEFAULT_FH = 208
ALPHA = 20


def sample_alpha_ratio(cell: Image.Image) -> float:
    px = cell.convert("RGBA").load()
    w, h = cell.size
    hit = tot = 0
    for y in range(0, h, 6):
        for x in range(0, w, 6):
            tot += 1
            if px[x, y][3] > ALPHA:
                hit += 1
    return hit / max(1, tot)


def foot_bottom(cell: Image.Image):
    px = cell.convert("RGBA").load()
    w, h = cell.size
    for y in range(h - 1, -1, -1):
        for x in range(0, w, 3):
            if px[x, y][3] > ALPHA:
                return y
    return None


def corners_transparent(cell: Image.Image) -> bool:
    px = cell.convert("RGBA")
    w, h = px.size
    pts = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
           (w // 10, h // 10), (w - w // 10, h // 10)]
    return all(px.getpixel(p)[3] <= 8 for p in pts)


def main() -> int:
    pet_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pets/boba")
    problems: list[str] = []
    print(f"# verify pet: {pet_dir}")

    meta_path = pet_dir / "pet.json"
    if not meta_path.exists():
        print("FAIL: pet.json not found"); return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sheet_path = pet_dir / (meta.get("spritesheetPath") or "spritesheet.webp")
    if not sheet_path.exists():
        cands = list(pet_dir.glob("*.webp")) + list(pet_dir.glob("*.png"))
        if not cands:
            print(f"FAIL: spritesheet not found ({meta.get('spritesheetPath')!r})"); return 1
        sheet_path = cands[0]
    img = Image.open(sheet_path).convert("RGBA")
    fh = int(meta.get("frameHeight") or 0) or DEFAULT_FH
    fw = img.width // 8
    rows = img.height // fh
    print(f"sheet {img.width}x{img.height} | cell {fw}x{fh} | rows {rows}"
          f" | declared={'yes' if meta.get('frameHeight') else 'no (default 208)'}")

    if img.width % 8:
        problems.append(f"width {img.width} not divisible by 8")
    if img.height % fh:
        problems.append(f"height {img.height} not divisible by frameHeight {fh}")
    if rows < 9:
        problems.append(f"only {rows} rows (need >= 9)")

    frame_counts = []
    for r in range(min(rows, 11)):
        frames = [img.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh))
                  for c in range(8)]
        n = 0
        for cell in frames:
            if sample_alpha_ratio(cell) > 0.02:
                n += 1
            else:
                break
        frame_counts.append(n)
        label = ROW_NAMES[r] if r < len(ROW_NAMES) else f"look-row{r-8}"
        note = ""
        if r < 9 and not (1 <= n <= 8):
            problems.append(f"row {r+1} ({label}): {n} valid frames")
        if r < 9 and n and n < 4:
            note = "  (few frames - ok but chunky)"
        print(f"  row {r:>2} {label:<11} frames {n}{note}")

    # look rows: 16 gaze directions should exist and differ
    look_ok = rows >= 11 and any(frame_counts[9:11])
    if rows >= 11:
        look_frames = [img.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh))
                       for r in (9, 10) for c in range(8)]
        filled = [f for f in look_frames if sample_alpha_ratio(f) > 0.02]
        same = []
        small = [f.convert("L").resize((32, 32)) for f in filled]
        bufs = [s.tobytes() for s in small]
        for i in range(len(bufs)):
            for j in range(i + 1, len(bufs)):
                diff = sum(abs(a - b) for a, b in zip(bufs[i], bufs[j]))
                if diff < 400:
                    same.append((i, j))
        if len(filled) < 16:
            problems.append(f"look rows have {len(filled)}/16 drawn frames")
        if same:
            problems.append(f"look frames too similar: {same[:5]}")
        print(f"  look rows: {len(filled)}/16 drawn, "
              f"{'differ OK' if not same else 'DUPLICATES'}")
    else:
        print("  look rows: absent (gaze degrades to idle)")

    # transparency + groundedness on idle
    idle_n = frame_counts[0] if frame_counts else 0
    if idle_n:
        corners_bad = 0
        bottoms = []
        for c in range(idle_n):
            cell = img.crop((c * fw, 0, (c + 1) * fw, fh))
            if not corners_transparent(cell):
                corners_bad += 1
            b = foot_bottom(cell)
            if b is not None:
                bottoms.append(b)
        if corners_bad:
            problems.append(f"{corners_bad} idle frames have non-transparent corners")
        if bottoms and (max(bottoms) - min(bottoms)) > max(12, fh // 10):
            problems.append(f"idle foot line varies {min(bottoms)}..{max(bottoms)} "
                            f"(engine auto-aligns, but keep it close)")
        print(f"  idle: {idle_n} frames, corner-ok {idle_n - corners_bad}/{idle_n}, "
              f"foot {min(bottoms) if bottoms else '-'}..{max(bottoms) if bottoms else '-'}")

    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  -", p)
        print("RESULT: NOT READY")
        return 1
    print("RESULT: READY TO PLAY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
