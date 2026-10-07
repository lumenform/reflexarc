"""Record a short "life signs" demo of a running ReflexArc pet.

Drives the real cursor through the whole interaction chain while capturing
only the pet's neighbourhood:

    idle watching -> gaze follow -> hover stroking -> click pet-pet ->
    pick up -> carry around -> drop -> landing squash (and maybe a faint)

The pet must already be running (`python run.py --scale 1.25`).  Outputs
docs/life_demo_raw.mp4 at 20 fps; use --gif/--mp4 to also emit the final
cropped/compressed assets used by the README.

Usage:
    python scripts/record_life_demo.py                  # just the raw clip
    python scripts/record_life_demo.py --finalize       # raw + mp4 + gif
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

FPS = 20
ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
def pet_rect() -> tuple[int, int, int, int]:
    hwnd = user32.FindWindowW(None, "ReflexArc")
    if not hwnd:
        raise SystemExit("ReflexArc window not found - start `python run.py` first")
    r = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def cursor_pos() -> tuple[int, int]:
    p = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move_cursor(x: int, y: int, duration: float = 0.4) -> None:
    """Glide the cursor so the pet's eyes can follow the motion."""
    x0, y0 = cursor_pos()
    steps = max(1, int(duration / 0.02))
    for i in range(1, steps + 1):
        t = i / steps
        # ease in-out so the gaze turn looks deliberate
        e = t * t * (3 - 2 * t)
        user32.SetCursorPos(int(x0 + (x - x0) * e), int(y0 + (y - y0) * e))
        time.sleep(0.02)


class Timeline:
    def __init__(self) -> None:
        self.t0 = time.time()

    def at(self, t: float) -> None:
        d = self.t0 + t - time.time()
        if d > 0:
            time.sleep(d)

    def now(self) -> float:
        return time.time() - self.t0


class Recorder(threading.Thread):
    """Screen capture that also logs the cursor position per frame.

    mss cannot see the cursor, and without a visible pointer the whole
    interaction reads as a self-playing animation (confirmed by a Doubao
    review of the first cut).  So we record where the cursor was for every
    frame and paint a cursor into the clip during finalize.
    """

    def __init__(self, region: tuple[int, int, int, int], out: Path) -> None:
        super().__init__(daemon=True)
        # h264/yuv420p wants even dimensions
        l, t, r, b = region
        self.region = (l, t, l + (r - l) // 2 * 2, t + (b - t) // 2 * 2)
        self.out = out
        self.stop_flag = threading.Event()
        self.frames = 0
        self.cursor: list[tuple[int, int]] = []
        self.error: BaseException | None = None

    def run(self) -> None:
        import imageio.v2 as imageio
        import mss

        left, top, right, bottom = self.region
        mon = {"left": left, "top": top, "width": right - left,
               "height": bottom - top}
        pt = ctypes.wintypes.POINT()
        writer = None
        try:
            writer = imageio.get_writer(
                str(self.out), fps=FPS, codec="libx264", quality=8,
                macro_block_size=1, ffmpeg_log_level="error")
            t0 = time.time()
            with mss.mss() as sct:
                while not self.stop_flag.is_set():
                    due = t0 + self.frames / FPS
                    wait = due - time.time()
                    if wait > 0:
                        time.sleep(wait)
                    user32.GetCursorPos(ctypes.byref(pt))
                    self.cursor.append((pt.x - left, pt.y - top))
                    raw = np.asarray(sct.grab(mon))          # BGRA
                    writer.append_data(raw[:, :, :3][:, :, ::-1])
                    self.frames += 1
        except BaseException as exc:            # surface it to the main thread
            self.error = exc
        finally:
            if writer is not None:
                writer.close()


# --------------------------------------------------------------------------
def run_timeline(body_x: int, body_y: int, region: tuple[int, int, int, int],
                 tl: Timeline) -> None:
    """The choreography.  Times are seconds from the recording start.

    Cursor travels are kept inside the (tight) capture region so the pet
    stays large in frame throughout.
    """
    left, top, right, bottom = region
    up_left = (left + int((right - left) * 0.22), top + int((bottom - top) * 0.16))
    up_right = (left + int((right - left) * 0.86), top + int((bottom - top) * 0.22))
    down_left = (left + int((right - left) * 0.14), bottom - 60)
    on_body = (body_x, body_y)

    # 0-4: the pet just lives (breathing, blinking, gaze wander)
    tl.at(4.0)

    # 4-9: gaze follows the cursor around
    move_cursor(*down_left, duration=0.8)
    tl.at(5.7)
    move_cursor(*up_left, duration=0.8)
    tl.at(7.4)
    move_cursor(*up_right, duration=1.0)
    tl.at(9.4)

    # 9-12.5: hover on the pet -> slow stroking, hearts
    move_cursor(*on_body, duration=0.7)
    tl.at(12.6)

    # 12.6-13.6: a quick click = a pet-pet
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.09)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    tl.at(14.4)

    # 14.4: press and pick it up
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.25)
    tl.at(15.2)
    move_cursor(body_x - 260, body_y - 380, duration=1.2)
    tl.at(17.4)
    move_cursor(body_x - 430, body_y - 560, duration=1.0)
    tl.at(20.4)

    # 20.4: let go -> it falls
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    tl.at(22.4)

    # 22.4-26: it lands, squashes, maybe faints; we clean up the cursor
    move_cursor(right - 80, top + 90, duration=1.0)
    tl.at(27.0)

    # 27-32: back to idle; gaze settles and wanders
    move_cursor(left + 80, bottom - 90, duration=1.2)
    tl.at(32.5)

    # the record runs until this point
    tl.at(33.5)


