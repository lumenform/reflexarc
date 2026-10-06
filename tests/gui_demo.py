"""Live demo: run the real transparent pet window for N seconds.

Usage: python -m tests.gui_demo [seconds]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from reflexarc.render import PetWindow, SpriteSheet, find_pet_dir
from reflexarc.sim import Simulation

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0

app = QApplication(sys.argv[:1])
app.setQuitOnLastWindowClosed(False)

pet_dir = find_pet_dir("boba")
sprites = SpriteSheet(pet_dir)

intuition = None
try:
    from reflexarc.intuition import LayaIntuition
    intuition = LayaIntuition(weight=0.45, refresh_s=8.0)
    print("intuition layer:", intuition.model_dir or "hub default", flush=True)
except Exception as exc:
    print("no intuition layer:", exc, flush=True)

sim = Simulation(seed=None, intuition=intuition, fresh=False, pet_name="Boba")
win = PetWindow(sim, sprites, scale=1.25)
win.show()

state = {"last": None}

def report():
    snap = sim.snapshot()
    if snap.intent != state["last"]:
        state["last"] = snap.intent
        print(f"[{snap.intent:<14}] {snap.reason}  | intuition: "
              f"{intuition.status() if intuition else 'off'}", flush=True)

t = QTimer()
t.timeout.connect(report)
t.start(500)

QTimer.singleShot(int(SECONDS * 1000), app.quit)
print(f"showing pet for {SECONDS:.0f}s at ({int(win.pet_x)},{int(win.pet_y)})", flush=True)
rc = app.exec()
sim.save()
print("demo ended", rc)
