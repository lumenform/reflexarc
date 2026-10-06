"""Build a demo GIF from the petdex spritesheet: a small story of the pet's day.

Story beats: working alongside you -> watching a video -> pondering ->
wandering -> cheering -> seeking attention -> tired -> overwhelmed -> repeat.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SHEET = ROOT / "pets" / "boba" / "spritesheet.webp"
OUT = ROOT / "docs" / "demo.gif"
SCALE = 2

ROWS = ["idle", "running-right", "running-left", "waving", "jumping",
        "failed", "waiting", "running", "review"]

# (row, label, loops)
STORY = [
    ("running", "working alongside you"),
    ("waiting", "watching the video with you"),
    ("review", "pondering"),
    ("running-right", "bored, wandering"),
    ("jumping", "cheerful"),
    ("waving", "you have been gone a while"),
    ("idle", "tired..."),
    ("failed", "cpu at 97% - dizzy"),
]

FRAME_MS = 110
BG = (24, 24, 37)
FLOOR = (36, 36, 54)
TEXT = (200, 200, 220)


def load_font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    sheet = Image.open(SHEET).convert("RGBA")
    cw, ch = sheet.width // 8, sheet.height // 11

    w, h = cw * SCALE, ch * SCALE + 46
    font = load_font(19 * SCALE // 2 + 4)

    frames = []
    for row, label in STORY:
        r = ROWS.index(row)
        for c in range(8):
            cell = sheet.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))
            cell = cell.resize((cw * SCALE, ch * SCALE), Image.LANCZOS)

            canvas = Image.new("RGB", (w, h), BG)
            draw = ImageDraw.Draw(canvas)
            # floor strip
            draw.rectangle([0, h - 34, w, h], fill=FLOOR)
            draw.rectangle([0, h - 36, w, h - 34], fill=(52, 52, 76))
            # caption
            draw.text((16, 12), label, font=font, fill=TEXT)

            # composite pet centered on the floor
            px = (w - cell.width) // 2
            py = h - 34 - cell.height + 6
            canvas.paste(cell, (px, py), cell)
            frames.append(canvas)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(OUT, save_all=True, append_images=frames[1:],
                   duration=FRAME_MS, loop=0, optimize=True)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"saved {OUT} ({len(frames)} frames, {size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
