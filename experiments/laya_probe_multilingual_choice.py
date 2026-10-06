"""Laya local-path load + zero-shot decision quality probe."""
import time, sys
from pathlib import Path

from laya import Router, decide

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "laya-multilingual"

QUESTIONS = {
    "action": {
        "type": "choice",
        "instructions": (
            "You are the intuition of a small pet living on this computer's "
            "desktop. Given `situation`, `feelings` and `personality`, pick the "
            "single behaviour that fits best right now."
        ),
        "criteria": {
            "rest": "curls up and sleeps, when tired or it is late at night",
            "walk": "wanders left and right across the desktop, when bored but energetic",
            "watch": "sits and watches the user quietly, when the user is around",
            "mirror": "pretends to work alongside the user, when the user is deep in flow",
            "cheer": "jumps happily, when in a great mood",
            "seek": "waves to get the user's attention, when lonely and ignored",
            "overwhelmed": "dizzy and stressed, when the machine is overloaded or everything is too much",
            "ponder": "stares thoughtfully into space, when curious and calm",
        },
    },
    "intensity": {
        "type": "score",
        "instructions": "How strongly should this behaviour be expressed?",
        "criteria": ["very low", "low", "medium", "high", "very high"],
    },
}

SCENARIOS = {
    "deep-night-tired": {
        "situation": "It is late night (around 23:40). The user is away or idle; foreground app: unknown. CPU load 5 percent.",
        "feelings": "energy 0.18, boredom 0.55, mood 0.50, attachment 0.35, stress 0.00, social hunger 0.40 (all 0 low to 1 high)",
        "personality": "curiosity 0.5, clinginess 0.4, laziness 0.6",
    },
    "deep-work": {
        "situation": "It is morning (around 11:00). The user is typing and clicking intensely; foreground app: terminal. CPU load 55 percent.",
        "feelings": "energy 0.72, boredom 0.05, mood 0.70, attachment 0.65, stress 0.00, social hunger 0.05 (all 0 low to 1 high)",
        "personality": "curiosity 0.5, clinginess 0.4, laziness 0.5",
    },
    "left-alone": {
        "situation": "It is afternoon (around 15:00). The user is away or idle; foreground app: unknown. CPU load 10 percent.",
        "feelings": "energy 0.55, boredom 0.85, mood 0.45, attachment 0.30, stress 0.00, social hunger 0.80 (all 0 low to 1 high)",
        "personality": "curiosity 0.6, clinginess 0.8, laziness 0.4",
    },
    "cpu-meltdown": {
        "situation": "It is evening (around 19:00). The user is typing and clicking intensely; foreground app: editor. CPU load 97 percent.",
        "feelings": "energy 0.55, boredom 0.10, mood 0.55, attachment 0.60, stress 0.70, social hunger 0.10 (all 0 low to 1 high)",
        "personality": "curiosity 0.5, clinginess 0.5, laziness 0.4",
    },
}

t0 = time.time()
print("loading Router with local multilingual path...", flush=True)
router = Router(models={"multilingual": str(MODEL_DIR)}, device="cpu")
print(f"router constructed in {time.time()-t0:.1f}s (lazy load)", flush=True)

first = True
for name, state in SCENARIOS.items():
    t = time.time()
    try:
        res = decide(router, state, questions=QUESTIONS, return_details=True,
                     model="multilingual")
        dt = time.time() - t
        try:
            answer = res.answer if hasattr(res, "answer") else res
            conf = getattr(res, "confidence", None)
            print(f"[{name}] {dt:.1f}s  answer={answer}  conf={conf}", flush=True)
        except Exception as e:
            print(f"[{name}] {dt:.1f}s raw={res!r}", flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[{name}] FAILED after {time.time()-t:.1f}s: {type(e).__name__}: {e}", flush=True)
        break
    first = False
