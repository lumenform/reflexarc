"""Render a frame as ASCII art so the shape can be inspected without images."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from pathlib import Path
from PySide6.QtGui import QGuiApplication

app = QGuiApplication(sys.argv[:1])
from reflexarc.render import SpriteSheet

sprites = SpriteSheet(Path(__file__).resolve().parents[1] / "pets" / "boba")
img = sprites.frame("idle", 0).toImage()

W, H = 64, 32
for j in range(H):
    row = ""
    for i in range(W):
        x = int(i * img.width() / W)
        y = int(j * img.height() / H)
        c = img.pixelColor(x, y)
        a = c.alpha()
        if a < 30:
            row += " "
        else:
            lum = (c.red() + c.green() + c.blue()) / 3
            row += "#" if lum < 110 else ("*" if lum < 190 else ".")
    print(row)
