"""Qt renderer: an always-on-top, click-through transparent pet window.

Loads petdex-format spritesheets (8xN grid, 192x208 cells) and plays the row
that matches the brain's current intent. The window walks left/right along
the bottom of the screen when the brain asks for it.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QAction, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .senses import Senses
from .sim import Simulation

# petdex canonical row order (v1 8x9; v2 8x11 shares the first 9 rows)
ROWS = [
    "idle", "running-right", "running-left", "waving", "jumping",
    "failed", "waiting", "running", "review",
]

ROW_FPS = {
    "idle": 6.0,
    "running-right": 10.0,
    "running-left": 10.0,
    "waving": 8.0,
    "jumping": 12.0,
    "failed": 5.0,
    "waiting": 6.0,
    "running": 10.0,
    "review": 5.0,
}

FRAMES_PER_ROW = 8
CELL_W, CELL_H = 192, 208


class SpriteSheet:
    def __init__(self, pet_dir: Path) -> None:
        meta_path = pet_dir / "pet.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        sheet_name = meta.get("spritesheetPath") or "spritesheet.webp"
        sheet_path = pet_dir / sheet_name
        if not sheet_path.exists():
            candidates = list(pet_dir.glob("*.webp")) + list(pet_dir.glob("*.png"))
            if not candidates:
                raise FileNotFoundError(f"no spritesheet in {pet_dir}")
            sheet_path = candidates[0]
        img = QImage(str(sheet_path))
        if img.isNull():
            raise RuntimeError(f"cannot load spritesheet: {sheet_path}")
        self.meta = meta
        self.image = img
        self.cell_w = img.width() // FRAMES_PER_ROW
        self.cell_h = img.height() // (img.height() // CELL_H if img.height() >= CELL_H else 9)
        # robust: derive rows from image height against 208px cells
        self.rows_count = max(1, img.height() // CELL_H)
        self.cell_h = img.height() // self.rows_count
        self.frames: dict[str, list[QPixmap]] = {}
        for r, name in enumerate(ROWS):
            if r >= self.rows_count:
                break
            frames = []
            for c in range(FRAMES_PER_ROW):
                pm = QPixmap.fromImage(
                    img.copy(c * self.cell_w, r * self.cell_h,
                             self.cell_w, self.cell_h))
                frames.append(pm)
            self.frames[name] = frames
        self.default_frames = self.frames.get("idle") or next(iter(self.frames.values()))

    def frame(self, row: str, index: int) -> QPixmap:
        frames = self.frames.get(row, self.default_frames)
        return frames[index % len(frames)]


class PetWindow(QWidget):
    def __init__(self, sim: Simulation, sprites: SpriteSheet, scale: float = 1.0):
        super().__init__()
        self.sim = sim
        self.sprites = sprites
        self.scale = scale
        self.w = int(self.sprites.cell_w * scale)
        self.h = int(self.sprites.cell_h * scale)

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

        # position: restore saved or start bottom-right
        screen = QApplication.primaryScreen().availableGeometry()
        import os as _os
        fx = _os.environ.get("REFLEXARC_FORCE_X")
        fy = _os.environ.get("REFLEXARC_FORCE_Y")
        if fx is not None and fy is not None:
            self.pet_x = float(fx)
            self.pet_y = float(fy)
        else:
            self.pet_x = float(self.sim.extra.get("x", screen.right() - self.w - 80))
            self.pet_y = float(screen.bottom() - self.h - 8)
        self._screen = screen
        self.move(int(self.pet_x), int(self.pet_y))

        self._row = "idle"
        self._frame_idx = 0.0
        self._last_t = time.time()
        self._senses_tick = 0
        self._paused = False
        self._mouse_was_down = False
        self._last_touch_ts = 0.0

        if not self.sim.stats.first_seen:
            self.sim.stats.first_seen = time.time()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        now = time.time()
        dt = max(0.0, min(0.5, now - self._last_t))
        self._last_t = now
        if self._paused:
            return

        # senses are relatively expensive: sample ~4x per second
        self._senses_tick += 1
        if self._senses_tick % 8 == 0 or self._senses_tick == 1:
            self._obs = self.sim.senses.sample()
        obs = getattr(self, "_obs", None)
        if obs is None:
            return

        self._check_touch(now)
        self.sim.step(obs, now)
        snap = self.sim.snapshot(now)
        target_row = snap.petdex_row

        # walking moves the window
        speed = 46.0 * self.scale
        if target_row == "running-left":
            self.pet_x -= speed * dt
        elif target_row == "running-right":
            self.pet_x += speed * dt
        left_edge = self._screen.left() + 4
        right_edge = self._screen.right() - self.w - 4
        hit_wall = False
        if self.pet_x <= left_edge:
            self.pet_x = left_edge
            hit_wall = True
        if self.pet_x >= right_edge:
            self.pet_x = right_edge
            hit_wall = True
        if hit_wall and target_row in ("running-left", "running-right"):
            self.sim.brain.time_left = 0.0  # decide again immediately
        self.move(int(self.pet_x), int(self.pet_y))

        # animation
        if target_row != self._row:
            self._row = target_row
            self._frame_idx = 0.0
        fps = ROW_FPS.get(self._row, 6.0)
        self._frame_idx += dt * fps
        self.update()

    def _check_touch(self, now: float) -> None:
        """The window is click-through so it never blocks the desktop, but we
        still read the global cursor: hovering over the sprite and clicking is
        a pet-pet."""
        try:
            user32 = ctypes.windll.user32
            pt = ctypes.wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(pt)):
                return
            gx, gy = pt.x, pt.y
            inside = (self.x() <= gx < self.x() + self.width()
                      and self.y() <= gy < self.y() + self.height())
            down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
            if inside and down and not self._mouse_was_down \
                    and (now - self._last_touch_ts) > 1.8:
                self._last_touch_ts = now
                self.sim.on_pet()
            self._mouse_was_down = down
        except (OSError, AttributeError):
            pass

    def paintEvent(self, event) -> None:  # noqa: N802
        pm = self.sprites.frame(self._row, int(self._frame_idx))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, self.w, self.h, pm)

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self.sim.extra["x"] = self.pet_x
        self.sim.save()
        super().closeEvent(event)


def find_pet_dir(name: str) -> Path:
    """Look for a pet in a few conventional places."""
    here = Path(__file__).resolve().parent.parent
    candidates = [
        here / "pets" / name,
        Path.home() / ".petdex" / "pets" / name,
        Path.home() / ".codex" / "pets" / name,
    ]
    for c in candidates:
        if (c / "pet.json").exists():
            return c
    # first pet with a spritesheet under pets/
    pets_root = here / "pets"
    if pets_root.exists():
        for d in sorted(pets_root.iterdir()):
            if d.is_dir() and (d / "pet.json").exists():
                return d
    raise FileNotFoundError(
        f"pet '{name}' not found; expected pets/{name}/pet.json"
    )


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
    return app.exec()
