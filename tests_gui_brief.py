"""Brief live GUI test: show the real transparent pet window for ~10 seconds,
then quit. Also drives a speed-up so several intents appear quickly."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from reflexarc.render import PetWindow, SpriteSheet
from reflexarc.sim import Simulation

app = QApplication(sys.argv[:1])
app.setQuitOnLastWindowClosed(False)

sprites = SpriteSheet(Path(__file__).resolve().parent / "pets" / "boba")
sim = Simulation(seed=3, fresh=True, pet_name="Boba")
win = PetWindow(sim, sprites, scale=1.25)
win.show()

# force some variety for the test: cycle intents every 1.2s
from reflexarc.brain import Intent, PETDEX_ROW
import itertools, time

cycle = itertools.cycle([
    Intent.WALK_RIGHT, Intent.WATCH_USER, Intent.CHEER,
    Intent.SEEK_ATTENTION, Intent.MIRROR_WORK, Intent.PONDER,
    Intent.REST,
])

def force_intent():
    it = next(cycle)
    sim.brain.current = it
    sim.brain.time_left = 1.2
    # pin decision away: push time_left far
    QTimer.singleShot(1150, lambda: setattr(sim.brain, "time_left", 999.0))

t = QTimer()
t.timeout.connect(force_intent)
t.start(1200)
force_intent()

# move the window a bit to eyeball walking
QTimer.singleShot(5000, lambda: (win.__setattr__("pet_x", win.pet_x - 160)))

QTimer.singleShot(10000, app.quit)
print("window shown at", int(win.pet_x), int(win.pet_y), "intent:", sim.brain.current.value)
rc = app.exec()
print("exited with", rc, "final intent:", sim.brain.current.value)
