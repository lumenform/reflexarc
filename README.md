# ReflexArc

English | [中文](README.zh-CN.md)

**Your desktop pet is not installed. It is raised.**

It does not chat. It does not call an LLM. It *lives* next to you: mirrors your
late-night typing, gets dizzy when the CPU melts down, waves when you have been
gone too long - and slowly turns into a night owl, because you are one.
ReflexArc gives a pet a working reflex arc instead of a script:

```
  sensors              nervous centre              effectors
+-------------+      +---------------------+      +----------------------+
| keyboard /  |      | homeostatic drives  |      | 16-direction gaze    |
| mouse idle  | ---> | energy  boredom     | ---> | breathing / shadow / |
| CPU load    |      | mood  attachment    |      | emote glyphs         |
| battery     |      | stress  social      |      | physics (walk, hop,  |
| time of day |      | hunger              |      | grabbed, thrown)     |
| window kind |      |          +          |      | petdex sprite rows   |
| cursor pos  |      | decision: instinct  |      +----------------------+
+-------------+      |  + laya intuition   |        transparent, click-
                     +---------------------+        through, always on top
                              |
                              v
                     personality drift over days
                     (night owl, clingy, lazy...)
```

The pet never chats. It just *lives* next to you: gets sleepy at 1am, paces when bored, mirrors your deep work, waves when you have been gone too long, gets dizzy when your CPU melts down.

**Real recording, no mockups** (35s: idle -> gaze follow -> petting -> picked
up and carried -> dropped on its face):

[![demo](docs/demo_life.gif)](docs/demo_life.mp4)

*Full clip: [docs/demo_life.mp4](docs/demo_life.mp4) (2.6 MB) - one continuous
real screen capture, the pet is that live Python process.*

## How it comes alive

Most desktop pets are stickers that play animations. Seven layers stacked
together are what make this one feel alive:

1. **It looks at you.** petdex v2 atlases hide 16 gaze-direction frames -
   almost every player uses only the first 9 rows. ReflexArc uses all of them:
   move your cursor nearby and it watches the cursor, turning *through* the
   in-between frames (half a turn takes 0.35 s, never a snap); switch windows
   and it turns toward your window; left alone it lets its gaze wander; sleepy
   and its head droops.
2. **It breathes, and it casts a shadow.** A slow chest-rise while standing
   (the rate follows energy and personality, deeper and slower asleep) and a
   soft shadow under its feet - hop and the shadow stays on the ground,
   shrinking and fading until it lands.
3. **It has physics.** Walking accelerates to cruise and brakes to a stop;
   joy triggers a real hop (crouch, arc, squash-and-stretch landing with one
   or two settling bounces).
4. **You can pick it up.** Press and drag and the pet is carried, legs
   kicking, watching the cursor; let go and it falls. Set it down gently and
   its mood improves; drop it hard and it gets dizzy and teary. Your desktop
   keeps working: it only takes the cursor while you *rest on the pet*, and is
   click-through everywhere else.
5. **It shows feelings.** A sleepy pet drifts `Zzz`; being petted floats
   hearts; a melting CPU makes it sweat first, shiver, then faint.
6. **It fidgets.** During quiet stretches it glances around, takes a deep
   breath, stretches, or hops a little - how often depends on its personality:
   a lazy pet sits still, a curious one keeps looking around.
7. **It remembers being handled.** Grabs, drops and pettings are counted, and
   a hard drop genuinely raises stress and sours the mood.

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
| Quiet morning, user nearby but idle | wanders (194+193) + ponders (182) + seeks attention occasionally (19) |
| Deep work, heavy typing | mirrors the user (664), occasional cheer (14) |
| Afternoon dip | stares into the distance (290), some walking, rare cheer |
| Evening video session | sits and watches the user (187) |
| 23:30 grind | stays close and watches (254), occasionally mirrors the work |
| CPU storm (97%) | dizzy/overwhelmed (230) - it panics long before your fans do |
| Left alone for hours | paces (245+245), sleeps (60), waves for you sometimes (14) |

