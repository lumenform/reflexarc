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
FPS = 10

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
    "# day 6 with my desktop pet",
    "class Boba:",
    "    def __init__(self):",
    "        self.energy = 0.75",
    "        self.boredom = 0.25",
    "",
    "    def live(self, senses):",
    "        while True:",
    "            drive = self.homeostasis(senses)",
    "            act = self.instinct(drive)",
    "            self.sprite.play(act)",
    "",
    "def homeostatic_drive(machine_state):",
    "    energy -= 0.03 * hours",
    "    boredom += 0.55 * idle_hours",
    "    mood = ema(mood, target, tau)",
    "    return dict(energy, boredom, mood)",
    "",
    "# the desk pet watches the user work...",
    "# typing fast makes it work too",
]


def burn(stop_flag) -> None:  # runs in child processes
    x = 1.0001
    while not stop_flag.value:
        for _ in range(20000):
            x = x * 1.000001 + 0.000001
        x = 1.0001


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
            last_rgb = None
            while not stop_event.is_set():
                frame = np.asarray(sct.grab(mon))          # BGRA
                frame = cv2.resize(frame, (OUT_W, OUT_H),
                                   interpolation=cv2.INTER_AREA)
                last_rgb = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
                # keep video time == real time: pad if we fell behind
                due = int((time.time() - start) * FPS) + 1
                while written < due:
                    writer.append_data(last_rgb)
                    written += 1
                sleep = (start + written * interval) - time.time()
                if sleep > 0:
                    time.sleep(sleep)
        finally:
            writer.close()


def type_code(seconds: float) -> None:
    """Type real keystrokes (only ASCII) with human-ish rhythm."""
    end = time.time() + seconds
    lines = list(CODE_LINES)
    while time.time() < end:
        for line in lines:
            if time.time() >= end:
                return
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
