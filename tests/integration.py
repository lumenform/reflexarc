"""End-to-end integration test with the real intuition layer (real time).

Runs the full Simulation with senses + drives + brain + LayaIntuition for a
fixed wall-clock duration and prints decision flow and intuition status.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import time
from pathlib import Path

os.environ.setdefault("REFLEXARC_HOME", str(Path(__file__).resolve().parents[1] / "state"))

from reflexarc.intuition import LayaIntuition
from reflexarc.sim import Simulation, describe

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0

intuition = LayaIntuition(weight=0.45, refresh_s=8.0)
sim = Simulation(seed=9, fresh=True, intuition=intuition, pet_name="Boba")

print(f"# integration run: {DURATION:.0f}s, model_dir={intuition.model_dir}")
t0 = time.time()
last_status = ""
try:
    while time.time() - t0 < DURATION:
        now = time.time()
        obs = sim.senses.sample()
        d = sim.step(obs, now)
        if d is not None:
            print(f"[{now-t0:6.1f}s] {d.intent.value:<14} ({d.reason}) | intuition: {intuition.status()}", flush=True)
        if intuition.status() != last_status:
            last_status = intuition.status()
            print(f"[{now-t0:6.1f}s] intuition status: {last_status}", flush=True)
        time.sleep(0.25)
finally:
    sim.save()
    print("# final:", describe(sim.senses.sample(), sim.drives))
    print("# intuition:", intuition.status())
