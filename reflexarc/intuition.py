"""Intuition layer: optional non-autoregressive decision model (laya).

The model does not make the final decision. It reads a short description of
the situation and answers eight independent yes/no questions ("should I rest?",
"should I seek attention?"). Those answers are calibrated (z-scored against a
measured baseline, see calibrate_intuition.py) and blended into the instinct
scores with a small weight.

Why calibration: laya base checkpoints are deliberately not zero-shot decision
engines - the model card says to treat them as "a fast base to specialise".
Fine-tuning wants a GPU; we do not need one. Measuring each question's
baseline bias and spread over synthetic situations is enough to isolate the
model's real conditional signal.

Best-effort by construction:
- lazy load in a background thread, inference never blocks the animation
- missing calibration falls back to a conservative built-in baseline
- any failure silently disables the layer; the pet keeps living
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .brain import Intent
from .drives import Drives
from .personality import Personality, state_dir
from .senses import Observation

# ---------------------------------------------------------------- questions

BEHAVIOUR_QUESTIONS: dict[str, dict] = {
    "rest": {
        "type": "noul",
        "instructions": "In this situation: should the pet curl up and sleep right now (it is tired, or it is very late)?",
        "criteria": {"true": "yes, this fits the situation",
                     "false": "no, a different behaviour fits better"},
    },
    "walk": {
        "type": "noul",
        "instructions": "In this situation: should the pet wander around the desktop right now (it is bored but has energy)?",
        "criteria": {"true": "yes, this fits the situation",
                     "false": "no, a different behaviour fits better"},
    },
    "watch": {
        "type": "noul",
        "instructions": "In this situation: should the pet sit and quietly watch the user right now (the user is around and present)?",
        "criteria": {"true": "yes, this fits the situation",
                     "false": "no, a different behaviour fits better"},
    },
    "mirror": {
        "type": "noul",
        "instructions": "In this situation: should the pet pretend to work alongside the user right now (the user is typing intensely, deep in flow)?",
        "criteria": {"true": "yes, this fits the situation",
                     "false": "no, a different behaviour fits better"},
    },
    "cheer": {
        "type": "noul",
        "instructions": "In this situation: should the pet jump happily right now (it is in a great mood and energized)?",
        "criteria": {"true": "yes, this fits the situation",
                     "false": "no, a different behaviour fits better"},
    },
    "seek": {
        "type": "noul",
        "instructions": "In this situation: should the pet wave to get the user's attention right now (it is lonely and has been ignored for a long time)?",
        "criteria": {"true": "yes, this fits the situation",
                     "false": "no, a different behaviour fits better"},
    },
    "overwhelmed": {
        "type": "noul",
        "instructions": "In this situation: should the pet act dizzy and stressed right now (the machine is overloaded)?",
        "criteria": {"true": "yes, this fits the situation",
                     "false": "no, a different behaviour fits better"},
    },
    "ponder": {
        "type": "noul",
        "instructions": "In this situation: should the pet stare thoughtfully into space right now (it is curious and calm)?",
        "criteria": {"true": "yes, this fits the situation",
                     "false": "no, a different behaviour fits better"},
    },
}

CRITERION_TO_INTENTS: dict[str, list[Intent]] = {
    "rest": [Intent.REST],
    "walk": [Intent.WALK_LEFT, Intent.WALK_RIGHT],
    "watch": [Intent.WATCH_USER],
    "mirror": [Intent.MIRROR_WORK],
    "cheer": [Intent.CHEER],
    "seek": [Intent.SEEK_ATTENTION],
    "overwhelmed": [Intent.OVERWHELMED],
    "ponder": [Intent.PONDER],
}

# Conservative fallback baseline (measured on 4 probe scenarios; replaced by
# the full calibration file when present). mean/std of each question's P(true).
FALLBACK_STATS = {
    "rest": {"mean": 0.42, "std": 0.34},
    "walk": {"mean": 0.87, "std": 0.05},
    "watch": {"mean": 0.40, "std": 0.12},
    "mirror": {"mean": 0.16, "std": 0.09},
    "cheer": {"mean": 0.10, "std": 0.05},
    "seek": {"mean": 0.07, "std": 0.05},
    "overwhelmed": {"mean": 0.29, "std": 0.06},
    "ponder": {"mean": 0.15, "std": 0.05},
}


def _p_true(v) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        p = v.get("true")
        if isinstance(p, (int, float)):
            return float(p)
        pp = v.get("probabilities")
        if isinstance(pp, dict) and isinstance(pp.get("true"), (int, float)):
            return float(pp["true"])
    return None


def _build_situation(obs: Observation, d: Drives, p: Personality) -> str:
    h = obs.hour
    part = ("late night" if (h >= 23 or h < 5) else
            "early morning" if h < 9 else
            "morning" if h < 12 else
            "afternoon" if h < 18 else "evening")
    user = ("typing and clicking intensely" if obs.activity > 0.65 else
            "occasionally active" if obs.activity > 0.25 else
            "away or idle" if obs.idle_seconds > 120 else "quietly present")
    return (
        f"It is {part} (around {int(h):02d}:{int((h % 1) * 60):02d}). The user is "
        f"{user}; foreground app: {obs.window_category}. CPU load {obs.cpu * 100:.0f} "
        f"percent. The pet: energy {d.energy:.2f}, boredom {d.boredom:.2f}, mood "
        f"{d.mood:.2f}, attachment {d.attachment:.2f}, stress {d.stress:.2f}, "
        f"social hunger {d.social_hunger:.2f}."
    )


class LayaIntuition:
    def __init__(self, weight: float = 0.45, refresh_s: float = 8.0,
                 device: str = "cpu", model_dir: str | None = None,
                 model_key: str | None = None,
                 calibration: str | Path | None = None) -> None:
        self.weight = weight
        self.refresh_s = refresh_s
        self.device = device
        self.model_dir, self.model_key = self._resolve_source(model_dir, model_key)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="laya")
        self._lock = threading.Lock()
        self._latest: dict[Intent, float] = {}
        self._last_submit = 0.0
        self._busy = False
        self._router = None
        self._status = "warming up"
        self.last_latency_ms: float | None = None
        self._stats = dict(FALLBACK_STATS)
        self._load_calibration(calibration)

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_source(model_dir: str | None, model_key: str | None) -> tuple[str | None, str]:
        if model_dir:
            return str(Path(model_dir).resolve()), model_key or "multilingual"
        env = os.environ.get("REFLEXARC_MODEL_DIR")
        if env:
            return str(Path(env).resolve()), model_key or "multilingual"
        root = Path(__file__).resolve().parent.parent / "models"
        for cand, key in ((root / "laya-typed", "typed-decisions"),
                          (root / "laya-multilingual", "multilingual")):
            if (cand / "model.safetensors").exists():
                return str(cand), key
        return None, model_key or "multilingual"

    def _load_calibration(self, path: str | Path | None) -> None:
        cands = []
        if path:
            cands.append(Path(path))
        cands.append(state_dir() / "calibration.json")
        for c in cands:
            try:
                if c.exists():
                    data = json.loads(c.read_text(encoding="utf-8"))
                    stats = data.get("stats", {})
                    for k, v in stats.items():
                        if k in self._stats and isinstance(v.get("mean"), (int, float)):
                            self._stats[k] = {"mean": float(v["mean"]),
                                              "std": max(0.05, float(v.get("std", 0.1)))}
                    self._status = f"calibrated ({data.get('n', '?')} samples)"
                    return
            except Exception:
                continue

    def status(self) -> str:
        return self._status

    def _ensure_router(self):
        if self._router is not None:
            return self._router
        from laya import Router
        if self.model_dir and Path(self.model_dir, "model.safetensors").exists():
            self._router = Router(models={self.model_key: self.model_dir},
                                  device=self.device)
        else:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            self._router = Router(device=self.device)
        return self._router

    def _infer(self, situation: str) -> None:
        try:
            from laya import decide
            router = self._ensure_router()
            t0 = time.time()
            res = decide(router, {"situation": situation},
                         questions=BEHAVIOUR_QUESTIONS,
                         return_details=True, model=self.model_key)
            self.last_latency_ms = (time.time() - t0) * 1000.0
            scores = self._interpret(res)
            with self._lock:
                self._latest = scores
            self._status = f"live ({self.last_latency_ms:.0f} ms)"
        except Exception as exc:
            self._status = f"disabled: {type(exc).__name__}: {exc}"
        finally:
            self._busy = False

    def _interpret(self, result) -> dict[Intent, float]:
        pp = getattr(result, "probabilities", None)
        if not isinstance(pp, dict):
            ans = getattr(result, "answer", None) or getattr(result, "values", None)
            pp = ans if isinstance(ans, dict) else {}
        scores: dict[Intent, float] = {}
        for key, intents in CRITERION_TO_INTENTS.items():
            p = _p_true(pp.get(key))
            if p is None:
                continue
            st = self._stats.get(key, {"mean": 0.5, "std": 0.2})
            sd = max(0.05, float(st.get("std", 0.2)))
            z = (p - float(st.get("mean", 0.5))) / sd
            val = max(-1.0, min(1.0, z / 2.5))
            for it in intents:
                scores[it] = val
        return scores

    # ------------------------------------------------------------------
    def scores(self, obs: Observation, drives: Drives, p: Personality,
               intents: list[Intent]) -> dict[Intent, float]:
        now = time.time()
        if (not self._busy) and (now - self._last_submit) >= self.refresh_s:
            self._busy = True
            self._last_submit = now
            self._pool.submit(self._infer, _build_situation(obs, drives, p))
        with self._lock:
            return dict(self._latest)


def create_intuition(weight: float = 0.45, refresh_s: float = 8.0) -> LayaIntuition:
    return LayaIntuition(weight=weight, refresh_s=refresh_s)
