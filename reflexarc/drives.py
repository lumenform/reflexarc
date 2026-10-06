"""Homeostatic drives: the slow inner life of the pet.

All drives live in [0, 1]. Update them with small dt (seconds). The dynamics
are deliberately simple, observable and tunable - the personality layer biases
every rate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from .personality import Personality
from .senses import Observation

HOUR = 3600.0


@dataclass
class Drives:
    energy: float = 0.75      # low -> wants to rest
    boredom: float = 0.25     # high -> wants to move/explore
    mood: float = 0.65        # overall affect
    attachment: float = 0.40  # desire to be near the user
    stress: float = 0.0       # environmental tension (cpu heat, rush)
    social_hunger: float = 0.3  # unmet need for interaction

    def clamp(self) -> None:
        for f in fields(self):
            setattr(self, f.name, max(0.0, min(1.0, float(getattr(self, f.name)))))

    def update(self, obs: Observation, p: Personality, dt: float) -> None:
        if dt <= 0:
            return
        h = dt / HOUR

        user_active = obs.activity > 0.25
        deep_idle = obs.idle_seconds > 180.0

        # --- energy -------------------------------------------------------
        drain = 0.030 + 0.022 * obs.activity          # per hour
        drain *= 1.0 + 0.35 * (1.0 - p.laziness)
        if self.energy < 0.30:
            # resting state trickles energy back
            self.energy += 0.40 * h
        self.energy -= drain * h
        if obs.on_battery and obs.battery is not None and obs.battery < 0.2:
            self.energy -= 0.05 * h  # sympathize with a tired machine

        # --- boredom ------------------------------------------------------
        if user_active:
            self.boredom -= 0.80 * h
        elif deep_idle:
            self.boredom += 0.55 * h * (0.6 + 0.8 * p.curiosity)
        else:
            self.boredom += 0.16 * h

        # --- attachment & social hunger ------------------------------------
        if user_active:
            self.attachment += 0.25 * h
            self.social_hunger -= 0.50 * h
        else:
            self.attachment -= 0.05 * h
            self.social_hunger += 0.18 * h * (0.5 + p.clinginess)

        # --- stress -------------------------------------------------------
        env_stress = max(0.0, obs.cpu - 0.65) * 1.4 * (0.35 + 0.65 * obs.activity)
        target_stress = env_stress
        k = 1.0 / (600.0 * (0.5 + p.resilience))  # relax toward target
        self.stress += (target_stress - self.stress) * dt * k

        # --- mood (EMA toward a target) ------------------------------------
        target_mood = (
            0.50
            + 0.20 * (self.energy - 0.5)
            + 0.18 * (0.5 - self.boredom)
            + 0.12 * (0.5 - self.stress)
            + 0.10 * (self.attachment - 0.5)
        )
        tau = 900.0 * (0.5 + p.resilience)  # ~7-22 min time constant
        self.mood += (target_mood - self.mood) * min(1.0, dt / tau)

        self.clamp()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Drives":
        known = {f.name for f in fields(cls)}
        d = cls(**{k: v for k, v in data.items() if k in known})
        d.clamp()
        return d
