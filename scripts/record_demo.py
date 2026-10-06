"""Record a real-screen demo of ReflexArc.

Choreography (about 110 seconds, all real events):
  phase 0  0-6s    : notepad ready, pet idles on the desktop
  phase 1  6-46s   : real keystrokes -> pet mirrors the work
  phase 2  46-86s  : real CPU stress -> pet becomes overwhelmed
  phase 3  86-108s : stress stops, mouse pets the pet (clicks)
  finish           : pet process closed, mp4 written

Run from the repo root:
    python scripts/record_demo.py [seconds_override]
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import imageio
import mss
import numpy as np
import pyautogui
import pygetwindow as gw

pyautogui.FAILSAFE = False

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "demo_real_raw.mp4"
OUT_W, OUT_H = 1920, 1080
FPS = 20

PET_SCALE = 1.25                   # physical sprite is 480x520 on this 200% display


def find_pet_center() -> tuple[int, int] | None:
    """HWND rect of the pet window, in this process's own coordinate space
    (same space pyautogui moves in, whatever the DPI setup is)."""
    import ctypes, ctypes.wintypes
    hwnd = ctypes.windll.user32.FindWindowW(None, "ReflexArc")
    if not hwnd:
        return None
    rect = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)

CODE_LINES = [
    "# reflexarc - a nervous system for a tiny desktop creature",
    "import time",
    "from dataclasses import dataclass",
    "",
    "@dataclass",
    "class Drives:",
    "    energy: float = 0.75",
    "    boredom: float = 0.25",
    "    mood: float = 0.65",
    "    attachment: float = 0.40",
    "",
    "class Senses:",
    "    def sample(self):",
    "        idle = get_last_input_seconds()",
    "        cpu = read_cpu_percent() / 100",
    "        return dict(idle=idle, cpu=cpu, hour=local_hour())",
    "",
    "def homeostasis(drives, obs, dt):",
    "    hours = dt / 3600",
    "    drives.energy -= 0.03 * hours",
    "    drives.boredom += 0.55 * hours if obs[\'idle\'] > 120 else 0",
    "    target = 0.5 + 0.2 * (drives.energy - 0.5)",
    "    drives.mood += (target - drives.mood) * min(1, dt / 900)",
    "    return drives",
    "",
    "def instinct(drives):",
    "    scores = {}",
    "    scores[\'rest\'] = 2.4 * max(0, 0.62 - drives.energy) ** 1.5",
    "    scores[\'walk\'] = 1.7 * drives.boredom * drives.energy",
    "    scores[\'watch\'] = 1.3 * drives.attachment",
    "    return max(scores, key=scores.get)",
    "",
    "def live(senses, sprite):",
    "    drives = Drives()",
    "    last = time.time()",
    "    while True:",
    "        now = time.time()",
    "        obs = senses.sample()",
    "        homeostasis(drives, obs, now - last)",
    "        act = instinct(drives)",
    "        sprite.play(act)",
    "        last = now",
    "        time.sleep(0.25)",
    "",
    "if __name__ == \'__main__\':",
    "    live(Senses(), sprite=PETDEX_SPRITE)",
    "",
    "# the strange part: it is not animated, it is alive",
    "# every state above is earned by what THIS machine is doing",
]


def burn(stop_flag) -> None:  # runs in child processes
    x = 1.0001
    while not stop_flag.value:
        for _ in range(20000):
            x = x * 1.000001 + 0.000001
        x = 1.0001


_FONT_CACHE: dict = {}


def _font(size: int):
    from PIL import ImageFont
    if size not in _FONT_CACHE:
        f = None
        for name in ("segoeui.ttf", "arial.ttf"):
            try:
                f = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        _FONT_CACHE[size] = f or ImageFont.load_default()
    return _FONT_CACHE[size]


def _draw_cursor_and_overlays(rgb: np.ndarray) -> np.ndarray:
    """mss does not capture the mouse cursor, so we draw it ourselves.
    Also paints a live CPU meter so the 'stress' phase has visual proof."""
    from PIL import Image, ImageDraw
    import ctypes, ctypes.wintypes
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None) / 100.0
    except Exception:
        cpu = 0.0

    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img, "RGBA")

    # --- CPU meter (top-right) ---
    x0, y0, w, h = img.width - 320, 24, 296, 54
    draw.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=10,
                           fill=(12, 12, 22, 180))
    pct = max(0.0, min(1.0, cpu))
    bar_w = int((w - 16) * pct)
    color = (90, 200, 120) if pct < 0.6 else ((240, 190, 60) if pct < 0.85
                                              else (235, 80, 80))
    draw.rounded_rectangle([x0 + 8, y0 + h - 20, x0 + 8 + bar_w, y0 + h - 8],
                           radius=6, fill=color)
    draw.text((x0 + 10, y0 + 6), f"CPU {int(pct * 100)}%",
              font=_font(20), fill=(235, 235, 245))

    # --- cursor ---
    user32 = ctypes.windll.user32
    pt = ctypes.wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        cx, cy = pt.x // 2, pt.y // 2      # physical -> 1080p half scale
        down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
        if down:
            draw.ellipse([cx - 26, cy - 26, cx + 26, cy + 26],
                         outline=(255, 210, 90, 220), width=5)
        pts = [(cx, cy), (cx + 4, cy + 26), (cx + 11, cy + 18),
               (cx + 20, cy + 30), (cx + 27, cy + 25), (cx + 18, cy + 14),
               (cx + 28, cy + 11)]
        draw.polygon([(px, py) for px, py in pts],
                     fill=(255, 255, 255, 235))
        draw.line([(cx, cy), (cx + 4, cy + 26), (cx + 11, cy + 18),
                   (cx + 20, cy + 30), (cx + 27, cy + 25), (cx + 18, cy + 14),
                   (cx + 28, cy + 11), (cx, cy)],
                  fill=(20, 20, 20, 255), width=2)
    return np.asarray(img)


def record_loop(stop_event: threading.Event) -> None:
    with mss.mss() as sct:
        mon = sct.monitors[1]
        writer = imageio.get_writer(str(OUT), fps=FPS, codec="libx264",
                                    quality=7, macro_block_size=None,
                                    ffmpeg_log_level="error")
        try:
            interval = 1.0 / FPS
            start = time.time()
            written = 0
            while not stop_event.is_set():
                frame = np.asarray(sct.grab(mon))          # BGRA
                frame = cv2.resize(frame, (OUT_W, OUT_H),
                                   interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
                rgb = _draw_cursor_and_overlays(rgb)
                due = int((time.time() - start) * FPS) + 1
                while written < due:
                    writer.append_data(rgb)
                    written += 1
                sleep = (start + written * interval) - time.time()
                if sleep > 0:
                    time.sleep(sleep)
        finally:
            writer.close()


def force_english_input() -> None:
    """Make sure the active keyboard layout is plain English (US) so every
    keystroke lands literally instead of through an IME."""
    import ctypes, ctypes.wintypes
    user32 = ctypes.windll.user32
    hkl = user32.LoadKeyboardLayoutW("00000409", 1)  # KLF_ACTIVATE
    if not hkl:
        return
    user32.ActivateKeyboardLayout(hkl, 0)
    # also tell every top-level window to switch to it (esp. notepad)
    WM_INPUTLANGCHANGEREQUEST = 0x0050
    hwnds = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl)
        return True
    user32.EnumWindows(cb, 0)


_TYPE_POS = {"i": 0}


def type_code(seconds: float) -> None:
    """Type real keystrokes (only ASCII) with human-ish rhythm. The cursor
    continues where the previous call stopped, so no line repeats in a row."""
    end = time.time() + seconds
    while time.time() < end:
        line = CODE_LINES[_TYPE_POS["i"] % len(CODE_LINES)]
        _TYPE_POS["i"] += 1
        pyautogui.typewrite(line, interval=0.035)
        pyautogui.press("enter")
        time.sleep(0.35)


def main() -> None:
    duration = sum([6, 40, 40, 22])
    if len(sys.argv) > 1:
        duration = float(sys.argv[1])

    py = sys.executable
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8"})

    print("[record] launching pet...", flush=True)
    pet = subprocess.Popen(
        [py, "-m", "reflexarc.cli", "--scale", str(PET_SCALE), "--fresh",
         "--no-laya"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(4.0)

    print("[record] opening notepad...", flush=True)
    subprocess.Popen(["notepad.exe"])
    time.sleep(2.5)
    try:
        wins = [w for w in gw.getAllWindows()
                if ("Notepad" in w.title or "记事本" in w.title) and w.visible]
        if wins:
            w = wins[0]
            w.activate()
            time.sleep(0.4)
            w.maximize()
    except Exception as exc:
        print("[record] notepad maximize failed:", exc, flush=True)
    time.sleep(1.5)

    print("[record] start capture", flush=True)
    stop = threading.Event()
    t = threading.Thread(target=record_loop, args=(stop,), daemon=True)
    t.start()

    t0 = time.time()
    plan_end = t0 + duration

    try:
        print("[phase] idle desk (3s)", flush=True)
        while time.time() < t0 + 6:
            time.sleep(0.2)

        print("[phase] typing (40s)", flush=True)
        force_english_input()
        time.sleep(0.5)
        type_code(40)

        print("[phase] cpu stress on (95s: 35s typing + 60s stopped)", flush=True)
        stop_flag = mp.Value("b", False)
        n_workers = max(4, (os.cpu_count() or 8) - 2)
        print(f"[phase] burning with {n_workers} workers (cpu_count="
              f"{os.cpu_count()})", flush=True)
        workers = [mp.Process(target=burn, args=(stop_flag,))
                   for _ in range(n_workers)]
        for w in workers:
            w.start()
        type_code(35)          # stubborn: keeps typing as the machine heats up
        print("[phase] user stops; pet still has to endure", flush=True)
        time.sleep(60)         # hands off the keyboard, the pet feels it alone
        stop_flag.value = True
        for w in workers:
            w.join(timeout=2)
            if w.is_alive():
                w.terminate()

        print("[phase] petting (22s)", flush=True)
        center = find_pet_center()
        print("[phase] pet center:", center, flush=True)
        if center:
            pyautogui.moveTo(*center, duration=0.8)
            for _ in range(3):
                pyautogui.click()
                time.sleep(3.4)
        while time.time() < plan_end:
            time.sleep(0.2)
    finally:
        stop.set()
        t.join(timeout=10)
        if pet.poll() is None:
            pet.terminate()
        print("[record] pet closed", flush=True)

    print("[record] video ->", OUT, flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    main()
