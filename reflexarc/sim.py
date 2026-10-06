"""Simulation core: wires senses -> drives -> brain without any rendering.

Both the GUI app and headless mode drive this class, so behaviour can be
tested and tuned without opening a window.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .brain import Brain, Decision
from .drives import Drives
from .personality import Personality, Stats, load_state, save_state
from .senses import Observation, Senses

DRIFT_EVERY_S = 1800.0   # re-evaluate lifestyle drift every 30 min
SAVE_EVERY_S = 60.0


@dataclass
class Snapshot:
    """Everything the renderer needs for one frame."""
    intent: str            # brain.Intent value
    petdex_row: str        # sprite row name
    since_decision: float
    drives: Drives = field(default_factory=Drives)
    reason: str = ""
    last_decision_age: float = 0.0


class Simulation:
    def __init__(self, seed: int | None = None,
                 intuition: object | None = None,
                 fresh: bool = False,
                 pet_name: str = "Boba") -> None:
        self.persona, self.stats, self.extra = load_state(pet_name)
        if fresh:
            self.persona = Personality.seeded(seed, name=pet_name)
            self.stats = Stats()
            self.extra = {}
        self.persona.name = pet_name

        self.drives = Drives.from_dict(self.extra.get("drives", {}))
        self.brain = Brain(self.persona, seed=seed, intuition=intuition)
        self.senses = Senses()

        self._t_last = time.time()
        self._t_drift = 0.0
        self._t_save = 0.0
        self._last_decision: Decision | None = None
        self._last_decision_ts = 0.0

    # ------------------------------------------------------------------
    def step(self, obs: Observation, now: float | None = None) -> Decision | None:
        now = now if now is not None else time.time()
        dt = max(0.0, min(5.0, now - self._t_last))
        self._t_last = now

        self.drives.update(obs, self.persona, dt)

        # lifestyle stats for slow personality drift
        self.stats.samples += 1
        is_night = obs.hour >= 22.0 or obs.hour < 6.0
        if obs.activity > 0.25:
            self.stats.active_samples += 1
            if is_night:
                self.stats.night_active_samples += 1
        if is_night:
            self.stats.night_samples += 1

        self._t_drift += dt
        if self._t_drift >= DRIFT_EVERY_S:
            self._t_drift = 0.0
            night_ratio = (self.stats.night_active_samples /
                           max(1, self.stats.night_samples))
            interaction_ratio = (self.stats.active_samples /
                                 max(1, self.stats.samples))
            self.persona.drift(night_activity_ratio=night_ratio,
                               interaction_ratio=interaction_ratio)

        self._t_save += dt
        if self._t_save >= SAVE_EVERY_S:
            self.save()

        self.brain.tick(dt)
        decision = None
        if self.brain.should_decide():
            decision = self.brain.decide(obs, self.drives)
            self._last_decision = decision
            self._last_decision_ts = now
            self._behaviour_feedback(decision)
        return decision

    # ------------------------------------------------------------------
    def on_pet(self) -> None:
        """The user touched the pet (mouse over sprite + click). Keep the
        window click-through but still feel the affection."""
        from .brain import Intent
        d = self.drives
        d.mood = min(1.0, d.mood + 0.10)
        d.attachment = min(1.0, d.attachment + 0.06)
        d.social_hunger = max(0.0, d.social_hunger - 0.25)
        d.stress = max(0.0, d.stress - 0.12)
        self.stats.pets_received += 1
        was_resting = self.brain.current is Intent.REST
        reaction = Intent.SEEK_ATTENTION if was_resting else Intent.CHEER
        self.brain.interrupt(reaction, 1.8)

    # ------------------------------------------------------------------
    def _behaviour_feedback(self, decision: Decision) -> None:
        """Acting on a drive satisfies it a little. Rates are per hour of the
        chosen behaviour, so fast decisions do not drain drives instantly."""
        from .brain import Intent
        d = self.drives
        i = decision.intent
        dh = max(0.0, decision.duration) / 3600.0
        if i is Intent.SEEK_ATTENTION:
            d.social_hunger = max(0.0, d.social_hunger - 12.0 * dh)
            d.boredom = max(0.0, d.boredom - 1.0 * dh)
        elif i in (Intent.WALK_LEFT, Intent.WALK_RIGHT):
            d.boredom = max(0.0, d.boredom - 1.5 * dh)
        elif i is Intent.REST:
            d.energy = min(1.0, d.energy + 1.0 * dh)
        elif i in (Intent.WATCH_USER, Intent.MIRROR_WORK):
            d.social_hunger = max(0.0, d.social_hunger - 2.5 * dh)
        elif i is Intent.CHEER:
            d.mood = min(1.0, d.mood + 6.0 * dh)
            d.boredom = max(0.0, d.boredom - 2.0 * dh)
        elif i is Intent.PONDER:
            d.boredom = max(0.0, d.boredom - 0.15 * dh)

    # ------------------------------------------------------------------
    def snapshot(self, now: float | None = None) -> Snapshot:
        from .brain import PETDEX_ROW
        now = now if now is not None else time.time()
        intent = self.brain.current
        return Snapshot(
            intent=intent.value,
            petdex_row=PETDEX_ROW[intent],
            since_decision=max(0.0, now - self._last_decision_ts),
            drives=self.drives,
            reason=self._last_decision.reason if self._last_decision else "",
            last_decision_age=max(0.0, now - self._last_decision_ts),
        )

    # ------------------------------------------------------------------
    def save(self) -> None:
        self.extra["drives"] = self.drives.to_dict()
        save_state(self.persona, self.stats, self.extra)


def describe(obs: Observation, drives: Drives) -> str:
    """One-line human-readable state for logs."""
    return (
        f"hour={obs.hour:04.1f} activity={obs.activity:.2f} "
        f"idle={obs.idle_seconds:6.1f}s cpu={obs.cpu:.2f} "
        f"win={obs.window_category:<8} | "
        f"E={drives.energy:.2f} B={drives.boredom:.2f} M={drives.mood:.2f} "
        f"A={drives.attachment:.2f} S={drives.stress:.2f} "
        f"H={drives.social_hunger:.2f}"
    )
