"""Qt renderer: an always-on-top, click-through transparent pet window.

Orchestration only: senses -> simulation -> gaze -> animation row -> paint.
Sprite assets and their measured geometry live in ``sprites.py``; the
``SpriteSheet`` / ``ROWS`` / ``ROW_FPS`` / ``find_pet_dir`` names are
re-exported here so existing callers (tests/*) keep working.
"""
from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from . import desktop
from .effects import (Breath, EmoteDirector, EmotionBody, FidgetScheduler,
                      ShadowRenderer, StatusBubble)
from .gaze import ATLAS_STRIDE, STEPS, GazeController, GazeInputs
from .motion import MotionController, MotionRequest
from .senses import Senses
from .sim import Simulation
from .sprites import (  # noqa: F401  (re-exported for tests and callers)
    CELL_H, CELL_W, FRAMES_PER_ROW, ROWS, ROW_FPS, SpriteSheet, find_pet_dir,
)

# input FSM timings
ARM_DELAY = 0.18        # hover this long on the silhouette -> arm the grab
CLICK_MAX_T = 0.35      # shorter press without movement = a pet-pet
DOUBLE_CLICK_T = 0.55   # second click within this window = status bubble
DRAG_MIN_PX = 7.0       # movement that turns a press into a drag
HOLD_STROKE_T = 0.30    # pressed but still this long -> stroking
HOVER_PET_T = 1.1       # cursor resting on the pet -> a slow stroke
SOLID_WATCHDOG = 1.5    # solid but no button for this long -> force back

# rows whose animation the gaze replaces with a look-direction frame: the
# pet's body is stationary in these rows, so only the head can turn
GAZE_ROWS = {"idle", "waiting"}

# rows during which fidgets (glances, stretches...) make sense
FIDGET_ROWS = {"idle", "waiting", "review"}

# window padding around the sprite cell: head-room for emotes, floor-room
# for the shadow when the pet is airborne (the window follows the pet; the
# shadow slides down inside it to stay on the ground).  Sized once.
PAD_X, PAD_TOP, PAD_BOT = 16, 100, 110

BLINK_DURATION = 0.12
CROSSFADE_T = 0.11      # rows cross-fade instead of hard-cutting


