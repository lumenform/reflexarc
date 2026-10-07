"""Desktop integration: the one place that talks to Win32.

* ``cursor()`` - cursor position in Qt *logical* coordinates (DPI-correct on
  scaled displays) plus the global left-button state.
* ``ClickThrough`` - a runtime toggle for WS_EX_TRANSPARENT.  Changing the
  window style with Qt's ``setWindowFlags`` would destroy and recreate the
  native window (flicker + tray reconnection), so we poke the ex-style bits
  directly.  Toggling touches no other flag, and we re-assert topmost after.
* screen geometry helpers for bounds, floors and multi-monitor dragging.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

VK_LBUTTON = 0x01

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

if ctypes.sizeof(ctypes.c_void_p) == 8:
    _get_style = user32.GetWindowLongPtrW
    _set_style = user32.SetWindowLongPtrW
    _style_t = ctypes.c_longlong
else:                                    # 32-bit Python
    _get_style = user32.GetWindowLongW
    _set_style = user32.SetWindowLongW
    _style_t = ctypes.c_long

_get_style.restype = _style_t
_get_style.argtypes = [wintypes.HWND, ctypes.c_int]
_set_style.restype = _style_t
_set_style.argtypes = [wintypes.HWND, ctypes.c_int, _style_t]


@dataclass(frozen=True)
class CursorState:
    x: float
    y: float
    left_down: bool


def cursor() -> CursorState:
    """Cursor in Qt logical coords (DPI-correct) + global button state."""
    pos = QCursor.pos()
    down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
    return CursorState(float(pos.x()), float(pos.y()), down)


class ClickThrough:
    """Runtime WS_EX_TRANSPARENT toggle for a Qt widget's native window."""

    def __init__(self, widget) -> None:
        self.widget = widget
        self.solid = False          # solid = NOT click-through
        self._hwnd: int | None = None

    # ------------------------------------------------------------------
    def _handle(self) -> int:
        if self._hwnd is None:
            self._hwnd = int(self.widget.winId())
        return self._hwnd

    def set_solid(self, solid: bool) -> None:
        if solid == self.solid:
            return
        hwnd = self._handle()
        style = _get_style(hwnd, GWL_EXSTYLE)
        if solid:
            new_style = style & ~WS_EX_TRANSPARENT
        else:
            new_style = style | WS_EX_TRANSPARENT
        _set_style(hwnd, GWL_EXSTYLE, new_style)
        # a style write can drop the window from the topmost band: re-assert
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.solid = solid

    def window_at(self, gx: float, gy: float) -> int:
        """Which window would receive a click at this global point."""
        pt = wintypes.POINT(int(gx), int(gy))
        return int(user32.WindowFromPoint(pt))

    def hit_tests_per_pixel(self, transparent_probe: tuple[float, float]
                            ) -> bool:
        """True when a (solid) layered window still ignores fully transparent
        pixels: probe a point that should be see-through and check that the
        click lands on whatever is underneath, not on us."""
        hwnd = self._handle()
        was_solid = self.solid
        self.set_solid(True)
        try:
            return self.window_at(*transparent_probe) != hwnd
        finally:
            self.set_solid(was_solid)


# --------------------------------------------------------------------------
def screen_rect_for(x: float, y: float) -> tuple[float, float, float, float]:
    """Available geometry (l, t, r, b) of the screen containing the point."""
    app = QApplication.instance()
    ix, iy = int(x), int(y)
    best = None
    for s in app.screens():
        g = s.availableGeometry()
        if g.contains(ix, iy):
            return (float(g.left()), float(g.top()), float(g.right()),
                    float(g.bottom()))
        if best is None:
            best = g       # fall back to the first screen
    g = best
    return (float(g.left()), float(g.top()), float(g.right()), float(g.bottom()))


def virtual_rect() -> tuple[float, float, float, float]:
    """Union of every screen's available geometry (for drag clamping)."""
    app = QApplication.instance()
    l = t = 10 ** 9
    r = b = -(10 ** 9)
    for s in app.screens():
        g = s.availableGeometry()
        l = min(l, g.left())
        t = min(t, g.top())
        r = max(r, g.right())
        b = max(b, g.bottom())
    return (float(l), float(t), float(r), float(b))
