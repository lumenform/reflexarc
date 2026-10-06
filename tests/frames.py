"""Verify frames within a row actually differ (animation integrity)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from pathlib import Path
from PySide6.QtGui import QGuiApplication

app = QGuiApplication(sys.argv[:1])
from reflexarc.render import SpriteSheet, ROWS

sprites = SpriteSheet(Path(__file__).resolve().parents[1] / "pets" / "boba")

def diff(pm1, pm2):
    i1, i2 = pm1.toImage(), pm2.toImage()
    n = 0
    for y in range(0, i1.height(), 4):
        for x in range(0, i1.width(), 4):
            c1, c2 = i1.pixelColor(x, y), i2.pixelColor(x, y)
            if abs(c1.red()-c2.red()) + abs(c1.green()-c2.green()) + abs(c1.blue()-c2.blue()) + abs(c1.alpha()-c2.alpha()) > 30:
                n += 1
    return n

for row in ROWS:
    frames = [sprites.frame(row, i) for i in range(8)]
    moving = sum(1 for i in range(1, 8) if diff(frames[0], frames[i]) > 20)
    print(f"{row:<14} frames_with_diff_vs_0={moving}/7")
