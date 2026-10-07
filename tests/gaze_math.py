"""Gaze maths: direction mapping, turning speed, quantisation hysteresis.

These are the invariants behind the pet's eyes, checkable without any Qt or
display.  Run with `python -m tests.gaze_math`; failures raise, so CI
notices them.

Screen coordinates: x right, y down.  Angle 0 = straight up = facing the
viewer; angles run clockwise.  Frame index d = round(angle / 22.5) % 16.
"""
from __future__ import annotations

import math

from reflexarc.gaze import (ATLAS_STRIDE, GazeController, GazeInputs, angle_of,
                            direction_index, nearest_point_on_rect)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_angle_wrap() -> None:
    check(abs(angle_of(0, -1) - 0.0) < 1e-9, "up should be 0 deg")
    check(abs(angle_of(1, 0) - 90.0) < 1e-9, "right should be 90 deg")
    check(abs(angle_of(0, 1) - 180.0) < 1e-9, "down should be 180 deg")
    check(abs(angle_of(-1, 0) - 270.0) < 1e-9, "left should be 270 deg")
    print("  angle wrap: 4 compass points OK")


def test_direction_mapping() -> None:
    # playback quantises to 8 steps (45 deg each); each step maps to every
    # second frame of the 16-direction atlas
    cases = [
        ((0, -100), 0),      # up (facing the viewer)
        ((100, -100), 1),    # up-right
        ((100, 0), 2),       # right
        ((100, 100), 3),     # down-right
        ((0, 100), 4),       # down (back to the viewer)
        ((-100, 100), 5),    # down-left
        ((-100, 0), 6),      # left
        ((-100, -100), 7),   # up-left
    ]
    for (dx, dy), want in cases:
        got = direction_index(dx, dy)
        check(got == want, f"direction_index({dx},{dy}) = {got}, want {want}")
    check(ATLAS_STRIDE == 2, "each gaze step must map to every 2nd look frame")
    print("  direction mapping: 8 compass points OK")


def test_nearest_point() -> None:
    # a window behind and above the pet: its nearest point is straight up
    p = nearest_point_on_rect(0.0, 1000.0, (-100.0, 0.0, 100.0, 900.0))
    check(p == (0.0, 900.0), f"nearest point {p}, want (0, 900)")
    p2 = nearest_point_on_rect(500.0, 500.0, (0.0, 0.0, 100.0, 100.0))
    check(p2 == (100.0, 100.0), f"nearest point {p2}, want (100, 100)")
    print("  nearest point on a window rect: OK")


def test_turn_takes_time() -> None:
    g = GazeController(seed=1)
    inp = GazeInputs(cursor=(5000.0, 0.0), cursor_fresh=True,
                     cursor_settled=True, cursor_radius=10 ** 6)
    frames = 0
    for _ in range(150):
        idx = g.update(1 / 30, (0.0, 0.0), inp)
        frames += 1
        if idx == 2:            # 90 deg = step 2 of 8
            break
    check(frames >= 5, f"a 90-deg turn snapped in {frames} frames")
    check(frames <= 75, f"a 90-deg turn took {frames} frames - too slow")
    print(f"  90-deg turn: {frames} frames (~{frames / 30:.2f}s) OK")


def test_hysteresis_no_twitch() -> None:
    """A target parked exactly on a frame boundary must not flip back and
    forth: this is what the 0.28-step hysteresis is for."""
    g = GazeController(seed=1)
    eye = (0.0, 0.0)
    a = math.radians(22.5)
    target = (math.sin(a) * 200.0, -math.cos(a) * 200.0)   # exactly 22.5 deg
    inp = GazeInputs(cursor=target, cursor_fresh=True, cursor_settled=True,
                     cursor_radius=10 ** 6)
    for _ in range(90):
        g.update(1 / 30, eye, inp)
    seen = set()
    for _ in range(180):
        seen.add(g.update(1 / 30, eye, inp))
    check(len(seen) == 1, f"gaze twitched between frames {seen}")
    print(f"  boundary stability: stays on d={seen.pop()} OK")


def test_sleepy_pulls_down() -> None:
    g = GazeController(seed=1)
    inp = GazeInputs(cursor=(5000.0, 0.0), cursor_fresh=True,
                     cursor_settled=True, cursor_radius=10 ** 6, sleepy=True)
    idx = 0
    for _ in range(150):
        idx = g.update(1 / 30, (0.0, 0.0), inp)
    check(idx == 4, f"a sleepy pet should settle looking down (4), got {idx}")
    print(f"  sleepy gaze settles on d={idx} (head down) OK")


def test_hover_target_priority() -> None:
    g = GazeController(seed=1)
    # cursor nearby beats the window rect
    inp = GazeInputs(cursor=(0.0, -300.0), cursor_fresh=True,
                     cursor_settled=True, cursor_radius=520.0,
                     fg_rect=(-500.0, -500.0, 500.0, -400.0))
    idx = g.update(1 / 30, (0.0, 0.0), inp)
    check(idx == 0, "cursor right above should be d=0")
    # cursor too far: falls back to the window rect
    inp2 = GazeInputs(cursor=(0.0, -5000.0), cursor_fresh=True,
                      cursor_settled=True, cursor_radius=520.0,
                      fg_rect=(-500.0, -500.0, 500.0, -400.0))
    for _ in range(150):
        idx = g.update(1 / 30, (0.0, 0.0), inp2)
    check(idx in (0, 7), f"far cursor should fall back to the rect (got {idx})")
    print(f"  target priority: cursor > window rect OK (d={idx})")


def main() -> None:
    print("gaze maths")
    test_angle_wrap()
    test_direction_mapping()
    test_nearest_point()
    test_turn_takes_time()
    test_hysteresis_no_twitch()
    test_sleepy_pulls_down()
    test_hover_target_priority()
    print("all gaze checks passed")


if __name__ == "__main__":
    main()
