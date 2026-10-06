"""Probe 4: typed-decisions checkpoint on the same 4 scenarios (noul)."""
import time
from pathlib import Path
from laya import Router, decide

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "laya-typed"
router = Router(models={"typed-decisions": str(MODEL_DIR)}, device="cpu")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reflexarc.intuition import BEHAVIOUR_QUESTIONS

SCENARIOS = {
    "deep-night-tired": "It is late night (around 23:40). The user is away or idle. CPU load 5 percent. The pet: energy 0.18 very low, boredom 0.55, mood 0.50, attachment 0.35, stress 0.0, social hunger 0.40.",
    "deep-work": "It is morning (around 11:00). The user is typing and clicking intensely in a terminal. CPU load 55 percent. The pet: energy 0.72, boredom 0.05, mood 0.70, attachment 0.65, stress 0.0, social hunger 0.05.",
    "left-alone": "It is afternoon (around 15:00). The user is away or idle. CPU load 10 percent. The pet: energy 0.55, boredom 0.85 very high, mood 0.45, attachment 0.30, stress 0.0, social hunger 0.80 very high.",
    "cpu-meltdown": "It is evening (around 19:00). The user is typing intensely in an editor. CPU load 97 percent. The pet: energy 0.55, boredom 0.10, mood 0.55, attachment 0.60, stress 0.70 high, social hunger 0.10.",
}

from reflexarc.intuition import _p_true

for name, situation in SCENARIOS.items():
    t = time.time()
    res = decide(router, {"situation": situation}, questions=BEHAVIOUR_QUESTIONS,
                 return_details=True, model="typed-decisions")
    dt = time.time() - t
    pp = res.probabilities
    row = []
    for k in BEHAVIOUR_QUESTIONS:
        p = _p_true(pp.get(k))
        row.append(f"{k}:{'?' if p is None else round(p,2)}")
    print(f"[{name}] {dt:.1f}s")
    print("   ", "  ".join(row), flush=True)
