"""Fast-forward scenario test: drives the engine with synthetic observations
to verify that behaviour shifts plausibly across daily situations.

Not a unit test suite - a behavioural sanity check with printed evidence.
"""
from __future__ import annotations

import os
os.environ.setdefault("REFLEXARC_HOME", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state"))

import time as _time
from collections import Counter

from reflexarc.senses import Observation
from reflexarc.sim import Simulation


def synth(hour: float, activity: float, idle: float, cpu: float,
          win: str = "editor") -> Observation:
    return Observation(ts=_time.time(), hour=hour, idle_seconds=idle,
                       activity=activity, cpu=cpu, battery=0.8,
                       on_battery=False, window_category=win)


def run_phase(sim: Simulation, label: str, obs: Observation, minutes: float,
              step_s: float = 5.0) -> Counter:
    """Advance simulated time in step_s chunks for `minutes`."""
    counter = Counter()
    t = 0.0
    now = sim._t_last
    while t < minutes * 60.0:
        now += step_s
        t += step_s
        decision = sim.step(obs, now)
        if decision is not None:
            counter[decision.intent.value] += 1
    return counter


def main() -> None:
    sim = Simulation(seed=11, fresh=True, pet_name="Boba")
    phases = [
        ("morning-idle",  synth(9.0, 0.05, 300, 0.20), 90),
        ("work-flow",     synth(11.0, 0.85, 0.5, 0.55), 120),
        ("afternoon-dip", synth(15.0, 0.10, 240, 0.25), 90),
        ("evening-video", synth(20.0, 0.35, 20, 0.40, win="video"), 60),
        ("late-night-grind", synth(23.5, 0.80, 1.0, 0.75), 90),
        ("cpu-storm",     synth(23.8, 0.95, 0.5, 0.97), 30),
        ("left-alone",    synth(2.0, 0.0, 1200, 0.10), 120),
    ]
    for label, obs, minutes in phases:
        counter = run_phase(sim, label, obs, minutes)
        d = sim.drives
        top = ", ".join(f"{k}:{v}" for k, v in counter.most_common(4))
        print(f"{label:<16} | E={d.energy:.2f} B={d.boredom:.2f} M={d.mood:.2f} "
              f"A={d.attachment:.2f} S={d.stress:.2f} H={d.social_hunger:.2f} "
              f"| night_owl={sim.persona.night_owl:.2f} | {top}")
    sim.save()
    print("saved state ->", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state"))


if __name__ == "__main__":
    main()
