"""The brain: two layers working together.

1. Instinct layer - deterministic homeostatic utility. Always available,
   explainable, cheap (runs in microseconds).
2. Intuition layer - an optional non-autoregressive decision model (laya).
   It nudges the instinct scores; the pet still works with it disabled.

The brain keeps the current intent until it is finished and only switches
when the challenger clearly wins (hysteresis), so behaviour feels alive
instead of jittery.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .drives import Drives
from .personality import Personality
from .senses import Observation


class Intent(str, Enum):
    REST = "rest"                        # -> idle sprite
    WALK_LEFT = "walk-left"              # -> running-left sprite, moves left
    WALK_RIGHT = "walk-right"            # -> running-right sprite, moves right
    WATCH_USER = "watch-user"            # -> waiting sprite
    MIRROR_WORK = "mirror-work"          # -> running sprite
    CHEER = "cheer"                      # -> jumping sprite
    SEEK_ATTENTION = "seek-attention"    # -> waving sprite
    OVERWHELMED = "overwhelmed"          # -> failed sprite
    PONDER = "ponder"                    # -> review sprite


# petdex sprite rows (v1 8x9 and v2 8x11 share the first 9 rows)
PETDEX_ROW = {
    Intent.REST: "idle",
    Intent.WALK_LEFT: "running-left",
    Intent.WALK_RIGHT: "running-right",
    Intent.SEEK_ATTENTION: "waving",
    Intent.CHEER: "jumping",
    Intent.OVERWHELMED: "failed",
    Intent.WATCH_USER: "waiting",
    Intent.MIRROR_WORK: "running",
    Intent.PONDER: "review",
}

# (min_duration_s, max_duration_s, cooldown_s)
TIMING = {
    Intent.REST: (25, 90, 5),
    Intent.WALK_LEFT: (3, 9, 2),
    Intent.WALK_RIGHT: (3, 9, 2),
    Intent.WATCH_USER: (8, 20, 3),
    Intent.MIRROR_WORK: (5, 15, 3),
    Intent.CHEER: (1.6, 2.8, 8),
    Intent.SEEK_ATTENTION: (4, 9, 12),
    Intent.OVERWHELMED: (3, 6, 10),
    Intent.PONDER: (6, 14, 5),
}


class IntuitionLayer(Protocol):
    weight: float

    def scores(self, obs: Observation, drives: Drives, p: Personality,
               intents: list[Intent]) -> dict[Intent, float]:
        """Return extra scores in roughly [-1, 1] per intent."""
        ...


def night_factor(hour: float) -> float:
    """1.0 deep night, 0.0 mid-day, smooth ramps."""
    if 1.0 <= hour < 6.0:
        return 1.0
    if hour >= 23.0:
        return 1.0 - (hour - 23.0) * 0.5 - 0.0  # ramp into night
    if 6.0 <= hour < 9.0:
        return max(0.0, 1.0 - (hour - 6.0) / 3.0)
    if 21.0 <= hour < 23.0:
        return (hour - 21.0) / 2.0 * 0.6
    return 0.0


def instinct_scores(obs: Observation, d: Drives, p: Personality) -> dict[Intent, float]:
    nf = night_factor(obs.hour)
    a = obs.activity
    long_idle = min(1.0, max(0.0, (obs.idle_seconds - 120.0) / 600.0))
    mindy = obs.window_category in ("editor", "terminal")
    worky = obs.window_category in ("terminal", "editor")
    watching_media = obs.window_category == "video"
    mid_a = 4.0 * a * (1.0 - a)     # peaks at moderate activity
    tired = max(0.0, 0.62 - d.energy)

    s: dict[Intent, float] = {}
    s[Intent.REST] = (
        2.4 * (tired ** 1.5)
        + 0.65 * nf * (1.0 - 0.6 * p.night_owl)
        + 0.40 * long_idle * (1.0 - 0.55 * p.curiosity)
        - 0.45 * a * p.clinginess
    )
    walk_base = (
        1.7 * d.boredom * (0.5 + 0.5 * p.curiosity) * d.energy
        + 0.45 * long_idle * (0.4 + 0.6 * p.curiosity) * d.energy
        + 0.20 * d.energy
        - 0.9 * d.stress
    )
    s[Intent.WALK_LEFT] = s[Intent.WALK_RIGHT] = walk_base
    s[Intent.WATCH_USER] = (
        1.30 * mid_a * d.attachment
        + 0.40 * a * p.clinginess
        + (0.18 if watching_media else 0.0)
        - 0.30 * d.boredom
    )
    s[Intent.MIRROR_WORK] = (
        1.5 * max(0.0, a - 0.5) * 2.2 * (0.45 + 0.55 * p.curiosity)
        + 0.35 * a * (1.0 if worky else 0.3)
        - 1.0 * d.stress
    )
    s[Intent.CHEER] = (
        0.9 * d.mood * (0.2 + 0.8 * a)
        + 0.35 * d.mood * (1.0 - d.boredom)
        - 0.6 * d.stress
        - 0.5 * nf
    )
    s[Intent.SEEK_ATTENTION] = (
        1.9 * d.social_hunger * (0.5 + 0.5 * p.clinginess)
        + 0.9 * long_idle * (0.4 + 0.6 * p.clinginess)
        - 0.6 * d.stress
    )
    s[Intent.OVERWHELMED] = (
        2.6 * d.stress
        + 0.8 * max(0.0, obs.cpu - 0.88) * 2.5
        + 0.4 * max(0.0, 0.2 - d.energy)
    )
    s[Intent.PONDER] = (
        0.70 * p.curiosity * (1.0 - 0.85 * a)
        + (0.24 if mindy else 0.0)
        + 0.15 * (1.0 - d.boredom)
        - 0.5 * d.stress
        - 0.5 * long_idle
    )
    return s


@dataclass
class Decision:
    intent: Intent
    duration: float
    reason: str
    scores: dict[Intent, float]


class Brain:
    def __init__(self, persona: Personality, seed: int | None = None,
                 intuition: IntuitionLayer | None = None,
                 hysteresis: float = 0.12,
                 noise: float = 0.06) -> None:
        self.persona = persona
        self.rng = random.Random(seed)
        self.intuition = intuition
        self.hysteresis = hysteresis
        self.noise_amp = noise

        self.current: Intent = Intent.REST
        self.time_left: float = 1.0
        self._cooldowns: dict[Intent, float] = {i: 0.0 for i in Intent}
        self._streak: int = 0

    def interrupt(self, intent: Intent, duration: float) -> None:
        """An external event (being petted, a loud failure...) takes control
        for a moment, then normal decision making resumes."""
        self.current = intent
        self.time_left = duration

    def tick(self, dt: float) -> None:
        for k in self._cooldowns:
            if self._cooldowns[k] > 0:
                self._cooldowns[k] = max(0.0, self._cooldowns[k] - dt)
        self.time_left -= dt

    def should_decide(self) -> bool:
        return self.time_left <= 0.0

    def decide(self, obs: Observation, drives: Drives) -> Decision:
        base = instinct_scores(obs, drives, self.persona)

        if self.intuition is not None:
            try:
                extra = self.intuition.scores(obs, drives, self.persona,
                                              list(Intent))
                w = float(getattr(self.intuition, "weight", 0.0))
                for i in Intent:
                    base[i] = base.get(i, 0.0) + w * float(extra.get(i, 0.0))
            except Exception:
                # intuition must never take the pet down
                self.intuition = None

        # tiny noise so equal states never look robotic
        scores = {}
        for i in Intent:
            jitter = self.rng.uniform(-self.noise_amp, self.noise_amp)
            scores[i] = base.get(i, 0.0) + jitter
        # cooled down intents are pushed down, not banned
        for i, cd in self._cooldowns.items():
            if cd > 0:
                scores[i] -= 0.5 * min(1.0, cd / 10.0)
        # alternate walking direction instead of pacing one way forever
        if self.current is Intent.WALK_RIGHT:
            scores[Intent.WALK_LEFT] += 0.22
        elif self.current is Intent.WALK_LEFT:
            scores[Intent.WALK_RIGHT] += 0.22

        # anti-monotony: repeating one behaviour over and over gets stale
        if self._streak > 3:
            scores[self.current] -= 0.03 * min(12, self._streak - 3)

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        cur = self.current
        margin = scores[best] - scores.get(cur, -9.9)
        if best != cur and margin < self.hysteresis and self.time_left > -6.0:
            best = cur  # stay a little longer

        if best == self.current:
            self._streak += 1
        else:
            self._streak = 0

        lo, hi, cd = TIMING[best]
        duration = self.rng.uniform(lo, hi)
        reason = self._reason(best, obs, drives)
        self.current = best
        self.time_left = duration
        self._cooldowns[best] = cd
        return Decision(intent=best, duration=duration, reason=reason, scores=scores)

    def _reason(self, i: Intent, obs: Observation, d: Drives) -> str:
        if i is Intent.REST:
            return f"energy {d.energy:.2f}"
        if i in (Intent.WALK_LEFT, Intent.WALK_RIGHT):
            return f"boredom {d.boredom:.2f}"
        if i is Intent.WATCH_USER:
            return f"watching you ({obs.window_category})"
        if i is Intent.MIRROR_WORK:
            return "working alongside you"
        if i is Intent.CHEER:
            return f"mood {d.mood:.2f}"
        if i is Intent.SEEK_ATTENTION:
            return f"lonely ({d.social_hunger:.2f})"
        if i is Intent.OVERWHELMED:
            return f"stress {d.stress:.2f}"
        if i is Intent.PONDER:
            return "pondering"
        return ""