class PetWindow(QWidget):
    def __init__(self, sim: Simulation, sprites: SpriteSheet, scale: float = 1.0):
        super().__init__()
        self.sim = sim
        self.sprites = sprites
        self.scale = scale
        self.sprite_w = int(round(self.sprites.cell_w * scale))
        self.sprite_h = int(round(self.sprites.cell_h * scale))
        self.w = self.sprite_w + 2 * PAD_X
        self.h = self.sprite_h + PAD_TOP + PAD_BOT

        self.setWindowTitle("ReflexArc")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(self.w, self.h)

        # foot anchor inside the window (source pixels -> window px)
        self._foot_local = (PAD_X + self.sprites.anchor_src_x * scale,
                            PAD_TOP + self.sprites.ground_y * scale)
        # head anchor (emote source) inside the window
        self._head_local = (PAD_X + self.sprites.eye_anchor[0] * scale,
                            PAD_TOP + self.sprites.eye_anchor[1] * scale)

        # position: restore saved or start bottom-right; the saved x was the
        # *sprite* corner in older versions, so shift it by the padding
        screen = QApplication.primaryScreen().availableGeometry()
        import os as _os
        fx = _os.environ.get("REFLEXARC_FORCE_X")
        fy = _os.environ.get("REFLEXARC_FORCE_Y")
        default_x = screen.right() - 80 - PAD_X - self.sprite_w
        default_y = screen.bottom() - 8 - PAD_TOP - self.sprite_h
        if fx is not None and fy is not None:
            self._pet_x = float(fx)
            self.pet_y = float(fy)
        elif "x" in self.sim.extra:
            self._pet_x = float(self.sim.extra["x"]) - PAD_X
            self.pet_y = default_y
        else:
            self._pet_x = float(default_x)
            self.pet_y = float(default_y)
        self._screen = screen
        self.move(int(self._pet_x), int(self.pet_y))

        self._row = "idle"
        self._frame_idx = 0.0
        self._t0 = time.time()
        self._last_t = time.time()
        self._senses_tick = 0
        self._paused = False
        self._last_touch_ts = 0.0
        self._last_cat = None

        # --- input / grab FSM ---
        self._clickthrough = desktop.ClickThrough(self)
        self._no_grab = bool(_os.environ.get("REFLEXARC_NO_GRAB"))
        self._no_breath = _os.environ.get("REFLEXARC_BREATH") == "0"
        self._no_emotes = _os.environ.get("REFLEXARC_EMOTES") == "0"
        self._grab_state = "idle"      # idle | armed | pressed | grabbed
        self._hover_since = 0.0
        self._press_t = 0.0
        self._press_pos = (0.0, 0.0)
        self._solid_since = 0.0
        self._hover_stroke_t = 0.0
        self._mouse_was_down = False
        self._last_click_ts = 0.0
        self._cursor = desktop.CursorState(0.0, 0.0, False)

        # --- sounds (short, soft, rate-limited; REFLEXARC_SOUND=0 silences) ---
        self._no_sound = _os.environ.get("REFLEXARC_SOUND") == "0"
        self._sound = None
        if not self._no_sound:
            try:
                from .sound import SoundBoard
                self._sound = SoundBoard()
            except Exception as exc:      # optional layer
                print(f"[reflexarc] sound disabled: {exc}", file=sys.stderr)

        # --- status bubble + body language (product layer) ---
        self._bubble = StatusBubble(scale)
        self._body = EmotionBody()
        self._em_sx = 1.0
        self._em_sy = 1.0
        self._em_y = 0.0
        self._panic_until = 0.0
        self._panic_next = 0.0
        self._panic_sign = 1

        # --- gaze state ---
        self._rng = random.Random()
        self.gaze = GazeController(seed=self._rng.randrange(1 << 30))
        self._gaze_active = False
        self._gaze_idx = 0
        self._switch_times: list[float] = []   # gaze step changes (debug HUD)
        self._blink_until = 0.0
        self._blink_next = time.time() + self._blink_gap()
        self._dpr = self._device_ratio()

        # row cross-fade: (pixmap, dx, dy) of the outgoing row, and how far
        # the fade has progressed (CROSSFADE_T = done)
        self._prev_draw: tuple | None = None
        self._cross_t = CROSSFADE_T

        # --- physics body (feet are the anchor; the window follows the feet) ---
        self.motion = MotionController(
            foot_x=self.pet_x + self._foot_local[0],
            floor_y=self.pet_y + self._foot_local[1],
            scale=scale, rng=random.Random(self._rng.randrange(1 << 30)))
        self._set_motion_bounds()
        self._pose = None
        self._was_cheering = False
        self._fidget_hop = False

        # --- life-sign layers ---
        self.breath = Breath()
        self.shadow = ShadowRenderer()
        self._emotes = EmoteDirector(scale=scale, rng=random.Random(self._rng.randrange(1 << 30)))
        self._fidget = FidgetScheduler(rng=random.Random(self._rng.randrange(1 << 30)))
        # transient pose offsets applied on top of the breathing scale
        self._extra_sx = 1.0
        self._extra_sy = 1.0
        self._shake = 0.0
        self._fid_handled = None
        self._debug = bool(_os.environ.get("REFLEXARC_DEBUG_HUD"))
        self._ms_next = 0.0

        if not self.sim.stats.first_seen:
            self.sim.stats.first_seen = time.time()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

        # warm the audio backend shortly after startup so the first real
        # sound does not block the interaction loop (see SoundBoard.warm)
        if self._sound is not None:
            QTimer.singleShot(900, self._sound.warm)

    # ------------------------------------------------------------------
    # window position: pet_x/pet_y are the window's top-left corner.  The
    # physics owns the body; assigning pet_x from outside (tests, debug)
    # teleports the whole pet there.
    # ------------------------------------------------------------------
    @property
    def pet_x(self) -> float:
        return self._pet_x

    @pet_x.setter
    def pet_x(self, value: float) -> None:
        self._pet_x = float(value)
        motion = getattr(self, "motion", None)
        if motion is not None:
            motion.teleport(foot_x=self._pet_x + self._foot_local[0])

    # ------------------------------------------------------------------
    # gaze helpers
    # ------------------------------------------------------------------
    def _device_ratio(self) -> float:
        try:
            return float(self.screen().devicePixelRatio()) or 1.0
        except Exception:
            return 1.0

    def _set_motion_bounds(self) -> None:
        """Keep the whole window (not just the feet) on screen."""
        left = self._screen.left() + 4 + self._foot_local[0]
        right = self._screen.right() - 4 - (self.w - self._foot_local[0])
        self.motion.set_bounds(left, right)

    def _eye_global(self) -> tuple[float, float]:
        """Eye anchor in global logical screen coordinates."""
        ex, ey = self.sprites.eye_anchor
        return (self.x() + ex * self.scale, self.y() + ey * self.scale)

    def _drowsiness(self, snap) -> float:
        d = snap.drives
        return max(0.0, min(1.0, (0.45 - d.energy) / 0.45 * 1.2))

    def _sleeping(self, snap) -> bool:
        from .brain import Intent
        return (self.sim.brain.current is Intent.REST
                and snap.drives.energy < 0.22)

    def _play(self, name: str, cooldown: float = 1.2) -> None:
        if self._sound is not None:
            self._sound.play(name, cooldown)

    def _current_need(self) -> str:
        """What does it want right now?  (double-click answers this)"""
        d = self.sim.drives
        p = self.sim.persona
        scores = {
            "want_pet": d.social_hunger * (0.55 + 0.9 * p.clinginess),
            "sleepy": max(0.0, 0.5 - d.energy) * 2.0,
            "bored": d.boredom * (0.5 + p.curiosity),
            "stress": d.stress * 1.5,
        }
        kind = max(scores, key=lambda k: scores[k])
        return kind if scores[kind] >= 0.30 else "happy"

    def _blink_gap(self) -> float:
        curiosity = getattr(self.sim.persona, "curiosity", 0.5)
        return self._rng.uniform(2.6, 5.4) * (1.15 - 0.5 * curiosity)

    def _over_body(self, gx: float, gy: float) -> bool:
        """Is a global-logical cursor position over the pet's silhouette?"""
        lx = (gx - self.x()) / self.scale
        ly = (gy - self.y()) / self.scale
        return self.sprites.hit_mask.contains(lx, ly)

    def _inside_window(self, gx: float, gy: float) -> bool:
        return (self.x() <= gx < self.x() + self.width()
                and self.y() <= gy < self.y() + self.height())

    # ------------------------------------------------------------------
    def _draw_hud(self, painter: QPainter, now: float) -> None:
        """Debug overlay: what the pet is doing and how often it changes.

        The useful number is gaze switches per second - a reviewer's
        tooling measured 5 scene changes per second in an earlier cut,
        which is what 'flickering' looks like as a metric.
        """
        painter.setPen(QColor(255, 90, 80, 235))
        font = QFont("Consolas", 8)
        painter.setFont(font)
        recent = sum(1 for t in self._switch_times if now - t < 10.0)
        pose = self._pose
        lines = [
            f"row {self._row}   gaze {self._gaze_idx}/{STEPS}",
            f"gaze switches: {recent}/10s  ({recent / 10.0:.1f}/s)",
            (f"mode {pose.mode}  h={pose.h:.0f}  sy={pose.sy:.2f}"
             if pose else ""),
        ]
        y = 14
        for s in lines:
            if s:
                painter.drawText(6, y, s)
            y += 12

    def _measure(self, t0: float, tag: str) -> None:
        """--debug HUD: rolling per-frame cost, printed every 2 s."""
        ms = (time.perf_counter() - t0) * 1000.0
        key = "_ms_" + tag
        ema = getattr(self, key, 0.0)
        setattr(self, key, ms if ema == 0.0 else 0.9 * ema + 0.1 * ms)
        now = time.time()
        if now >= self._ms_next:
            self._ms_next = now + 2.0
            recent = sum(1 for t in self._switch_times if now - t < 10.0)
            print(f"[reflexarc] tick {getattr(self, '_ms_tick', 0.0):.2f} ms  "
                  f"paint {getattr(self, '_ms_paint', 0.0):.2f} ms  "
                  f"gaze-switches {recent}/10s ({recent / 10.0:.1f}/s)",
                  file=sys.stderr, flush=True)

    def _tick(self) -> None:
        now = time.time()
        t0 = time.perf_counter() if self._debug else 0.0
        dt = max(0.0, min(0.5, now - self._last_t))
        self._last_t = now
        if self._paused:
            if self.motion.held:
                self.motion.release()
            if self._clickthrough.solid:
                self._end_grab()
            return

        # senses are relatively expensive: sample ~4x per second
        self._senses_tick += 1
        if self._senses_tick % 8 == 0 or self._senses_tick == 1:
            self._obs = self.sim.senses.sample()
        obs = getattr(self, "_obs", None)
        if obs is None:
            return

        self._input_fsm(now, dt)
        self.sim.step(obs, now)
        snap = self.sim.snapshot(now)
        row = snap.petdex_row
        held = self.motion.held

        # --- gaze: the eyes track the world while the body rows allow it ---
        self._gaze_active = False
        if self.sprites.has_look and row in GAZE_ROWS and not held:
            inp = GazeInputs(
                cursor=(self._cursor.x, self._cursor.y),
                cursor_fresh=obs.idle_seconds < 3.0,
                # lock on only after the cursor settles; a moving cursor
                # would mean re-drawing the head every step (the flicker a
                # scene-change count flagged: 5 jumps per second)
                cursor_settled=0.35 <= obs.idle_seconds < 4.0,
                fg_rect=self._logical_rect(obs.fg_rect),
                held=held,
                drowsy=self._drowsiness(snap),
                sleepy=self._sleeping(snap),
                cursor_radius=520.0 * self.scale,
            )
            prev_idx = self._gaze_idx
            self._gaze_idx = self.gaze.update(dt, self._eye_global(), inp)
            self._gaze_active = True
            if self._gaze_idx != prev_idx:
                self._switch_times.append(now)
                if len(self._switch_times) > 200:
                    del self._switch_times[:100]
            if now >= self._blink_next:
                self._blink_until = now + BLINK_DURATION
                self._blink_next = now + self._blink_gap()
        else:
            self._blink_next = max(self._blink_next, now + 0.8)

        self._update_life(dt, obs, snap)

        # --- physics: brain intent -> body (the body never talks back) ---
        cheering = snap.intent == "cheer"
        hop_edge = cheering and not self._was_cheering
        self._was_cheering = cheering
        walk_dir = 0
        if row == "running-left":
            walk_dir = -1
        elif row == "running-right":
            walk_dir = 1
        req = MotionRequest(walk_dir=walk_dir, hop=hop_edge,
                            small_hop=self._fidget_hop)
        self._fidget_hop = False
        pose = self.motion.update(dt, req, laziness=self.sim.persona.laziness,
                                 cursor=(self._cursor.x, self._cursor.y))
        self._pose = pose
        imp = self.motion.consume_impact()
        if imp > 0.12:
            self._emotes.notify_landed(imp)
        if imp >= 0.55:
            # a hard fall: dizzy stars orbiting the head, body curls up
            self._emotes.emotes.spawn(
                "stars", self._head_local[0],
                self._head_local[1] - 34 * self.scale)
            self._body.play("sad", 2.2)
            self._play("sad", 2.0)
        elif imp >= 0.25:
            self._play("land", 1.0)
        if imp >= 0.25:
            self.sim.on_land(imp)
        if pose.hit_wall and row in ("running-left", "running-right"):
            self.sim.brain.time_left = 0.0  # decide again immediately

        # --- final row: the body overrides the brain while airborne/held ---
        final_row = row
        if pose.held or pose.mode == "air":
            final_row = "jumping"       # legs out: a leaping, dangling pose
            self._gaze_active = False
        if final_row != self._row:
            # capture the outgoing picture so the two rows can cross-fade
            self._prev_draw = self._current_sprite(now)
            self._cross_t = 0.0
            self._row = final_row
            self._frame_idx = 0.0
        elif self._cross_t < CROSSFADE_T:
            self._cross_t = min(CROSSFADE_T, self._cross_t + dt)
            if self._cross_t >= CROSSFADE_T:
                self._prev_draw = None
        fps = ROW_FPS.get(self._row, 6.0)
        self._frame_idx += dt * fps

        # the window follows the pet (feet at a fixed spot inside it); the
        # shadow slides down inside the window to stay on the ground line
        self._pet_x = pose.x - self._foot_local[0]
        self.pet_y = pose.y - self._foot_local[1]
        self.move(int(self._pet_x), int(self.pet_y))
        self.update()
        if self._debug:
            if self.motion.held or self._grab_state in ("armed", "pressed"):
                if now - getattr(self, "_held_log_t", 0.0) > 0.4:
                    self._held_log_t = now
                    print(f"[reflexarc] {self._grab_state} "
                          f"cur=({self._cursor.x:.0f},{self._cursor.y:.0f}) "
                          f"feet=({self.motion.x:.0f},{self.motion.y:.0f}) "
                          f"win=({self.pet_x:.0f},{self.pet_y:.0f}) "
                          f"mode={self.motion.mode.value}", file=sys.stderr, flush=True)
            self._measure(t0, "tick")

    # ------------------------------------------------------------------
    def _update_life(self, dt: float, obs, snap) -> None:
        """Breathing, fidgets, emotes - the layers that make it feel alive."""
        d = snap.drives
        p = self.sim.persona

        # a window switch is worth a "?"
        cat = obs.window_category
        if self._last_cat is not None and cat != self._last_cat and obs.activity > 0.2:
            self._emotes.notify_curious()
        self._last_cat = cat

        # micro-actions during long idles, personality-scaled
        fid = self._fidget.update(dt, active=self._row in FIDGET_ROWS,
                                  curiosity=p.curiosity, laziness=p.laziness)
        self._extra_sx = 1.0
        self._extra_sy = 1.0
        if fid is not None:
            k = min(1.0, fid.t / fid.dur)
            fresh = fid is not self._fid_handled
            if fid.kind == "glance" and fresh:
                self.gaze.nudge(int(fid.value), ttl=max(0.25, fid.dur))
            elif fid.kind == "breath":
                self.breath.boost = 1.8
            elif fid.kind == "stretch":
                s = math.sin(math.pi * k)
                self._extra_sx = 1.0 + 0.045 * s
                self._extra_sy = 1.0 - 0.060 * s
            elif fid.kind == "hop" and fresh:
                self._fidget_hop = True     # the body hops next physics step
        self._fid_handled = fid
        if fid is None or fid.kind != "breath":
            self.breath.boost = 1.0

        sleeping = self._sleeping(snap)
        if not self._no_breath:
            self.breath.update(dt, d.energy, sleeping, p.laziness, d.stress)

        # a stressed pet vibrates a little
        if not sleeping and (d.stress > 0.70 or obs.cpu > 0.80):
            self._shake = 1.3 * self.scale
        else:
            self._shake = 0.0

        if not self._no_emotes:
            self._emotes.update(
                dt, energy=d.energy, mood=d.mood, stress=d.stress, cpu=obs.cpu,
                sleeping=sleeping, head=self._head_local, foot=self._foot_local)

        # startled little glances right after being picked up - slow enough
        # to read as worry, not as a twitch
        now = time.time()
        if now < self._panic_until:
            if now >= self._panic_next:
                self._panic_next = now + 0.55
                self._panic_sign = -self._panic_sign
                self.gaze.nudge(2 * self._panic_sign, ttl=0.7)

        # body-language layer: the emotion shows in the pose itself
        self._em_sx, self._em_sy, self._em_y = self._body.update(dt)
        if (self._body.kind is None and not sleeping
                and d.boredom > 0.68 and self._rng.random() < 0.004):
            self._body.play("bored", 3.5)

        # status bubble expiry
        self._bubble.update(now)

    def _logical_rect(self, rect):
        """Physical-pixel rect (senses) -> Qt logical coordinates."""
        if rect is None:
            return None
        d = self._device_ratio()
        return (rect[0] / d, rect[1] / d, rect[2] / d, rect[3] / d)

    # ------------------------------------------------------------------
    def _input_fsm(self, now: float, dt: float) -> None:
        """One state machine for hovering, petting and dragging.

        The window stays click-through except while a grab is *armed*: the
        cursor must rest on the silhouette for ARM_DELAY before we start
        taking clicks, so ordinary desktop work is never blocked.  A press
        that does not move is a pet-pet; a press that moves picks the pet up.
        Safety nets: any state can end via _end_grab, a watchdog forces
        click-through back when the button has been up too long, and
        REFLEXARC_NO_GRAB disables grabbing entirely.
        """
        cur = desktop.cursor()
        self._cursor = cur
        body_over = self._over_body(cur.x, cur.y)
        inside = self._inside_window(cur.x, cur.y)
        over = body_over
        gap_click = now - self._last_click_ts
        # just after a click the pet may have hopped out from under the
        # cursor as its reaction to that click: keep accepting the whole
        # window for a moment so a double-click still lands
        if not over and gap_click < DOUBLE_CLICK_T:
            over = inside
        if self._debug:
            sig = (body_over, inside, over, self._grab_state, cur.left_down)
            if sig != getattr(self, "_ov_sig", None):
                self._ov_sig = sig
                print(f"[reflexarc] ov t={now - self._t0:6.2f} body={body_over} "
                      f"inside={inside} over={over} gap={gap_click:5.2f} "
                      f"winy={self.y():.0f} cury={cur.y:.0f}",
                      file=sys.stderr, flush=True)

        # hovering (with or without grab arming) is a slow stroke
        if over and not cur.left_down:
            if self._hover_stroke_t == 0.0:
                self._hover_stroke_t = now
            elif (now - self._hover_stroke_t >= HOVER_PET_T
                  and now - self._last_touch_ts > 2.5):
                self._last_touch_ts = now
                self._hover_stroke_t = now
                self.sim.on_hover_tick()
                self._emotes.notify_petted()
                self._play("happy", 2.4)
        else:
            self._hover_stroke_t = 0.0

        if self._no_grab:
            if (over and cur.left_down and not self._mouse_was_down
                    and now - self._last_touch_ts > 1.8):
                self._last_touch_ts = now
                self.sim.on_pet()
                self._emotes.notify_petted()
            self._mouse_was_down = cur.left_down
            return

        st = self._grab_state
        if st == "idle":
            if over and not cur.left_down:
                if self._hover_since == 0.0:
                    self._hover_since = now
                elif now - self._hover_since >= ARM_DELAY:
                    self._clickthrough.set_solid(True)
                    self._solid_since = now
                    self._set_grab_state("armed")
            else:
                self._hover_since = 0.0

        elif st == "armed":
            if not over and not cur.left_down:
                self._end_grab()
            elif cur.left_down:
                self._press_t = now
                self._press_pos = (cur.x, cur.y)
                self._set_grab_state("pressed")

        elif st == "pressed":
            moved = math.hypot(cur.x - self._press_pos[0],
                               cur.y - self._press_pos[1])
            if not cur.left_down:
                if self._debug:
                    print(f"[reflexarc] click: held={now - self._press_t:.2f}s "
                          f"gap={now - self._last_click_ts:.2f}s "
                          f"bubble={self._bubble.kind}",
                          file=sys.stderr, flush=True)
                if now - self._press_t < CLICK_MAX_T:
                    if now - self._last_click_ts < DOUBLE_CLICK_T:
                        # double-click: answer "what do you want right now?"
                        self._bubble.show(self._current_need(), now)
                    else:
                        self.sim.on_pet()
                        self._emotes.notify_petted()
                        self._body.play("joy", 1.6)
                        self._play("happy")
                    self._last_click_ts = now
                self._end_grab()
            elif moved > DRAG_MIN_PX:
                self.motion.grab(cur.x, cur.y)
                self.sim.on_pick_up()
                self._emotes.notify_petted()
                self._play("surprise")
                self._panic_until = now + 0.9      # startled: quick glances
                self._panic_next = 0.0
                self._set_grab_state("grabbed")
            elif now - self._press_t > HOLD_STROKE_T:
                self.sim.on_hold(dt)     # pressed but still = stroking

        elif st == "grabbed":
            if not cur.left_down:
                self.motion.release()
                self.sim.on_drop()
                self._end_grab()
            else:
                self.sim.on_hold(dt)

        # safety net: "solid" is only legal while the interaction state says
        # so (armed = cursor resting on the pet, pressed, grabbed).  Reaching
        # idle while still solid means a lost transition - force it back.
        if self._clickthrough.solid and self._grab_state == "idle":
            self._end_grab()

        if self._debug:
            sig = (self._grab_state, over, cur.left_down)
            if sig != getattr(self, "_fsm_sig", None):
                self._fsm_sig = sig
                print(f"[reflexarc] fsm: state={self._grab_state} "
                      f"over={over} down={cur.left_down} "
                      f"solid={self._clickthrough.solid}",
                      file=sys.stderr, flush=True)

    def _set_grab_state(self, st: str) -> None:
        if self._debug and st != self._grab_state:
            print(f"[reflexarc] grab: {self._grab_state} -> {st}",
                  file=sys.stderr, flush=True)
        self._grab_state = st

    def _end_grab(self) -> None:
        self._clickthrough.set_solid(False)
        self._set_grab_state("idle")
        # deliberately keep _hover_since: if the cursor is still on the pet
        # the window stays pre-armed, so the second click of a double-click
        # lands immediately instead of being swallowed by a fresh 0.18s wait

    def _current_sprite(self, now: float | None = None):
        """(pixmap, source dx, dy) for whatever should be on screen now."""
        now = time.time() if now is None else now
        if self._gaze_active and self.sprites.blink_frames and now < self._blink_until:
            idx = self.sprites.blink_frames[0]
            pm = self.sprites.frame("idle", idx)
            dx, dy = self.sprites.draw_offset("idle", idx)
            bx, by = self.sprites.blink_align
            return pm, dx + bx, dy + by
        if self._gaze_active:
            atlas_idx = self._gaze_idx * ATLAS_STRIDE
            pm = self.sprites.look(atlas_idx)
            dx, dy = self.sprites.draw_offset("look", atlas_idx)
            return pm, dx, dy
        idx = int(self._frame_idx)
        pm = self.sprites.frame(self._row, idx)
        dx, dy = self.sprites.draw_offset(self._row, idx)
        return pm, dx, dy

    def paintEvent(self, event) -> None:  # noqa: N802
        now = time.time()
        t0 = time.perf_counter() if self._debug else 0.0
        pm, dx, dy = self._current_sprite(now)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        pose = self._pose
        h_above = pose.h if pose else 0.0
        pose_sx = pose.sx if pose else 1.0
        pose_sy = pose.sy if pose else 1.0

        # ground shadow - the window follows the pet, so the shadow slides
        # *down* inside it to stay on the floor while the pet is airborne
        self.shadow.draw(painter, self._foot_local[0],
                         self._foot_local[1] + h_above,
                         self.sprites.body_w * self.scale * 0.62, h_above,
                         self.scale)

        # breathing / squash: scale about the feet so they never slide
        fx, fy = self._foot_local
        if self._shake:
            painter.translate(self._shake * math.sin(now * 47.0), 0.0)
        painter.translate(fx, fy)
        painter.scale(self.breath.sx * self._extra_sx * pose_sx * self._em_sx,
                      self.breath.sy * self._extra_sy * pose_sy * self._em_sy)
        painter.translate(-fx, -fy)
        # cross-fade from the outgoing row: a hard cut between animations
        # reads as a flicker, a short blend reads as the pet *changing pose*
        if self._prev_draw is not None and self._cross_t < CROSSFADE_T:
            k = max(0.0, min(1.0, self._cross_t / CROSSFADE_T))
            ppm, pdx, pdy = self._prev_draw
            painter.setOpacity(1.0 - k)
            painter.drawPixmap(int(PAD_X + pdx * self.scale),
                               int(PAD_TOP + pdy * self.scale + self._em_y),
                               self.sprite_w, self.sprite_h, ppm)
            painter.setOpacity(k)
        painter.drawPixmap(int(PAD_X + dx * self.scale),
                           int(PAD_TOP + dy * self.scale + self._em_y),
                           self.sprite_w, self.sprite_h, pm)
        painter.setOpacity(1.0)

        # glyphs live in window coordinates, above everything
        painter.resetTransform()
        self._emotes.emotes.draw(painter)
        if self._bubble.active:
            self._bubble.draw(painter, now, self._head_local[0],
                              self._head_local[1] - 92 * self.scale)
        if self._debug:
            self._draw_hud(painter, now)
            self._measure(t0, "paint")

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self.sim.extra["x"] = self.pet_x
        self.sim.save()
        super().closeEvent(event)


