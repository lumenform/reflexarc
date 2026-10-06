"""Calibrate the intuition layer without fine-tuning.

Laya base checkpoints are intentionally not zero-shot decision engines (the
model card says so). Fine-tuning needs a GPU we do not have, so ReflexArc
does the next best thing: measure each question's *baseline bias and spread*
across a spread of synthetic situations, then z-score every live answer
against that baseline. Only deviations from "average" survive - the model's
real conditional signal.

Usage:
    python calibrate_intuition.py --model-dir models/laya-multilingual \
        --model-key multilingual --out state/calibration.json [--n 48]
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from reflexarc.intuition import BEHAVIOUR_QUESTIONS


def synth_situation(rng: random.Random) -> str:
    hour = rng.choice([3, 8, 10, 11, 14, 16, 19, 21, 23, 23])
    activity = rng.choice(["away or idle", "quietly present", "occasionally active",
                           "typing and clicking intensely"])
    cpu = rng.choice([5, 15, 30, 55, 75, 90, 97])
    energy = round(rng.uniform(0.15, 0.9), 2)
    boredom = round(rng.uniform(0.05, 0.95), 2)
    mood = round(rng.uniform(0.3, 0.85), 2)
    attachment = round(rng.uniform(0.1, 0.8), 2)
    stress = round(rng.uniform(0.0, 0.8), 2)
    hunger = round(rng.uniform(0.0, 0.9), 2)
    window = rng.choice(["terminal", "editor", "video", "browser", "unknown"])
    return (
        f"It is around {hour:02d}:00. The user is {activity}; foreground app: "
        f"{window}. CPU load {cpu} percent. The pet: energy {energy}, boredom "
        f"{boredom}, mood {mood}, attachment {attachment}, stress {stress}, "
        f"social hunger {hunger}."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--model-key", default="multilingual")
    ap.add_argument("--out", default="state/calibration.json")
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    from laya import Router, decide

    model_dir = str(Path(args.model_dir).resolve())
    router = Router(models={args.model_key: model_dir}, device="cpu")

    rng = random.Random(args.seed)
    samples: dict[str, list[float]] = {k: [] for k in BEHAVIOUR_QUESTIONS}

    t0 = time.time()
    for i in range(args.n):
        situation = synth_situation(rng)
        res = decide(router, {"situation": situation},
                     questions=BEHAVIOUR_QUESTIONS,
                     return_details=True, model=args.model_key)
        pp = res.probabilities
        for key in BEHAVIOUR_QUESTIONS:
            v = pp.get(key, {})
            p = v.get("true") if isinstance(v, dict) else None
            if p is None and isinstance(v, dict):
                p = v.get("probabilities", {}).get("true")
            samples[key].append(float(p) if p is not None else 0.5)
        if (i + 1) % 8 == 0:
            print(f"  {i+1}/{args.n} situations in {time.time()-t0:.0f}s", flush=True)

    stats = {}
    for key, vals in samples.items():
        m = sum(vals) / len(vals)
        var = sum((v - m) ** 2 for v in vals) / max(1, len(vals) - 1)
        sd = var ** 0.5
        stats[key] = {"mean": round(m, 4), "std": round(sd, 4)}
        print(f"{key:<12} mean={m:.3f} sd={sd:.3f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "model_key": args.model_key,
        "model_dir": model_dir,
        "n": args.n,
        "stats": stats,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, indent=1), encoding="utf-8")
    print("saved ->", out)


if __name__ == "__main__":
    main()
