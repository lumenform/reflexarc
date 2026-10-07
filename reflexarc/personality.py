"""Personality: slowly drifting traits that shape every decision.

Traits live in [0, 1]. They are seeded randomly on first run but drift over
days based on how the user actually lives (night coding, idle weekends...).
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Personality:
    curiosity: float = 0.5   # explores, ponders, investigates things
    clinginess: float = 0.5  # wants to be near the user, waves for attention
    laziness: float = 0.5    # rests more, moves less, slower pace
    resilience: float = 0.5  # recovers mood and stress faster
    night_owl: float = 0.4   # active phase shifts toward late hours
    name: str = "Boba"

    @classmethod
    def seeded(cls, seed: int | None = None, name: str = "Boba") -> "Personality":
        rng = random.Random(seed)
        p = cls(name=name)
        for f in fields(cls):
            if f.name == "name":
                continue
            setattr(p, f.name, round(rng.uniform(0.25, 0.75), 3))
        return p

    def clamp(self) -> None:
        for f in fields(self):
            if f.name == "name":
                continue
            v = float(getattr(self, f.name))
            setattr(self, f.name, max(0.0, min(1.0, v)))

    def drift(self, *, night_activity_ratio: float, interaction_ratio: float,
              rate: float = 0.02) -> None:
        """Blend traits toward observed lifestyle. Called periodically."""
        self.night_owl += rate * (night_activity_ratio - self.night_owl)
        self.clinginess += rate * (interaction_ratio - self.clinginess)
        self.clamp()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Personality":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Stats:
    """Raw counters used for slow personality drift and save files."""
    samples: int = 0
    active_samples: int = 0
    night_samples: int = 0
    night_active_samples: int = 0
    pets_received: int = 0
    first_seen: float = 0.0
    times_grabbed: int = 0     # picked up by the cursor
    hover_pets: int = 0        # ticks the cursor rested on the pet

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Stats":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def state_dir() -> Path:
    import os
    env = os.environ.get("REFLEXARC_HOME")
    d = Path(env) if env else (Path.home() / ".reflexarc")
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path() -> Path:
    return state_dir() / "state.json"


def load_state(default_name: str = "Boba") -> tuple[Personality, Stats, dict]:
    """Returns (personality, stats, extra_state). Creates fresh state if none."""
    path = state_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            persona = Personality.from_dict(data.get("personality", {}))
            stats = Stats.from_dict(data.get("stats", {}))
            extra = data.get("extra", {})
            return persona, stats, extra
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return Personality.seeded(name=default_name), Stats(), {}


def save_state(persona: Personality, stats: Stats, extra: dict) -> None:
    path = state_path()
    payload = {
        "version": 1,
        "personality": persona.to_dict(),
        "stats": stats.to_dict(),
        "extra": extra,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
