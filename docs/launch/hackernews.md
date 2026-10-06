# Show HN draft

**Title:** Show HN: ReflexArc - desktop pets with a nervous system (no LLM chat)

**Body:**

I have been playing with two open-source projects and ended up welding them together:

1. **petdex** - a gallery of 4,800+ animated desktop pets in a simple sprite format.
2. **laya** - a non-autoregressive "System 1" decision engine (single forward pass, no text generation).

Desktop pets today either play scripted loops or call an LLM when you click them. Both feel dead. So I gave one a *reflex arc* instead:

sensors (keyboard/mouse idle, CPU, battery, time, foreground window *category* only) -> homeostatic drives (energy, boredom, mood, attachment, stress, social hunger) -> nine behaviour candidates -> petdex sprite states.

The pet never chats. It just lives: gets sleepy at 1am, paces when bored, mirrors your deep work, waves when you have been gone too long, gets dizzy when your CPU melts down.

Three findings worth sharing:

- **laya's multilingual checkpoint is useless zero-shot here** - it picked "cheer" in 4 out of 4 wildly different scenarios. Its model card warns it is a base to specialize, not a decision engine - that is accurate.
- **The typed-decisions checkpoint is genuinely usable zero-shot**: rest scores 0.54 at 3am vs 0.10 during deep work; "overwhelmed" jumps to 0.45 at 97% CPU vs ~0.25 baseline.
- **You can specialize without a GPU.** Fine-tuning wants 2xT4 for hours. Instead I measure each question's baseline + spread over 48 synthetic situations and z-score live answers against it - the model's conditional signal survives, the bias dies. ~40 lines of code.

Architecture: deterministic homeostatic utility runs every frame (microseconds); laya intuition refreshes in a background thread every 8s (~1-3s per batch on CPU) and nudges scores with a small weight. If laya dies, the pet keeps living on instinct alone.

MIT, pure Python, sprites fetched from petdex at runtime (community art - not bundled).

Demo: docs/demo.gif
Repo: [link]

Happy to answer questions about the two-layer brain or the calibration trick.
