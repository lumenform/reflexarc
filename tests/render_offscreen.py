"""Offscreen renderer sanity check: load spritesheet, slice all rows, verify
alpha coverage and export a contact sheet PNG for eyeballing."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage, QPainter

app = QGuiApplication(sys.argv[:1])

from reflexarc.render import SpriteSheet, ROWS

pet_dir = Path(__file__).resolve().parents[1] / "pets" / "boba"
sprites = SpriteSheet(pet_dir)
print("cell:", sprites.cell_w, "x", sprites.cell_h,
      "rows:", sprites.rows_count)

out = Path(__file__).resolve().parents[1] / "state"
out.mkdir(exist_ok=True)

contact = QImage(sprites.cell_w * len(ROWS), sprites.cell_h,
                 QImage.Format_ARGB32)
contact.fill(0)
p = QPainter()
p.begin(contact)
for i, row in enumerate(ROWS):
    pm = sprites.frame(row, 0)
    p.drawPixmap(i * sprites.cell_w, 0, pm)
p.end()
contact.save(str(out / "contact_first_frames.png"))

for row in ROWS:
    pm = sprites.frame(row, 0)
    img = pm.toImage()
    opaque = 0
    total = 0
    for y in range(0, img.height(), 8):
        for x in range(0, img.width(), 8):
            total += 1
            if img.pixelColor(x, y).alpha() > 10:
                opaque += 1
    print(f"{row:<14} alpha_coverage={opaque / max(1,total):.3f}")

print("contact sheet ->", out / "contact_first_frames.png")
