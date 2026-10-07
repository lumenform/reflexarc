# Show HN draft (v2)

**Title:** Show HN: ReflexArc - a desktop pet with homeostasis and no LLM chat (you can pick it up)

**Body:**

Your desktop pet is not installed - it is raised. No chat, no LLM calls: it has
homeostatic drives (energy, boredom, mood, attachment, stress, social hunger)
and a reflex arc. Mine mirrors late-night typing, gets dizzy when the CPU melts
down, waves when ignored, and turned into a night owl because I am one.

The part people usually ask about first: **you can interact with it without any
"AI" involved.** Move your cursor nearby and it turns its head and watches you
(16 gaze directions). Hover to pet it - hearts pop. **Press and drag and you can
pick it up** - it dangles, legs kicking, watching the cursor; set it down gently
and it's happy, drop it and it lands dizzy. Double-click and a tiny status
bubble shows what it wants right now. 35s real screen recording in the README.

I welded two open-source projects together:

1. **petdex** - a gallery of 4,800+ animated desktop pets in an open sprite format.
2. **laya** - a non-autoregressive "System 1" decision engine (single forward pass, no text generation).

Sensors (keyboard/mouse idle, CPU, battery, time, foreground window *category*
only) feed the drives; a deterministic utility picks among nine behaviours every
few seconds; laya's intuition refreshes in a background thread every 8s and
nudges the scores. If laya dies, the pet keeps living on instinct alone.

Three findings worth sharing:

- **laya's multilingual checkpoint is useless zero-shot here** - it picked
  "cheer" in 4/4 wildly different scenarios. The model card warns it is a base
  to specialize; that is accurate.
- **The typed-decisions checkpoint is genuinely usable**: rest scores 0.54 at
  3am vs 0.10 during deep work; "overwhelmed" hits 0.45 at 97% CPU.
- **You can specialize without a GPU**: measure each question's baseline over
  48 synthetic situations and z-score live answers. ~40 lines of code.

Physics is tiny but present: walk acceleration, hop arcs, landing squash, grab
and throw. Sound is four soft one-second otter clips, rate-limited, off-switch
included. MIT, pure Python + PySide6.

Repo: <link>
Demo GIF (repo README): docs/demo_life.gif

Happy to answer questions about the reflex-arc design, the calibration trick,
or the grab-and-throw physics.
