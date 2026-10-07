"""The body: walking momentum, hops, being grabbed and thrown, landings.

Pure math - no Qt, no windows.  The controller owns the pet's *body*: where
its feet are, how tall/squashed it currently is, whether it is on the floor.
The brain owns *intent*; the two meet only in the renderer, which translates
intents into a MotionRequest and lets the pose win visually.

Coordinates: global logical screen pixels.  The anchor is the pet's feet;
``floor_y`` is the line it stands on.  ``y`` is the feet's screen y, so
``height = floor_y - y`` (0 when standing).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum


class MotionMode(str, Enum):
    BASE = "base"          # on the floor, walking or standing
    AIR = "air"            # ballistic (hop, thrown)
    GRABBED = "grabbed"    # held by the cursor, springing along


@dataclass
class MotionRequest:
    """What the renderer asks the body to do this frame (brain-translated)."""
    walk_dir: int = 0        # -1 / 0 / +1
    hop: bool = False        # edge-triggered: one hop per True run
    small_hop: bool = False  # fidget hop (lower)
    hop_height: float = 0.0  # 0 = default


@dataclass
class Pose:
    x: float
    y: float                       # feet, screen y
    floor_y: float
    h: float = 0.0                 # height above the floor (>= 0)
    sx: float = 1.0
    sy: float = 1.0
    impact: float = 0.0            # last landing impact 0..1 (renderer consumes)
    mode: str = "base"
    on_ground: bool = True
    held: bool = False
    hit_wall: bool = False
    row_override: str | None = None
    frame_override: float | None = None


class MotionController:
    GRAVITY = 2800.0     # px/s^2
    HOP_H = 92.0
    SMALL_HOP_H = 46.0   # fidget hop: visible from the corner of your eye
    # grab spring: soft and slightly under-damped - the pet hangs with
    # weight instead of rigidly following the cursor
    GRAB_K = 260.0
    GRAB_C = 27.4        # ~0.85 damping ratio

    def __init__(self, foot_x: float, floor_y: float, scale: float = 1.0,
                 rng: random.Random | None = None) -> None:
        self.x = float(foot_x)
        self.y = float(floor_y)
        self.floor_y = float(floor_y)
        self.scale = scale
        self.rng = rng or random.Random()

        self.vx = 0.0
        self.vy = 0.0
        self.mode = MotionMode.BASE

        self._c = 0.0        # squash: + compressed, - stretched
        self._cv = 0.0
        self._crouch = 0.0
        self._hop_h = self.HOP_H

        self._off_x = 0.0    # cursor -> feet offset while grabbed
        self._off_y = 0.0

        self.left = -1.0e9
        self.right = 1.0e9
        self.impact = 0.0
        self.hit_wall = False

    # ------------------------------------------------------------------
    @property
    def h(self) -> float:
        return max(0.0, self.floor_y - self.y)

    @property
    def held(self) -> bool:
        return self.mode is MotionMode.GRABBED

    def set_bounds(self, left: float, right: float) -> None:
        self.left = float(left)
        self.right = float(right)

    def set_floor(self, floor_y: float) -> None:
        self.floor_y = float(floor_y)
        if self.mode is MotionMode.BASE:
            self.y = self.floor_y

    def teleport(self, foot_x: float, floor_y: float | None = None) -> None:
        self.x = float(foot_x)
        if floor_y is not None:
            self.floor_y = float(floor_y)
        self.y = min(self.y, self.floor_y) if self.mode is not MotionMode.AIR \
            else self.y
        self.vx = 0.0
        self.vy = 0.0

    # ---- grabbing -----------------------------------------------------
    def grab(self, cursor_x: float, cursor_y: float) -> None:
        """Pick the pet up: the feet keep their offset from the cursor."""
        self._off_x = self.x - cursor_x
        self._off_y = self.y - cursor_y
        self.mode = MotionMode.GRABBED
        self.vx = 0.0
        self.vy = 0.0
        self._c = -0.04

    def release(self) -> None:
        """Let go: inherit the spring's velocity, cap the throw."""
        if self.mode is not MotionMode.GRABBED:
            return
        self.mode = MotionMode.AIR
        self.vy = max(-1600.0, min(1600.0, self.vy))
        self.vx = max(-2600.0, min(2600.0, self.vx))
        if self.y >= self.floor_y:
            self.y = self.floor_y - 0.01

    # ------------------------------------------------------------------
    def _speed(self, laziness: float) -> float:
        base = 52.0 * (1.12 - 0.35 * laziness)
        return base * self.scale

    def update(self, dt: float, req: MotionRequest,
               laziness: float = 0.5, cursor: tuple[float, float] | None = None
               ) -> Pose:
        dt = max(0.0, min(0.1, dt))
        self.hit_wall = False

        # --- grabbed: spring towards the cursor -------------------------
        if self.mode is MotionMode.GRABBED:
            cx, cy = cursor if cursor is not None else (self.x, self.y)
            tx = cx + self._off_x
            ty = cy + self._off_y
            ax = (tx - self.x) * self.GRAB_K - self.vx * self.GRAB_C
            ay = (ty - self.y) * self.GRAB_K - self.vy * self.GRAB_C
            self.vx += ax * dt
            self.vy += ay * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            # a held pet dangles a little taller
            self._c += (-0.05 - self._c) * min(1.0, 10.0 * dt)

        else:
            # --- pre-hop crouch -> launch -------------------------------
            if (self.mode is MotionMode.BASE and self._crouch <= 0.0
                    and self.h <= 0.0):
                if req.hop:
                    self._crouch = 0.115
                    self._hop_h = req.hop_height or self.HOP_H
                elif req.small_hop:
                    self._crouch = 0.085
                    self._hop_h = req.hop_height or self.SMALL_HOP_H
            if self._crouch > 0.0:
                self._crouch -= dt
                if self._crouch <= 0.0:
                    self.vy = -math.sqrt(2.0 * self.GRAVITY * self._hop_h)
                    self.mode = MotionMode.AIR
                    self._c = -0.10

            # --- ballistic ----------------------------------------------
            if self.mode is MotionMode.AIR:
                self.vy += self.GRAVITY * dt
                self.x += self.vx * dt
                self.y += self.vy * dt
                self.vx *= max(0.0, 1.0 - 0.25 * dt)   # mild air drag
                # hold the launch stretch steady - a spring running in the
                # air reads as a nervous twitch, not a leap
                self._c += (-0.10 - self._c) * min(1.0, 12.0 * dt)
                if self.y >= self.floor_y:
                    impact_v = max(0.0, self.vy)
                    self.y = self.floor_y
                    self.vy = 0.0
                    self.mode = MotionMode.BASE
                    # deep, readable squash: small hops compress ~22%, a big
                    # drop flattens to ~36% (the exaggerated cartoon landing
                    # reads as "handfeel" at a glance)
                    self._c = min(0.72, 0.18 + impact_v / 1600.0)
                    self._cv = 0.0
                    self.impact = min(1.0, impact_v / 1400.0)

            # --- walking (grounded only) --------------------------------
            if self.mode is MotionMode.BASE and self._crouch <= 0.0:
                target = req.walk_dir * self._speed(laziness)
                accel = 3.4 if req.walk_dir else 5.0
                self.vx += (target - self.vx) * min(1.0, accel * dt)
                if req.walk_dir == 0 and abs(self.vx) < 1.5:
                    self.vx = 0.0
                self.x += self.vx * dt
                self.y = self.floor_y

        # --- walls ------------------------------------------------------
        if self.x <= self.left:
            self.x = self.left
            if self.vx < 0.0:
                self.vx = 0.0
                self.hit_wall = True
        elif self.x >= self.right:
            self.x = self.right
            if self.vx > 0.0:
                self.vx = 0.0
                self.hit_wall = True

        # --- squash-and-stretch spring (grounded; sub-stepped) ---------
        if self.mode is MotionMode.BASE:
            # slower and a touch less damped than a strict settle: two or
            # three visible bounces are what make the landing read as weight
            omega, zeta = 16.0, 0.23
            steps = max(1, int(math.ceil(omega * dt / 0.15)))
            hdt = dt / steps if steps else 0.0
            for _ in range(steps):
                a = -2.0 * zeta * omega * self._cv - omega * omega * self._c
                self._cv += a * hdt
                self._c += self._cv * hdt

        return Pose(
            x=self.x, y=self.y, floor_y=self.floor_y, h=self.h,
            sx=1.0 + 0.55 * self._c, sy=1.0 - 0.50 * self._c,
            impact=self.impact, mode=self.mode.value,
            on_ground=self.mode is MotionMode.BASE and self.h <= 0.0,
            held=self.mode is MotionMode.GRABBED,
            hit_wall=self.hit_wall,
        )

    def consume_impact(self) -> float:
        """Renderer asks for the landing event exactly once."""
        v = self.impact
        self.impact = 0.0
        return v