def main(args) -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    try:
        pet_dir = find_pet_dir(args.name.lower())
    except FileNotFoundError:
        try:
            from .fetch import fetch_pet
            root = Path(__file__).resolve().parent.parent / "pets"
            pet_dir = fetch_pet(getattr(args, "pet_slug", "boba"), root)
        except Exception as exc:
            print(f"pet not found and fetch failed: {exc}", file=sys.stderr)
            return 3

    sprites = SpriteSheet(pet_dir)

    intuition = None
    if not getattr(args, "no_laya", False):
        try:
            from .intuition import create_intuition
            intuition = create_intuition()
        except Exception as exc:  # optional layer
            print(f"[reflexarc] intuition layer disabled: {exc}", file=sys.stderr)

    sim = Simulation(seed=args.seed, intuition=intuition,
                     fresh=args.fresh, pet_name=sprites.meta.get("displayName", args.name))

    win = PetWindow(sim, sprites, scale=getattr(args, "scale", 1.0))

    tray = QSystemTrayIcon()
    icon_pm = sprites.frame("idle", 0).scaled(64, 64, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation)
    tray.setIcon(QIcon(icon_pm))
    tray.setToolTip("ReflexArc")
    menu = QMenu()
    act_pause = QAction("Pause / resume")
    act_pause.triggered.connect(lambda: setattr(win, "_paused", not win._paused))
    act_quit = QAction("Quit")
    act_quit.triggered.connect(app.quit)
    menu.addAction(act_pause)
    menu.addSeparator()
    menu.addAction(act_quit)
    tray.setContextMenu(menu)
    tray.show()

    win.show()

    if win._debug:
        # sanity: a solid layered window should still ignore transparent
        # pixels; probe a point in the window's padding that must be
        # see-through and check the click reaches what is underneath
        ok = win._clickthrough.hit_tests_per_pixel((win.x() + 4, win.y() + 4))
        print(f"[reflexarc] per-pixel hit test: "
              f"{'OK' if ok else 'NOT available (transparent area swallows clicks)'}",
              file=sys.stderr, flush=True)

    return app.exec()
