# ReflexArc 反射弧

**A nervous system for desktop pets.**

ReflexArc gives a desktop pet a working reflex arc: sensors (what is happening on the machine) -> a nervous centre (homeostatic drives + decisions) -> effectors (sprite animation). The pet does not chat. It does not call an LLM every few seconds. It just *lives* next to you - tired when you work late, bored when you are gone, dizzy when the machine is overloaded.

It is assembled from two open-source worlds:

- **[petdex](https://petdex.dev)** - 4,800+ animated pets, a public gallery in a simple sprite format. ReflexArc uses petdex pets as the *body* and reads pets from `~/.petdex/pets`, `~/.codex/pets`, or a local `pets/` folder.
- **[laya](https://github.com/NandhaKishorM/laya)** - a non-autoregressive decision engine (single forward pass, CPU-friendly). Optional: it acts as the pet's *intuition*, nudging behaviour choices without making them.

> The petdex gallery gave them a body. ReflexArc gives them instincts.

## How it works

```
  sensors                nervous centre                 effectors
+-------------+      +---------------------+      +------------------+
| keyboard /  |      | homeostatic drives  |      | petdex sprite    |
| mouse idle  | ---> | energy  boredom     | ---> | idle / walking / |
| CPU load    |      | mood  attachment    |      | waving / jumping |
| battery     |      | stress  social      |      | failed / waiting |
| time of day |      | hunger              |      | running / review |
| window kind |      |          +          |      +------------------+
+-------------+      |  decision (utility +|               ^
                     |  optional laya      |               |
                     |  intuition)         |         transparent,
                     +---------------------+         click-through
                              |                     window
                              v
                     personality drift
                     (night owl, clingy, lazy...)
```

### Two layers of decisions

1. **Instinct** (always on, deterministic, microseconds). A utility function
   scores nine candidate behaviours against the current drives and ambient
   observations. This is the pet's spine - explainable and predictable.
2. **Intuition** (optional). `laya` reads a short natural-language description
   of the situation plus the pet's drives and suggests what *feels* right.
   Its suggestion is blended with a small weight; if it is unavailable,
   slow, or wrong, the pet keeps living on instinct alone.

## What it notices (privacy by design)

| Signal | Used for | Stored? |
| --- | --- | --- |
| Keyboard/mouse idle time | activity, boredom | aggregate only |
| CPU load | stress / overwhelmed behaviour | smoothed, in memory |
| Battery | "tired machine" sympathy | in memory |
| Time of day | sleep rhythm, night owl drift | in memory |
| Foreground window *category* | watching/pondering | category only - **titles are never stored or transmitted** |

Nothing leaves the machine. Personality and drives live in `~/.reflexarc/state.json`.

## Behaviour, observed

From the fast-forward scenario test (`tests_scenario.py`), the same pet across a
simulated day:

| Situation | Dominant behaviour |
| --- | --- |
| Quiet morning, nobody around | paces left and right, ponders |
| Deep work, heavy typing | mirrors the user (running in place) |
| Afternoon dip | stares into the distance, occasional walk |
| Evening video session | sits and watches the user |
| 23:30 grind | stays close and watches |
| CPU storm (97%) | dizzy / overwhelmed |
| Left alone for hours | curls up, sleeps, occasionally waves |

## Personality that drifts

Five traits: curiosity, clinginess, laziness, resilience, night owl. They seed
randomly on first run and then drift slowly toward how you actually live - work
nights for a week and your pet becomes a night owl.

## Quick start

```bash
# core (no dependencies beyond the stdlib)
python run.py --headless --duration 30 --fresh

# GUI pet (transparent, click-through, always on top)
pip install PySide6 psutil
python run.py --scale 1.25

# optional intuition layer (first run downloads ~614 MB)
pip install "laya[onnx]"
python run.py --no-laya      # to disable it
```

Pets are fetched automatically from the petdex manifest on first run
(`--pet-slug boba` by default; any of the 4,800+ slugs works). If you already
use petdex, ReflexArc also reads your installed pets from `~/.petdex/pets` and
`~/.codex/pets`.

## CLI

```
python run.py [--headless] [--duration N] [--fresh] [--seed N]
              [--name NAME] [--pet-slug SLUG] [--scale F]
              [--no-laya]
```

## Status / roadmap

- [x] v0.1 - reflex arc, drives, nine states, transparent GUI, petdex format
- [ ] click/touch interaction (pet the pet)
- [ ] multi-pet: two pets from two machines meeting on a shared desktop
- [ ] agent hooks: react when your coding agent finishes or fails
- [ ] sound (subtle, off by default)

## Credits

- [petdex](https://github.com/crafter-station/petdex) - pet gallery, sprite format, desktop groundwork. Pets are community art, owned by their submitters; ReflexArc downloads them on demand and does not bundle them.
- [laya](https://github.com/NandhaKishorM/laya) - non-autoregressive decision engine used as the optional intuition layer.
- The whole open-source pet ecosystem that made this possible.

MIT License.
