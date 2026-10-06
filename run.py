"""ReflexArc launcher.

Usage examples:
    python run.py --headless --duration 60
    python run.py --headless --scenario night
    python run.py                # GUI (needs PySide6)
"""
from __future__ import annotations

import argparse
import sys
import time

from reflexarc.sim import Simulation, describe


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="reflexarc",
                                 description="A nervous system for desktop pets.")
    ap.add_argument("--headless", action="store_true",
                    help="no GUI; print state lines instead")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="headless: stop after N seconds (0 = forever)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--fresh", action="store_true",
                    help="ignore saved personality and start fresh")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="time multiplier for drives (debug aid)")
    ap.add_argument("--every", type=float, default=2.0,
                    help="headless: print an observation every N seconds")
    ap.add_argument("--name", type=str, default="Boba")
    ap.add_argument("--pet-slug", type=str, default="boba",
                    help="petdex slug to fetch/use when no local pet folder matches")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="sprite scale for the GUI window")
    ap.add_argument("--no-laya", action="store_true",
                    help="disable the laya intuition layer")
    return ap.parse_args()


def run_headless(args: argparse.Namespace) -> int:
    sim = Simulation(seed=args.seed, fresh=args.fresh, pet_name=args.name)
    print(f"# ReflexArc headless | pet={sim.persona.name} "
          f"curiosity={sim.persona.curiosity:.2f} clinginess={sim.persona.clinginess:.2f} "
          f"laziness={sim.persona.laziness:.2f} night_owl={sim.persona.night_owl:.2f}",
          flush=True)

    t0 = time.time()
    last_print = 0.0
    try:
        while True:
            now = time.time()
            obs = sim.senses.sample()
            decision = sim.step(obs, now)
            if decision is not None:
                snap = sim.snapshot(now)
                print(f"[{now - t0:7.1f}s] DECIDE  {snap.intent:<14} "
                      f"({snap.reason})  | {describe(obs, sim.drives)}", flush=True)
            elif now - last_print >= args.every:
                last_print = now
                snap = sim.snapshot(now)
                print(f"[{now - t0:7.1f}s] hold    {snap.intent:<14} "
                      f"| {describe(obs, sim.drives)}", flush=True)

            if args.duration and (now - t0) >= args.duration:
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        sim.save()
    print("# done", flush=True)
    return 0


def run_gui(args: argparse.Namespace) -> int:
    try:
        from reflexarc.render import main as render_main  # noqa: WPS433
    except ImportError as exc:
        print("GUI requires PySide6. Install it or use --headless.\n"
              f"({exc})", file=sys.stderr)
        return 2
    return render_main(args)


def main() -> int:
    args = parse_args()
    if args.headless:
        return run_headless(args)
    return run_gui(args)


if __name__ == "__main__":
    raise SystemExit(main())
