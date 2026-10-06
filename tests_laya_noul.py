"""Probe 2: ask 8 independent yes/no questions instead of one 8-way choice."""
import time
from pathlib import Path
from laya import Router, decide

MODEL_DIR = Path(__file__).resolve().parent / "models" / "laya-multilingual"
router = Router(models={"multilingual": str(MODEL_DIR)}, device="cpu")

BEHAVIOURS = {
    "rest": "the pet should curl up and sleep right now (it is tired or it is very late)",
    "walk": "the pet should wander around the desktop right now (it is bored but has energy)",
    "watch": "the pet should sit and quietly watch the user right now (the user is around and present)",
    "mirror": "the pet should pretend to work alongside the user right now (the user is deep in flow)",
    "cheer": "the pet should jump happily right now (it is in a great mood and energized)",
    "seek": "the pet should wave to get the user's attention right now (it is lonely and has been ignored)",
    "overwhelmed": "the pet should act dizzy and stressed right now (the machine is overloaded or everything is too much)",
    "ponder": "the pet should stare thoughtfully into space right now (it is curious and calm)",
}

SCENARIOS = {
    "deep-night-tired": "It is late night (around 23:40). The user is away or idle. CPU load 5 percent. The pet: energy 0.18 very low, boredom 0.55, mood 0.50, attachment 0.35, stress 0.0, social hunger 0.40.",
    "deep-work": "It is morning (around 11:00). The user is typing and clicking intensely in a terminal. CPU load 55 percent. The pet: energy 0.72, boredom 0.05, mood 0.70, attachment 0.65, stress 0.0, social hunger 0.05.",
    "left-alone": "It is afternoon (around 15:00). The user is away or idle. CPU load 10 percent. The pet: energy 0.55, boredom 0.85 very high, mood 0.45, attachment 0.30, stress 0.0, social hunger 0.80 very high.",
    "cpu-meltdown": "It is evening (around 19:00). The user is typing intensely in an editor. CPU load 97 percent. The pet: energy 0.55, boredom 0.10, mood 0.55, attachment 0.60, stress 0.70 high, social hunger 0.10.",
}

for name, situation in SCENARIOS.items():
    q = {}
    for key, desc in BEHAVIOURS.items():
        q[key] = {
            "type": "noul",
            "instructions": f"In this situation: should {desc}?",
            "criteria": {"true": "yes, this fits the situation", "false": "no, a different behaviour fits better"},
        }
    state = {"situation": situation}
    t = time.time()
    res = decide(router, state, questions=q, return_details=True, model="multilingual")
    dt = time.time() - t
    probs = res.probabilities
    yes = {k: round(v.get("true", 0) + v.get("probabilities", {}).get("true", 0), 3)
           if isinstance(v, dict) else round(float(v), 3) for k, v in
           ((k, (res.answers.get(k, {}) if hasattr(res, "answers") else {})) for k in BEHAVIOURS)}
    # simpler: pull probabilities dict directly
    pp = res.probabilities
    row = []
    for k in BEHAVIOURS:
        v = pp.get(k, {})
        p_true = v.get("true") if isinstance(v, dict) else None
        if p_true is None and isinstance(v, dict):
            # noul may return 'probabilities' nested
            p_true = v.get("probabilities", {}).get("true")
        row.append(f"{k}:{p_true}")
    print(f"[{name}] {dt:.1f}s")
    print("   ", "  ".join(row), flush=True)