def _minimize_all() -> None:
    """Clear the desktop behind the pet (restored via _restore_all)."""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(New-Object -ComObject Shell.Application).MinimizeAll()"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _restore_all() -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(New-Object -ComObject Shell.Application).UndoMinimizeAll()"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "life_demo_raw.mp4"))
    ap.add_argument("--finalize", action="store_true",
                    help="also emit docs/demo_life.mp4 and docs/demo_life.gif")
    args = ap.parse_args()

    left, top, right, bottom = pet_rect()
    w, h = right - left, bottom - top
    body_x = left + int(w * 0.465)
    body_y = top + int(h * 0.42)
    print(f"pet window {left},{top} - {right},{bottom}  body at {body_x},{body_y}")

    # tight framing: the pet fills about half the frame (a Doubao review of
    # the wide cut asked for the pet to be >= 1/3 of the frame)
    REG_W, REG_H = 800, 1000
    region = (max(0, body_x - int(REG_W * 0.75)),
              max(0, body_y - int(REG_H * 0.75)),
              min(3840, body_x + int(REG_W * 0.25)),
              min(2160, body_y + int(REG_H * 0.25)))
    print(f"capture region {region}  "
          f"({region[2]-region[0]}x{region[3]-region[1]})")

    orig = cursor_pos()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    rec = Recorder(region, out)
    _minimize_all()                 # clean desktop behind the pet
    time.sleep(0.6)
    hwnd = user32.FindWindowW(None, "ReflexArc")
    if not (hwnd and user32.IsWindowVisible(hwnd)):
        print("pet window vanished after MinimizeAll - aborting", file=sys.stderr)
        _restore_all()
        return 3
    rec.start()
    time.sleep(0.4)                 # let the writer settle

    tl = Timeline()
    try:
        run_timeline(body_x, body_y, rec.region, tl)
    finally:
        rec.stop_flag.set()
        rec.join(timeout=5)
        user32.SetCursorPos(*orig)
        _restore_all()

    if rec.error is not None:
        print(f"recording failed: {rec.error!r}", file=sys.stderr)
        return 2
    # keep the cursor track next to the clip so finalize can paint it in
    cursor_file = out.with_suffix(".cursor.json")
    cursor_file.write_text(json.dumps(rec.cursor), encoding="utf-8")
    dur = rec.frames / FPS
    print(f"recorded {rec.frames} frames ({dur:.1f}s) -> {out}")
    print(f"cursor track ({len(rec.cursor)} points) -> {cursor_file}")

    if args.finalize:
        finalize(out)
    return 0


