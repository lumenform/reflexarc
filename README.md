# ReflexArc 反射弧

English | [中文](README.zh-CN.md)

**Your desktop pet is not installed. It is raised.**

It does not chat. It does not call an LLM. It *lives* next to you: mirrors your
late-night typing, gets dizzy when the CPU melts down, waves when you have been
gone too long - and slowly turns into a night owl, because you are one.
ReflexArc gives a pet a working reflex arc instead of a script:

```
  sensors              nervous centre               effectors
+-------------+      +---------------------+      +------------------+
| keyboard /  |      | homeostatic drives  |      | petdex sprite    |
| mouse idle  | ---> | energy  boredom     | ---> | idle / walking / |
| CPU load    |      | mood  attachment    |      | waving / jumping |
| battery     |      | stress  social      |      | failed / waiting |
| time of day |      | hunger              |      | running / review |
| window kind |      |          +          |      +------------------+
+-------------+      | decision: instinct  |               ^
                     |  + laya intuition   |         transparent,
                     +---------------------+         click-through
                              |                     window
                              v
                     personality drift over days
                     (night owl, clingy, lazy...)
```

The pet never chats. It just *lives* next to you: gets sleepy at 1am, paces when bored, mirrors your deep work, waves when you have been gone too long, gets dizzy when your CPU melts down.

**Real recording, no mockups** (96s: typing -> CPU pinned -> petting; mid-section at 3x):

[![demo](docs/demo_real.gif)](docs/demo_real.mp4)

*Full clip: [docs/demo_real.mp4](docs/demo_real.mp4) (4 MB) - it is one continuous real screen capture, the pet is a live Python process on the right.*

## Assembled from

- **[petdex](https://github.com/crafter-station/petdex)** - 4,800+ community-animated pets in an open sprite format. ReflexArc uses them as the *body*: pets are fetched at runtime from the petdex manifest, and local `~/.petdex/pets` / `~/.codex/pets` installs are used when present. Pet art belongs to its submitters and is not bundled here.
- **[laya](https://github.com/NandhaKishorM/laya)** - a non-autoregressive "System 1" decision engine (single forward pass over any text, no generation). Optional: it acts as the pet's *intuition*, nudging behaviour choices by a small weight.

## Two layers of decisions

1. **Instinct** - always on, deterministic, microseconds. A utility function scores nine candidate behaviours against the current drives and ambient observations. This is the pet's spine: explainable, predictable, and it never fails.
2. **Intuition** - optional. laya answers eight independent yes/no questions about the situation ("should the pet rest right now?", "should it seek attention?"). Answers are calibrated (below) and blended in with a small weight. If laya is missing, slow, or wrong, the pet keeps living on instinct alone.

### Field notes: making a base model usable without a GPU

Straight answers from the build, in case you want to use laya for something similar:

- **The multilingual checkpoint is useless zero-shot for this task.** Across four wildly
  different situations (3am exhausted / deep work / left alone / 97% CPU) it picked
  "cheer" every single time. Its model card says to treat laya as *a fast base to
  specialise, not a zero-shot decision engine* - that is accurate.
- **The typed-decisions checkpoint is genuinely usable.** Zero-shot: "rest" scores 0.54
  at 3am vs 0.10 during deep work; "overwhelmed" jumps to 0.45 at 97% CPU vs a ~0.25
  baseline; "mirror" 0.61-0.67 during focused work vs 0.22 idle.
- **You can specialise without fine-tuning.** Fine-tuning wants a 2xT4 for hours.
  Instead, `calibrate_intuition.py` samples ~48 synthetic situations, measures each
  question's baseline (mean/spread), and live answers are z-scored against it. The
  model's conditional signal survives; its blanket bias dies. ~40 lines of code.
- **Speed**: ~3.5s per batch of eight questions on CPU (first call ~25s while the
  614-800MB checkpoint loads). Far too slow for a game loop, which is why intuition
  runs in a background thread, refreshes every ~8s, and is blended as a *nudge*, not
  an oracle.

## Behaviour, observed

From `tests/scenario.py` - the same pet fast-forwarded across a simulated day:

| Situation | What happens |
| --- | --- |
| Quiet morning, user nearby but idle | ponders (228) + wanders (278) + seeks attention occasionally (22) |
| Deep work, heavy typing | mirrors the user (575), occasional cheer |
| Afternoon dip | stares into the distance (355), some walking, rare cheer |
| Evening video session | sits and watches the user (220) |
| 23:30 grind | stays close and watches (281), occasionally mirrors the work |
| CPU storm (97%) | dizzy/overwhelmed (221) - it panics long before your fans do (mirror drops to 27) |
| Left alone for hours | paces (361), sleeps (71), waves for you sometimes (15) |

All counts come from real simulation runs with feedback loops active: behaviours
satisfy their drives a little (walking reduces boredom, seeking attention eases
social hunger), so nothing repeats forever.

## What it notices (privacy by design)

| Signal | Used for | Stored? |
| --- | --- | --- |
| Keyboard/mouse idle time | activity, boredom | aggregate only |
| CPU load | stress / overwhelmed behaviour | smoothed, in memory |
| Battery | "tired machine" sympathy | in memory |
| Time of day | sleep rhythm, night-owl drift | in memory |
| Foreground window *category* | watching/pondering | category only - titles are never stored or sent |

Nothing leaves the machine. Personality, drives and history live in `~/.reflexarc/state.json`.

## Personality that drifts

Five traits - curiosity, clinginess, laziness, resilience, night owl - seed randomly
on first run and then drift slowly toward how you actually live. Work nights for a
week and your pet becomes a night owl. It is not a setting; it is an outcome.

## Quick start

```bash
# core engine, zero dependencies (headless)
python run.py --headless --duration 30 --fresh

# GUI pet: transparent, click-through, always on top
pip install PySide6 psutil
python run.py --scale 1.25

# optional intuition layer
pip install "laya[onnx]"          # or: pip install laya
python calibrate_intuition.py --model-dir models/laya-typed \
    --model-key typed-decisions --out state/calibration.json --n 48
python run.py --scale 1.25        # intuition auto-detected
python run.py --no-laya           # or keep it off
```

On first run the pet is fetched from the petdex manifest (`--pet-slug boba` by
default; any of the 4,800+ slugs works). Model weights for the intuition layer are
downloaded by `laya` itself on first use (HF `convaiinnovations/laya`, multilingual
or typed-decisions subfolder).

## CLI

```
python run.py [--headless] [--duration N] [--fresh] [--seed N]
              [--name NAME] [--pet-slug SLUG] [--scale F] [--no-laya]
```

## Status / roadmap

- [x] v0.1 - reflex arc, homeostatic drives, nine behaviours, transparent GUI, petdex format, calibrated intuition
- [x] petting - hover the sprite and click (the window is click-through, but the pet still feels you). It gets calmer and happier; wake it from a nap and it waves at you
- [ ] shareable personality report card ("it became a night owl in 7 days")
- [ ] multi-pet: two pets, two machines, one shared desktop
- [ ] agent hooks: react when your coding agent finishes or fails
- [ ] sound (subtle, off by default)

## Credits

- [petdex](https://github.com/crafter-station/petdex) - gallery, sprite format, desktop groundwork.
- [laya](https://github.com/NandhaKishorM/laya) - the optional intuition engine.
- Every pet artist in the petdex catalog.

MIT License.
