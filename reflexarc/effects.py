"""Living-layer drawing: breathing, ground shadow, emote glyphs, fidgets.

QtGui only - no widgets, no windows.  Everything expensive (gradients,
glyph outlines, the heart path, dust rings) is baked into pixmaps once at
construction; the per-frame path does nothing but blits and transforms, so
this stays cheap at 30 fps.

The pet's "life signs" are split into four small systems:

* ``Breath``          - a vertical scale pulse anchored at the feet
* ``ShadowRenderer``  - a pre-baked radial blob, scaled/dimmed by height
* ``EmoteSystem``     - floating glyphs (zzz, hearts, sweat, !, ?, dust)
* ``EmoteDirector``   - decides *when* emotions become visible (reads the
  drives/snapshot; never touches the brain)
* ``FidgetScheduler`` - occasional micro-actions during long idles
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient, QTransform)


# --------------------------------------------------------------------------
class Breath:
    """Vertical scale pulse anchored at the feet: chest rises, feet stay."""

    def __init__(self) -> None:
        self._phase = 0.0
        self.sx = 1.0
        self.sy = 1.0
        self.boost = 1.0          # set by the deep-breath fidget / stress

    def update(self, dt: float, energy: float, sleeping: bool,
               laziness: float = 0.5, stress: float = 0.0) -> None:
        f = 0.16 + 0.24 * energy
        f *= (1.15 - 0.30 * laziness)
        amp = 0.006 + 0.011 * energy
        if sleeping:
            f = 0.12
            amp *= 1.9
        elif stress > 0.5:
            f *= 1.6              # hot and tense: faster, shallower breathing
            amp *= 0.8
        amp *= self.boost
        self._phase = (self._phase + dt * f) % 1.0
        s = math.sin(2.0 * math.pi * self._phase)
        self.sy = 1.0 + amp * s
        self.sx = 1.0 - 0.32 * amp * s   # weak volume conservation


# --------------------------------------------------------------------------
class ShadowRenderer:
    """A soft elliptical shadow, baked once, drawn as a scaled blit."""

    def __init__(self) -> None:
        self._pm = self._bake(256, 96)

    @staticmethod
    def _bake(w: int, h: int) -> QPixmap:
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        grad = QRadialGradient(w / 2.0, h / 2.0, w / 2.0)
        grad.setColorAt(0.0, QColor(0, 0, 0, 150))
        grad.setColorAt(0.55, QColor(0, 0, 0, 70))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        t = QTransform()
        t.translate(w / 2.0, h / 2.0)
        t.scale(1.0, h / float(w))          # squash the circle into an ellipse
        t.translate(-w / 2.0, -h / 2.0)
        p.setTransform(t)
        p.drawEllipse(QRectF(0, 0, w, w))
        p.end()
        return pm

    def draw(self, painter: QPainter, cx: float, ground_y: float,
             width: float, height_above: float, scale: float = 1.0) -> None:
        h_norm = max(0.0, min(1.0, height_above / (220.0 * scale)))
        w = width * (1.0 - 0.34 * h_norm)
        h = w * 0.30
        alpha = 0.85 * (1.0 - 0.72 * h_norm) + 0.08
        painter.setOpacity(max(0.0, min(1.0, alpha)))
        painter.drawPixmap(QRectF(cx - w / 2.0, ground_y - h / 2.0, w, h),
                           self._pm, QRectF(0, 0, self._pm.width(), self._pm.height()))
        painter.setOpacity(1.0)


# --------------------------------------------------------------------------
@dataclass
class Emote:
    kind: str
    x: float
    y: float
    t: float = 0.0
    dur: float = 1.6
    size: float = 1.0


class EmoteSystem:
    """Floating emotion glyphs.  One baked pixmap per kind; per-frame work is
    a handful of drawPixmap calls with transforms."""

    def __init__(self, scale: float = 1.0) -> None:
        self.scale = scale
        s = max(0.7, min(2.2, scale))
        self._heart = self._bake_heart(26.0 * s)
        # glyphs are hand-drawn paths, not font text: Qt offscreen mode has no
        # font database at all, and hand-drawn strokes match the pixel style
        self._zzz = self._bake_z(22.0 * s, QColor(150, 175, 235))
        self._bang = self._bake_bang(26.0 * s, QColor(235, 80, 70))
        self._question = self._bake_question(24.0 * s, QColor(125, 170, 235))
        self._drop = self._bake_drop(13.0 * s)
        self._ring = self._bake_ring(48.0 * s, max(3.0, 5.0 * s))
        self.items: list[Emote] = []

    # ---- baking ----------------------------------------------------------
    @staticmethod
    def _stroke_pm(w: float, h: float, color: QColor, width: float,
                   draw) -> QPixmap:
        pm = QPixmap(max(2, int(round(w))), max(2, int(round(h))))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(color, max(2.0, width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        draw(p, pm.width(), pm.height())
        p.end()
        return pm

    @classmethod
    def _bake_z(cls, s: float, color: QColor) -> QPixmap:
        def draw(p: QPainter, w: int, h: int) -> None:
            path = QPainterPath()
            path.moveTo(w * 0.16, h * 0.24)
            path.lineTo(w * 0.84, h * 0.24)
            path.lineTo(w * 0.16, h * 0.76)
            path.lineTo(w * 0.84, h * 0.76)
            p.drawPath(path)
        return cls._stroke_pm(s, s, color, s * 0.17, draw)

    @classmethod
    def _bake_bang(cls, s: float, color: QColor) -> QPixmap:
        def draw(p: QPainter, w: int, h: int) -> None:
            p.drawLine(QPointF(w / 2, h * 0.10), QPointF(w / 2, h * 0.58))
            p.setBrush(color)
            p.drawEllipse(QPointF(w / 2, h * 0.85), w * 0.13, w * 0.13)
        return cls._stroke_pm(s * 0.5 + 6, s * 1.25, color, s * 0.18, draw)

    @classmethod
    def _bake_question(cls, s: float, color: QColor) -> QPixmap:
        def draw(p: QPainter, w: int, h: int) -> None:
            path = QPainterPath()
            path.moveTo(w * 0.20, h * 0.30)
            path.cubicTo(w * 0.20, h * 0.04, w * 0.80, h * 0.04,
                         w * 0.80, h * 0.30)
            path.cubicTo(w * 0.80, h * 0.52, w * 0.50, h * 0.50,
                         w * 0.50, h * 0.70)
            p.drawPath(path)
            p.setBrush(color)
            p.drawEllipse(QPointF(w * 0.50, h * 0.88), w * 0.10, w * 0.10)
        return cls._stroke_pm(s, s, color, s * 0.15, draw)

    @staticmethod
    def _bake_heart(s: float) -> QPixmap:
        pm = QPixmap(int(s * 1.4), int(s * 1.3))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        x0, y0 = s * 0.7, s * 0.2
        k = s
        path.moveTo(x0, y0 + 0.72 * k)
        path.cubicTo(x0 - 0.68 * k, y0 + 0.32 * k,
                     x0 - 0.44 * k, y0 - 0.14 * k,
                     x0, y0 + 0.14 * k)
        path.cubicTo(x0 + 0.44 * k, y0 - 0.14 * k,
                     x0 + 0.68 * k, y0 + 0.32 * k,
                     x0, y0 + 0.72 * k)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(235, 90, 120))
        p.drawPath(path)
        p.end()
        return pm

    @staticmethod
    def _bake_drop(s: float) -> QPixmap:
        pm = QPixmap(int(s * 1.2), int(s * 1.6))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        cx, cy, r = s * 0.6, s * 0.95, s * 0.55
        path.moveTo(cx, s * 0.05)
        path.cubicTo(cx + r * 1.1, cy - r * 0.25, cx + r, cy + r,
                     cx, cy + r)
        path.cubicTo(cx - r, cy + r, cx - r * 1.1, cy - r * 0.25,
                     cx, s * 0.05)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(120, 180, 230, 220))
        p.drawPath(path)
        p.end()
        return pm

    @staticmethod
    def _bake_ring(size: float, thickness: float) -> QPixmap:
        pm = QPixmap(int(size), int(size))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(200, 190, 175, 190), thickness)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        inset = thickness / 2.0 + 1.0
        p.drawEllipse(QRectF(inset, inset, size - inset * 2, size - inset * 2))
        p.end()
        return pm

    # ---- runtime ---------------------------------------------------------
    def spawn(self, kind: str, x: float, y: float, size: float = 1.0,
              dur: float | None = None) -> None:
        if kind == "puff":
            for i in range(5):
                a = i * (2.0 * math.pi / 5.0) + 0.4
                self.items.append(Emote(
                    "puff", x + math.cos(a) * 14.0, y + math.sin(a) * 5.0,
                    dur=dur or self.rng(0.28, 0.42)))
            return
        d = dur if dur is not None else {
            "heart": 1.5, "zzz": 2.4, "sweat": 1.1,
            "bang": 0.9, "question": 1.8,
        }.get(kind, 1.5)
        self.items.append(Emote(kind, x, y, dur=d, size=size))

    @staticmethod
    def rng(lo: float, hi: float) -> float:
        return random.uniform(lo, hi)

    def update(self, dt: float) -> None:
        if not self.items:
            return
        alive = []
        for e in self.items:
            e.t += dt
            if e.t < e.dur:
                alive.append(e)
        self.items = alive

    def draw(self, painter: QPainter) -> None:
        for e in self.items:
            k = min(1.0, e.t / e.dur)
            if e.kind == "heart":
                x = e.x + 7.0 * math.sin(e.t * 4.5)
                y = e.y - 34.0 * k * self.scale
                a = 1.0 if k < 0.6 else max(0.0, 1.0 - (k - 0.6) / 0.4)
                sc = (1.15 - 0.15 * min(1.0, k * 4.0)) * e.size
                self._blit(painter, self._heart, x, y, a, sc)
            elif e.kind == "zzz":
                x = e.x + 16.0 * k * self.scale
                y = e.y - 30.0 * k * self.scale
                a = 1.0 if k < 0.55 else max(0.0, 1.0 - (k - 0.55) / 0.45)
                sc = (0.7 + 0.5 * k) * e.size
                self._blit(painter, self._zzz, x, y, a * 0.95, sc)
            elif e.kind == "sweat":
                dip = math.sin(min(1.0, k * 1.6) * math.pi) * 9.0 * self.scale
                a = 1.0 if k < 0.5 else max(0.0, 1.0 - (k - 0.5) / 0.5)
                self._blit(painter, self._drop, e.x, e.y + dip, a, e.size)
            elif e.kind == "bang":
                sc = (1.35 - 0.35 * min(1.0, k * 5.0)) * e.size
                a = 1.0 if k < 0.65 else max(0.0, 1.0 - (k - 0.65) / 0.35)
                wob = 2.0 * math.sin(e.t * 22.0) * (1.0 - k)
                self._blit(painter, self._bang, e.x + wob, e.y, a, sc)
            elif e.kind == "question":
                y = e.y - 22.0 * k * self.scale
                a = math.sin(min(1.0, k * 1.3) * math.pi)
                self._blit(painter, self._question, e.x, y, a, e.size)
            elif e.kind == "puff":
                sc = (0.25 + 1.1 * k) * e.size
                a = max(0.0, 1.0 - k) * 0.9
                self._blit(painter, self._ring, e.x, e.y, a, sc)

    @staticmethod
    def _blit(painter: QPainter, pm: QPixmap, x: float, y: float,
              alpha: float, scale: float) -> None:
        if alpha <= 0.01:
            return
        painter.setOpacity(alpha)
        w = pm.width() * scale
        h = pm.height() * scale
        painter.drawPixmap(QRectF(x - w / 2.0, y - h / 2.0, w, h), pm,
                           QRectF(0, 0, pm.width(), pm.height()))
        painter.setOpacity(1.0)


# --------------------------------------------------------------------------
class EmoteDirector:
    """Decides when emotions become visible.  Reads drives/snapshot values
    and event notifications from the renderer; never touches the brain."""

    def __init__(self, scale: float = 1.0, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.emotes = EmoteSystem(scale)
        self._t_sleep = 1.5
        self._t_sweat = 2.0
        self._t_bang = 0.0
        self._petted_queue = 0
        self._landed_queue = 0.0
        self._curious_queue = 0

    # event hooks (called by the renderer)
    def notify_petted(self) -> None:
        self._petted_queue = min(3, self._petted_queue + 1)

    def notify_landed(self, impact: float) -> None:
        self._landed_queue = max(self._landed_queue, impact)

    def notify_curious(self) -> None:
        self._curious_queue = min(2, self._curious_queue + 1)

    # ------------------------------------------------------------------
    def update(self, dt: float, *, energy: float, mood: float, stress: float,
               cpu: float, sleeping: bool, head: tuple[float, float],
               foot: tuple[float, float]) -> None:
        hx, hy = head
        sc = self.emotes.scale
        self.emotes.update(dt)

        # hearts: being petted or held - float up from above the head
        if self._petted_queue > 0:
            for _ in range(2 + min(2, self._petted_queue - 1)):
                self.emotes.spawn("heart",
                                  hx + self.rng.uniform(-20, 30) * sc,
                                  hy - (82 + self.rng.uniform(0, 22)) * sc,
                                  size=self.rng.uniform(0.7, 1.05))
            self._petted_queue = 0

        # dust: landing
        if self._landed_queue > 0.0:
            imp = self._landed_queue
            self._landed_queue = 0.0
            self.emotes.spawn("puff", foot[0], foot[1] - 4.0,
                              size=0.7 + 0.6 * imp)

        # question marks: something changed in the world
        while self._curious_queue > 0:
            self._curious_queue -= 1
            self.emotes.spawn("question", hx + 30 * sc, hy - 62 * sc)

        # zzz while sleepy - a ladder drifting up from the head
        if sleeping or energy < 0.22:
            self._t_sleep -= dt
            if self._t_sleep <= 0.0:
                self._t_sleep = self.rng.uniform(1.8, 2.6)
                self.emotes.spawn("zzz", hx + 24 * sc, hy - 66 * sc)
        else:
            self._t_sleep = max(self._t_sleep, 1.2)

        # sweat / stress chain: sweat first, then also a bang
        hot = stress > 0.42 or cpu > 0.62
        very_hot = stress > 0.70 or cpu > 0.80
        if hot and not sleeping:
            self._t_sweat -= dt
            if self._t_sweat <= 0.0:
                self._t_sweat = self.rng.uniform(1.2, 2.2) if very_hot \
                    else self.rng.uniform(3.0, 6.0)
                self.emotes.spawn("sweat", hx + 20 * sc, hy - 26 * sc)
            if very_hot:
                self._t_bang -= dt
                if self._t_bang <= 0.0:
                    self._t_bang = self.rng.uniform(1.0, 1.6)
                    self.emotes.spawn("bang", hx - 40 * sc, hy - 78 * sc)
        else:
            self._t_sweat = max(self._t_sweat, 1.0)
            self._t_bang = max(self._t_bang, 0.8)


# --------------------------------------------------------------------------
@dataclass
class Fidget:
    kind: str                  # glance | breath | stretch | hop
    value: float = 0.0
    t: float = 0.0
    dur: float = 0.5


class FidgetScheduler:
    """Occasional micro-actions during long idles, personality-scaled:
    curiosity makes them more frequent, laziness makes them rarer."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self._timer = self._gap(0.5, 0.5)
        self.current: Fidget | None = None

    def _gap(self, curiosity: float, laziness: float) -> float:
        base = self.rng.uniform(4.0, 14.0)
        base *= (1.35 - 0.60 * curiosity) * (0.80 + 0.70 * laziness)
        return max(2.5, base)

    def update(self, dt: float, active: bool, curiosity: float = 0.5,
               laziness: float = 0.5) -> Fidget | None:
        if self.current is not None:
            self.current.t += dt
            if self.current.t >= self.current.dur:
                self.current = None
            else:
                return self.current

        if not active:
            self._timer = self._gap(curiosity, laziness)
            return None

        self._timer -= dt
        if self._timer > 0.0:
            return None
        self._timer = self._gap(curiosity, laziness)
        r = self.rng.random()
        if r < 0.55:
            f = Fidget("glance", float(self.rng.choice([-4, -3, 3, 4])), dur=0.7)
        elif r < 0.75:
            f = Fidget("breath", dur=3.0)
        elif r < 0.92:
            f = Fidget("stretch", dur=0.42)
        else:
            f = Fidget("hop", dur=0.5)
        self.current = f
        return f