All counts come from real simulation runs with feedback loops active: behaviours
satisfy their drives a little (walking reduces boredom, seeking attention eases
social hunger), so nothing repeats forever.  Dwell times are personality-scaled:
a lazy pet rests longer, a curious one moves on sooner.

## What it notices (privacy by design)

| Signal | Used for | Stored? |
| --- | --- | --- |
| Keyboard/mouse idle time | activity, boredom | aggregate only |
| CPU load | stress / overwhelmed behaviour | smoothed, in memory |
| Battery | "tired machine" sympathy | in memory |
| Time of day | sleep rhythm, night-owl drift | in memory |
| Foreground window *category* | watching / pondering / gaze target | category only - titles are never stored or sent |
| Cursor position | eye contact, petting, grabbing | never stored |

Nothing leaves the machine. Personality, drives and history live in `~/.reflexarc/state.json`.

## Personality that drifts

Five traits - curiosity, clinginess, laziness, resilience, night owl - seed randomly
on first run and then drift slowly toward how you actually live. Work nights for a
week and your pet becomes a night owl. It is not a setting; it is an outcome.
Personality also decides how *busy* the pet looks: a lazy pet sits quiet for long
stretches, a curious one keeps looking around and fidgeting.

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

How to play: **move the cursor near it** and it follows with its eyes; **hover on
the pet** and it gets slowly stroked (hearts); **click** for a quick pet; **press
and drag** to pick it up (let go and it falls - a gentle set-down and a hard drop
get different reactions); **tray menu** to pause or quit.

On first run the pet is fetched from the petdex manifest (`--pet-slug boba` by
default; any of the 4,800+ slugs works). Model weights for the intuition layer are
downloaded by `laya` itself on first use (HF `convaiinnovations/laya`, multilingual
or typed-decisions subfolder).

## CLI and environment

```
python run.py [--headless] [--duration N] [--fresh] [--seed N]
              [--name NAME] [--pet-slug SLUG] [--scale F] [--no-laya]
```

| Env var | Effect |
| --- | --- |
| `REFLEXARC_NO_GRAB=1` | disable picking the pet up (fully click-through again; hover/click petting stays) |
| `REFLEXARC_BREATH=0` | disable the breathing pulse |
| `REFLEXARC_EMOTES=0` | disable emote glyphs (Zzz / hearts / sweat) |
| `REFLEXARC_DEBUG_HUD=1` | print per-frame cost every 2 s and run the hit-test self-check |
| `REFLEXARC_FORCE_X/Y` | pin the window position (debug / multi-monitor) |

## Tests

```bash
python -m tests.gaze_math        # gaze maths (mapping, turn speed, hysteresis)
python -m tests.motion_physics   # physics (ramps, hop arc, landing, grabbing)
python -m tests.scenario         # fast-forward a whole simulated day
python -m tests.integration 90   # real-time end-to-end (with laya)
python -m tests.look_probe       # verify a new atlas's 16 gaze directions (Pillow)
```

The first three are zero-dependency and run in CI.  After swapping in a new pet
atlas, run `look_probe` once - a mismatched direction convention makes the pet
look the wrong way, and the probe catches it before you do.

## Status / roadmap

- [x] v0.1 - reflex arc, homeostatic drives, nine behaviours, transparent GUI, petdex format, calibrated intuition
- [x] v0.2 - life signs: 16-direction gaze, breathing, shadow, emote glyphs,
      physics (walk with momentum, hops, landing squash), grab-and-throw
      interaction, personality-scaled liveliness
- [ ] shareable personality report card ("it became a night owl in 7 days")
- [ ] multi-pet: two pets, two machines, one shared desktop
- [ ] agent hooks: react when your coding agent finishes or fails
- [ ] sound (subtle, off by default)

## Credits

- [petdex](https://github.com/crafter-station/petdex) - gallery, sprite format, desktop groundwork.
- [laya](https://github.com/NandhaKishorM/laya) - the optional intuition engine.
- Every pet artist in the petdex catalog.

MIT License.
