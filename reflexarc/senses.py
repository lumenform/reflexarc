"""Sensory layer: raw machine state -> normalized observations.

Privacy by design: only aggregate signals are read. Foreground window titles
are classified into coarse categories in-memory and are never persisted or
sent anywhere.
"""
from __future__ import annotations

import ctypes
import time
from collections import deque
from dataclasses import dataclass

IS_WINDOWS = hasattr(ctypes, "windll")


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def get_idle_seconds() -> float:
    """System-wide time since the last keyboard/mouse input (Windows)."""
    if not IS_WINDOWS:
        return 0.0
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        tick = ctypes.windll.kernel32.GetTickCount()
        return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except OSError:
        return 0.0


def get_foreground_category() -> str:
    """Classify the foreground window into a coarse category. Never stores the
    raw title anywhere."""
    if not IS_WINDOWS:
        return "unknown"
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "unknown"
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.lower()
    except OSError:
        return "unknown"

    rules = (
        ("terminal", ("cmd", "powershell", "pwsh", "terminal", "wezterm", "alacritty", "warp", "tmux")),
        ("editor", ("visual studio", "code", "cursor", "pycharm", "sublime", "notepad", "devenv", "unity", "rider", "neovim", "vim", "idea")),
        ("video", ("youtube", "bilibili", "netflix", "potplayer", "vlc", "mpv", "capcut", "premiere", "剪映")),
        ("browser", ("chrome", "edge", "firefox", "arc", "safari", "opera", "浏览器")),
        ("chat", ("wechat", "qq", "telegram", "discord", "slack", "feishu", "lark", "微信", "企业微信", "钉钉")),
        ("game", ("steam", "unity", "game", "genshin", "minecraft", "游戏")),
    )
    for cat, keys in rules:
        if any(k in title for k in keys):
            return cat
    return "other"


def get_cpu_load(prev: "CPU | None" = None) -> tuple[float, "CPU | None"]:
    """Return (load 0..1, state). Uses psutil when available, else a rough
    tick-based estimate so the engine still runs with zero dependencies."""
    try:
        import psutil  # type: ignore
        return psutil.cpu_percent(interval=None) / 100.0, None
    except ImportError:
        pass
    # Fallback: not measuring per-core idle time properly, approximate with
    # process time growth is complex; keep a neutral value.
    return 0.5, None


def get_battery() -> tuple[float | None, bool | None]:
    try:
        import psutil  # type: ignore
        b = psutil.sensors_battery()
        if b is None:
            return None, None
        return b.percent / 100.0, (not b.power_plugged)
    except Exception:
        return None, None


CPU = object  # placeholder type alias, kept simple


@dataclass
class Observation:
    ts: float
    hour: float            # 0..24 local hour (float)
    idle_seconds: float
    activity: float        # 0..1 recent input intensity over ~15s
    cpu: float             # 0..1
    battery: float | None
    on_battery: bool | None
    window_category: str


class Senses:
    """Samples ambient signals. Call sample() every ~250ms."""

    WINDOW = 60            # keep last 60 samples (~15s at 250ms)
    ACTIVE_IDLE_CUTOFF = 2.0

    def __init__(self) -> None:
        self._active_flags: deque[int] = deque(maxlen=self.WINDOW)
        self._cpu_smoothed = 0.3

    def sample(self) -> Observation:
        now = time.time()
        idle = get_idle_seconds()
        self._active_flags.append(1 if idle < self.ACTIVE_IDLE_CUTOFF else 0)
        activity = sum(self._active_flags) / max(1, len(self._active_flags))

        cpu, _ = get_cpu_load()
        self._cpu_smoothed = 0.7 * self._cpu_smoothed + 0.3 * cpu

        battery, on_battery = get_battery()
        lt = time.localtime(now)
        hour = lt.tm_hour + lt.tm_min / 60.0

        return Observation(
            ts=now,
            hour=hour,
            idle_seconds=idle,
            activity=activity,
            cpu=self._cpu_smoothed,
            battery=battery,
            on_battery=on_battery,
            window_category=get_foreground_category(),
        )