def _bake_cursor(height: int = 32):
    """A classic arrow pointer with a soft drop shadow.

    mss captures no cursor, so without this the clip reads as a self-playing
    animation; pasting a pointer is what turns it into an interaction demo.
    """
    from PIL import Image, ImageDraw
    w = int(height * 0.66)
    im = Image.new("RGBA", (w + 10, height + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pts = [(3, 3), (3, height * 0.74), (w * 0.32, height * 0.58),
           (w * 0.50, height * 0.97), (w * 0.66, height * 0.90),
           (w * 0.48, height * 0.52), (w * 0.95, height * 0.52)]
    d.polygon([(x + 3, y + 3) for x, y in pts], fill=(0, 0, 0, 70))
    d.polygon(pts, fill=(252, 252, 252, 255),
              outline=(20, 20, 20, 255), width=3)
    return im


def finalize(raw: Path) -> None:
    """Compress to the README mp4 and a small looping gif, painting in the
    cursor track recorded alongside the clip.

    Streams the raw clip frame by frame; h264 needs even dimensions, which
    is easy to get wrong when scaling, so both outputs round to even.
    """
    import cv2
    import imageio.v2 as imageio
    from PIL import Image

    mp4 = raw.parent / "demo_life.mp4"
    gif = raw.parent / "demo_life.gif"

    # cursor track recorded by Recorder (frame -> region-relative position)
    track: list = []
    cursor_file = raw.with_suffix(".cursor.json")
    if cursor_file.exists():
        try:
            track = json.loads(cursor_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            track = []
    cursor_pm = _bake_cursor(46) if track else None

    reader = imageio.get_reader(str(raw))
    meta = reader.get_meta_data()
    fps = float(meta.get("fps", FPS))
    w, h = meta.get("size", (800, 1000))

    mp4_w = 640
    mp4_h = max(2, int(h * mp4_w / w) // 2 * 2)
    gif_w = 480
    gif_h = max(2, int(mp4_h * gif_w / mp4_w) // 2 * 2)
    sx, sy = mp4_w / max(1, w), mp4_h / max(1, h)

    writer = imageio.get_writer(str(mp4), fps=fps, codec="libx264",
                                quality=7, macro_block_size=1,
                                ffmpeg_log_level="error")
    gif_frames = []
    n = 0
    for i, frame in enumerate(reader):
        small = cv2.resize(frame, (mp4_w, mp4_h), interpolation=cv2.INTER_AREA)
        if cursor_pm is not None and i < len(track):
            px, py = track[i]
            im = Image.fromarray(small)
            # the arrow tip sits at (3, 3) inside the baked image: offset so
            # the tip - not the image corner - lands on the cursor position
            im.paste(cursor_pm, (int(px * sx) - 3, int(py * sy) - 3), cursor_pm)
            small = np.asarray(im)
        writer.append_data(small)
        if i % 2 == 0:                       # gif runs at half rate
            tiny = cv2.resize(small, (gif_w, gif_h),
                              interpolation=cv2.INTER_AREA)
            gif_frames.append(Image.fromarray(tiny))
        n += 1
    reader.close()
    writer.close()
    print(f"wrote {mp4} ({mp4.stat().st_size/1e6:.1f} MB, {n} frames)")

    # gif via ffmpeg: a shared palette plus inter-frame optimisation beats
    # PIL's per-frame encoder on real screen content by an order of magnitude
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        vf = ("fps=8,scale=480:-1:flags=lanczos,"
              "split[a][b];[a]palettegen=max_colors=96[p];"
              "[b][p]paletteuse=dither=bayer:bayer_scale=4")
        subprocess.run([ff, "-y", "-i", str(mp4), "-vf", vf, "-loop", "0",
                        str(gif)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"wrote {gif} ({gif.stat().st_size/1e6:.1f} MB)")
    except Exception as exc:
        print(f"gif encoding skipped: {exc!r}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
