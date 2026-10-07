"""Gaze: where the pet looks, quantised to petdex v2's 16 look directions.

Pure math - no Qt, no windows. Screen coordinates: x right, y down, angles
clockwise from straight up (0 deg = facing the viewer).  Any screen-space
delta maps to a look-frame index with

    d = round(deg(atan2(dx, -dy)) % 360 / 22.5) % 16

The controller keeps a *continuous* angle, rate-limits it toward the current
target, and only then quantises to a frame index - with hysteresis, so a
target parked on a step boundary does not make the pet twitch.  A 180-degree
turn takes about 0.35 s of visible stepping through the in-between frames.

Target priority: the cursor (when the user is moving it nearby, or when the
pet is held), else the nearest point of the foreground window's rectangle,
else a slow random wander.  Sleep pulls the gaze toward "head down" (d=8,
the over-the-shoulder frame).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

# The atlas has 16 directions, but playback quantises to 8 (45 degrees per
# step): every step is a full head redraw in this art style, so 16 steps read
# as flicker while 8 read as a head turning (verified against a 99-jump-per-
# 19s scene-change count from a reviewer's tooling).
STEPS = 8
DEG_PER_DIR = 360.0 / STEPS
ATLAS_STRIDE = 2      # each gaze step = every second look frame


def angle_of(dx: float, dy: float) -> float:
    """Screen-space delta -> angle in [0, 360), clockwise from up."""
    return math.degrees(math.atan2(dx, -dy)) % 360.0


def direction_index(dx: float, dy: float) -> int:
    """Screen-space delta -> gaze step (0..7, 45 degrees each)."""
    return int(round(angle_of(dx, dy) / DEG_PER_DIR)) % STEPS


def _lerp_angle(a: float, b: float, k: float) -> float:
    """Interpolate a -> b along the shortest arc, k in [0, 1]."""
    delta = ((b - a + 180.0) % 360.0) - 180.0
    return (a + delta * k) % 360.0


def nearest_point_on_rect(x: float, y: float,
                          rect: tuple[float, float, float, float]
                          ) -> tuple[float, float]:
    """Closest point of an (l, t, r, b) rectangle to (x, y)."""
    l, t, r, b = rect
    return (min(max(x, l), r), min(max(y, t), b))


@dataclass
class GazeInputs:
    cursor: tuple[float, float] | None = None   # global screen coords
    cursor_fresh: bool = False     # user moved the mouse recently
    cursor_settled: bool = False   # ...and it has been still for a moment
    fg_rect: tuple[float, float, float, float] | None = None
    held: bool = False             # being carried: watch the cursor
    drowsy: float = 0.0            # 0..1, pulls the gaze down
    sleepy: bool = False           # fully asleep: head down
    cursor_radius: float = 520.0   # notice the cursor within this distance
    wander_gap: tuple[float, float] = (9.0, 18.0)   # unhurried gaze drift


class GazeController:
    def __init__(self, seed: int | None = None, max_deg_per_s: float = 80.0,
                 step_hyst: float = 0.35, wander_steps: int = 1) -> None:
        self.rng = random.Random(seed)
        self.max_deg_per_s = max_deg_per_s
        self.step_hyst = step_hyst
        self.wander_steps = wander_steps

        self._angle = 0.0        # continuous gaze angle (degrees)
        self._rate = 0.0         # current turn rate (deg/s), eased
        self._idx = 0            # quantised frame index
        self._t = 0.0
        self._wander_target = 0.0
        self._wander_timer = 0.0
        self._nudge_angle: float | None = None
        self._nudge_until = 0.0

    # ------------------------------------------------------------------
    @property
    def angle(self) -> float:
        return self._angle

    @property
    def index(self) -> int:
        return self._idx

    def nudge(self, steps: int, ttl: float = 0.6) -> None:
        """Fidget hook: glance a few steps away for a moment."""
        self._nudge_angle = ((self._idx + steps) * DEG_PER_DIR) % 360.0
        self._nudge_until = self._t + ttl

    def override(self, angle: float, ttl: float = 1.0) -> None:
        self._nudge_angle = angle % 360.0
        self._nudge_until = self._t + ttl

    # ------------------------------------------------------------------
    def update(self, dt: float, eye: tuple[float, float],
               inp: GazeInputs, speed_scale: float = 1.0) -> int:
        self._t += dt
        target = self._pick_target(dt, eye, inp)

        if inp.sleepy:
            target = 180.0
        elif inp.drowsy > 0.55:
            k = (inp.drowsy - 0.55) / 0.45
            target = _lerp_angle(target, 180.0, min(1.0, k) * 0.85)

        if self._nudge_angle is not None:
            if self._t < self._nudge_until:
                target = self._nudge_angle
            else:
                self._nudge_angle = None

        speed = self.max_deg_per_s * max(0.05, speed_scale)
        if inp.drowsy > 0.55:
            speed *= 0.45
        delta = ((target - self._angle + 180.0) % 360.0) - 180.0
        # ease the *start*: a living head accelerates out of stillness
        # instead of snapping to a constant turn speed.  The approach to the
        # target keeps full speed and snaps the last fraction - a
        # proportional (exponential) approach would drag the final degrees
        # out for seconds.
        if abs(delta) < 0.5:
            self._rate = 0.0
            step = delta
        else:
            want = speed if delta > 0.0 else -speed
            self._rate += (want - self._rate) * min(1.0, 7.0 * dt)
            step = self._rate * dt
            if abs(step) > abs(delta):
                step = delta
        self._angle = (self._angle + step) % 360.0

        # quantise with hysteresis (0.5 + hyst past the step boundary)
        frac = self._angle / DEG_PER_DIR
        diff = ((frac - self._idx + STEPS / 2.0) % STEPS) - STEPS / 2.0
        if diff >= 0.5 + self.step_hyst:
            self._idx = (self._idx + 1) % STEPS
        elif diff <= -(0.5 + self.step_hyst):
            self._idx = (self._idx - 1) % STEPS
        return self._idx

    # ------------------------------------------------------------------
    def _pick_target(self, dt: float, eye: tuple[float, float],
                     inp: GazeInputs) -> float:
        ex, ey = eye
        if inp.held and inp.cursor is not None:
            return angle_of(inp.cursor[0] - ex, inp.cursor[1] - ey)
        # Only lock onto the cursor once it has *settled*.  Tracking a
        # moving cursor means re-drawing the whole head every step, which
        # reads as a twitch; a living animal watches what stops moving.
        if inp.cursor is not None and inp.cursor_settled:
            dx = inp.cursor[0] - ex
            dy = inp.cursor[1] - ey
            if dx * dx + dy * dy <= inp.cursor_radius ** 2:
                return angle_of(dx, dy)
        if inp.fg_rect is not None:
            px, py = nearest_point_on_rect(ex, ey, inp.fg_rect)
            if px != ex or py != ey:
                return angle_of(px - ex, py - ey)
        return self._wander(dt, inp)

    def _wander(self, dt: float, inp: GazeInputs) -> float:
        self._wander_timer -= dt
        if self._wander_timer <= 0.0:
            lo, hi = inp.wander_gap
            self._wander_timer = self.rng.uniform(lo, hi)
            # biased to stay near the current look, and toward the upper half
            # of the screen (the pet sits at the bottom; up is "the world")
            steps = self.rng.randint(-self.wander_steps, self.wander_steps)
            base = self._idx + steps
            if self.rng.random() < 0.35:
                base = self.rng.randint(0, STEPS - 1)   # a look anywhere
            self._wander_target = (base * DEG_PER_DIR) % 360.0
        return self._wander_target
