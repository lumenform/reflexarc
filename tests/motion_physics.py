"""Motion invariants: acceleration, hop arcs, landings, walls, grabbing.

Pure maths, no Qt, no display.  Run with `python -m tests.motion_physics`.
"""
from __future__ import annotations

from reflexarc.motion import MotionController, MotionMode, MotionRequest


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def new_body(**kw) -> MotionController:
    m = MotionController(foot_x=kw.pop("foot_x", 0.0),
                         floor_y=kw.pop("floor_y", 1000.0),
                         scale=kw.pop("scale", 1.25), **kw)
    m.set_bounds(-2000.0, 2000.0)
    return m


def test_walk_ramps() -> None:
    m = new_body()
    v0 = m.vx
    m.update(1 / 60, MotionRequest(walk_dir=1), laziness=0.5)
    v1 = m.vx
    check(v1 > v0, "walking should accelerate")
    check(v1 < m._speed(0.5), "the first step must not jump to cruise")
    for _ in range(120):
        m.update(1 / 60, MotionRequest(walk_dir=1), laziness=0.5)
    cruise = m.vx
    check(abs(cruise - m._speed(0.5)) < 3.0,
          f"after 2 s the speed should be cruise ({cruise:.1f} vs "
          f"{m._speed(0.5):.1f})")
    x0 = m.x
    for _ in range(60):
        m.update(1 / 60, MotionRequest(walk_dir=0), laziness=0.5)
    check(m.vx == 0.0, "walking should stop")
    check(m.x - x0 < 30.0, f"stopping should coast a little, not slide "
                           f"({m.x - x0:.1f}px)")
    print(f"  walk: ramps to {cruise:.0f} px/s, coasts {m.x - x0:.0f}px to stop OK")


def test_hop_arc() -> None:
    m = new_body()
    m.update(1 / 60, MotionRequest(hop=True))
    hs = []
    t = 0.0
    for _ in range(120):
        p = m.update(1 / 60, MotionRequest())
        hs.append(p.h)
        t += 1 / 60
        if p.h == 0.0 and t > 0.2:
            break
    apex = max(hs)
    check(abs(apex - m.HOP_H) < m.HOP_H * 0.2,
          f"apex {apex:.0f}px should be near {m.HOP_H}px")
    check(0.35 <= t <= 0.75, f"airtime {t:.2f}s out of range")
    check(m.impact > 0.3, f"a full hop should land with impact ({m.impact:.2f})")
    print(f"  hop: apex {apex:.0f}px, airtime {t:.2f}s, "
          f"impact {m.impact:.2f} OK")


def test_landing_squash_converges() -> None:
    m = new_body()
    m.update(1 / 60, MotionRequest(hop=True))
    deepest = 1.0
    landed = False
    for i in range(240):
        p = m.update(1 / 60, MotionRequest())
        if p.h == 0.0 and i > 5:
            landed = True
        if landed:
            deepest = min(deepest, p.sy)
    check(deepest < 0.90, f"landing should squash visibly (deepest sy "
                          f"{deepest:.2f})")
    check(abs(p.sy - 1.0) < 0.01, f"squash should settle back to 1.0 "
                                  f"(got {p.sy:.3f})")
    check(abs(p.sx - 1.0) < 0.01, f"stretch should settle back to 1.0 "
                                  f"(got {p.sx:.3f})")
    print(f"  landing: squash to sy={deepest:.2f}, settles to 1.00 OK")


def test_wall_stops_without_snap() -> None:
    m = new_body()
    m.set_bounds(-50.0, 50.0)
    hit_at = None
    speeds = []
    for i in range(240):
        p = m.update(1 / 60, MotionRequest(walk_dir=1), laziness=0.5)
        speeds.append(m.vx)
        if p.hit_wall:
            hit_at = m.x
            break
    check(hit_at is not None, "should reach the wall")
    check(abs(hit_at - 50.0) < 1.0, f"should stop exactly at the wall "
                                    f"({hit_at:.1f})")
    check(m.vx == 0.0, "wall should zero the velocity")
    print(f"  wall: decelerated into x={hit_at:.1f} and stopped OK")


def test_grab_follows_cursor() -> None:
    m = new_body(foot_x=0.0, floor_y=1000.0)
    m.grab(cursor_x=0.0, cursor_y=800.0)     # feet hang 200px below cursor
    check(m.mode is MotionMode.GRABBED, "grab should enter GRABBED mode")
    for _ in range(90):
        m.update(1 / 60, MotionRequest(), cursor=(300.0, 600.0))
    check(abs(m.x - 300.0) < 25.0, f"feet should spring to the cursor x "
                                   f"({m.x:.0f})")
    check(abs(m.y - 800.0) < 25.0, f"feet should keep their offset from the "
                                   f"cursor ({m.y:.0f})")
    check(m.h > 0.0, "a held pet is airborne")
    print(f"  grab: feet track cursor at offset ({m.x - 300:.0f}, "
          f"{m.y - 600:.0f}) OK")


def test_release_falls_and_lands() -> None:
    m = new_body()
    m.grab(0.0, 700.0)
    for _ in range(60):
        m.update(1 / 60, MotionRequest(), cursor=(0.0, 700.0))
    m.release()
    check(m.mode is MotionMode.AIR, "release should go ballistic")
    landed = False
    for i in range(300):
        p = m.update(1 / 60, MotionRequest())
        if p.h == 0.0 and i > 2:
            landed = True
            break
    check(landed, "the pet must come back down")
    check(abs(m.y - 1000.0) < 0.5, f"should rest exactly on the floor "
                                   f"({m.y:.1f})")
    print(f"  release: fell and landed with impact {m.impact:.2f} OK")


def test_dropped_from_height_is_shaken() -> None:
    m = new_body()
    m.grab(0.0, 800.0)
    for _ in range(90):                      # carry it up high first
        m.update(1 / 60, MotionRequest(), cursor=(0.0, 300.0))
    check(m.h > 300.0, f"should be lifted high ({m.h:.0f}px)")
    m.release()
    for i in range(400):
        p = m.update(1 / 60, MotionRequest())
        if p.h == 0.0 and i > 2:
            break
    check(m.impact >= 0.55, f"a big drop should be a heavy impact "
                            f"({m.impact:.2f})")
    print(f"  big drop: impact {m.impact:.2f} (>= 0.55 = shaken) OK")


def main() -> None:
    print("motion physics")
    test_walk_ramps()
    test_hop_arc()
    test_landing_squash_converges()
    test_wall_stops_without_snap()
    test_grab_follows_cursor()
    test_release_falls_and_lands()
    test_dropped_from_height_is_shaken()
    print("all motion checks passed")


if __name__ == "__main__":
    main()
