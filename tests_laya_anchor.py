"""Probe 3: anchored noul questions (explicit TRUE/FALSE exemplars)."""
import time
from pathlib import Path
from laya import Router, decide

MODEL_DIR = Path(__file__).resolve().parent / "models" / "laya-multilingual"
router = Router(models={"multilingual": str(MODEL_DIR)}, device="cpu")

ANCHORS = {
    "rest": ("Should the pet curl up and sleep right now?",
             "TRUE when: it is 3am, the user is away, energy is 0.15. FALSE when: it is 11am, the user is typing heavily, energy is 0.7."),
    "walk": ("Should the pet wander around the desktop right now?",
             "TRUE when: the user has been away for a while, the pet is bored (0.8) and has plenty of energy (0.7). FALSE when: the user is working right beside it, or the pet is tired (energy 0.2), or the machine is overloaded."),
    "watch": ("Should the pet sit and quietly watch the user right now?",
             "TRUE when: the user is present and active (like an evening video session), the pet feels attached. FALSE when: the user has been gone for an hour."),
    "mirror": ("Should the pet pretend to work alongside the user right now?",
             "TRUE when: the user is typing intensely in an editor or terminal, the pet is energetic and curious. FALSE when: the user is idle or away."),
    "cheer": ("Should the pet jump happily right now?",
             "TRUE when: the pet is in an excellent mood (0.85) and the user is active and things are going well. FALSE when: the pet is tired, stressed, or lonely."),
    "seek": ("Should the pet wave to get the user's attention right now?",
             "TRUE when: the user has ignored the pet for a long time (social hunger 0.8, user away for 20+ minutes). FALSE when: the user is actively interacting."),
    "overwhelmed": ("Should the pet act dizzy and stressed right now?",
             "TRUE when: the machine is overloaded (CPU 95 percent or more) and everything is too much. FALSE when: the machine is calm."),
    "ponder": ("Should the pet stare thoughtfully into space right now?",
             "TRUE when: the pet is curious, calm, and the user is quiet or mildly active. FALSE when: the machine is overloaded or it is deep night and the pet is exhausted."),
}

SCENARIOS = {
    "deep-night-tired": "It is late night (around 23:40). The user is away or idle. CPU load 5 percent. The pet: energy 0.18 very low, boredom 0.55, mood 0.50, attachment 0.35, stress 0.0, social hunger 0.40.",
    "deep-work": "It is morning (around 11:00). The user is typing and clicking intensely in a terminal. CPU load 55 percent. The pet: energy 0.72, boredom 0.05, mood 0.70, attachment 0.65, stress 0.0, social hunger 0.05.",
    "left-alone": "It is afternoon (around 15:00). The user is away or idle. CPU load 10 percent. The pet: energy 0.55, boredom 0.85 very high, mood 0.45, attachment 0.30, stress 0.0, social hunger 0.80 very high.",
    "cpu-meltdown": "It is evening (around 19:00). The user is typing intensely in an editor. CPU load 97 percent. The pet: energy 0.55, boredom 0.10, mood 0.55, attachment 0.60, stress 0.70 high, social hunger 0.10.",
}

for name, situation in SCENARIOS.items():
    q = {}
    for key, (question, anchors) in ANCHORS.items():
        q[key] = {
            "type": "noul",
            "instructions": f"{question} {anchors}",
            "criteria": {"true": "yes, this fits the current situation",
                         "false": "no, this does not fit the current situation"},
        }
    t = time.time()
    res = decide(router, {"situation": situation}, questions=q,
                 return_details=True, model="multilingual")
    dt = time.time() - t
    pp = res.probabilities
    row = []
    for k in ANCHORS:
        v = pp.get(k, {})
        p = v.get("true") if isinstance(v, dict) else None
        if p is None and isinstance(v, dict):
            p = v.get("probabilities", {}).get("true")
        row.append(f"{k}:{p if p is None else round(p,2)}")
    print(f"[{name}] {dt:.1f}s")
    print("   ", "  ".join(row), flush=True)
