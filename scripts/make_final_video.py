"""Cut the raw recording into the final demo:
- CPU-stress middle section played at 3x (time-lapse, honest)
- Chinese captions telling the causal story
Outputs docs/demo_real.mp4 and a compact docs/demo_real.gif.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "docs" / "demo_real_raw.mp4"
OUT_MP4 = ROOT / "docs" / "demo_real.mp4"
OUT_GIF = ROOT / "docs" / "demo_real.gif"

SPEEDUP_START, SPEEDUP_END, SPEED = 46.0, 134.0, 3

CAPTIONS = [
    (0.0, 46.0, "我打字的时候，它陪着一起忙"),
    (46.0, 134.0, "我把 CPU 压满…它比我先慌（×3 倍速）"),
    (134.0, 999.0, "摸一摸"),
]


def font(size: int):
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf"):
        try:
            return ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def caption_for(t: float) -> str:
    for a, b, text in CAPTIONS:
        if a <= t < b:
            return text
    return ""


def draw_caption(rgb: np.ndarray, text: str) -> np.ndarray:
    if not text:
        return rgb
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img, "RGBA")
    f = font(40)
    bbox = draw.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (img.width - tw) // 2
    y = img.height - 150
    pad = 18
    draw.rounded_rectangle([x - pad, y - pad, x + tw + pad, y + th + pad],
                           radius=14, fill=(15, 15, 25, 190))
    draw.text((x, y), text, font=f, fill=(240, 240, 250))
    return np.asarray(img)


def main() -> None:
    cap = cv2.VideoCapture(str(RAW))
    FPS = cap.get(cv2.CAP_PROP_FPS) or 20.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames: list[np.ndarray] = []
    times: list[float] = []
    for idx in range(total):
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / FPS
        if SPEEDUP_START <= t < SPEEDUP_END:
            if idx % SPEED != 0:      # keep 1 of every SPEED frames
                continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(draw_caption(rgb, caption_for(t)))
        times.append(t)
    cap.release()
    out_fps = float(FPS)
    print(f"kept {len(frames)} of {total} frames (~{len(frames)/out_fps:.0f}s @ {out_fps:.0f}fps)")

    w = imageio.get_writer(str(OUT_MP4), fps=out_fps, codec="libx264",
                           quality=7, macro_block_size=None,
                           ffmpeg_log_level="error")
    for fr in frames:
        w.append_data(fr)
    w.close()
    print("mp4 ->", OUT_MP4, f"{OUT_MP4.stat().st_size/1024/1024:.1f}MB")

    # compact GIF: typing (8s) + dizzy (8s) + petting (8s), 960px wide
    def pick(t0: float) -> list[np.ndarray]:
        return [f for f, t in zip(frames, times) if t0 <= t < t0 + 8][::2]

    gif_frames = []
    for t0 in (10.0, 60.0, 138.0):
        for fr in pick(t0):
            im = Image.fromarray(fr).resize((960, 540), Image.LANCZOS)
            gif_frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=128))
    if gif_frames:
        gif_frames[0].save(OUT_GIF, save_all=True, append_images=gif_frames[1:],
                           duration=int(1000 / out_fps * 2), loop=0, optimize=True)
        print("gif ->", OUT_GIF, f"{OUT_GIF.stat().st_size/1024/1024:.1f}MB")


if __name__ == "__main__":
    main()
