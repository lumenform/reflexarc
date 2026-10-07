"""Sprite assets: petdex slices, the 16 gaze directions, measured geometry.

Loads a petdex-format spritesheet (8 sprite columns; v1 = 9 rows, v2 = 11)
and exposes three things:

* the nine classic animation rows, unchanged: ``ROWS``, ``frame()``;
* v2's sixteen gaze directions on rows 9-10: ``look(d)`` (d = 0..15);
* geometry measured from the atlas itself at load time - the ground line,
  per-frame foot centres (frames drift up to ~23px horizontally), per-frame
  lift (``failed``'s faint pose floats 36px above the ground), the eye
  anchor used for gaze maths, blink frames, and a coarse silhouette mask.

The 16 directions run clockwise from "straight up", which the atlas draws as
facing the viewer:

    d = round(deg(atan2(dx, -dy)) % 360 / 22.5) % 16      (screen y is down)

Verified against the boba atlas by muzzle-centroid analysis; re-verify a new
atlas with ``python -m tests.look_probe``.

All expensive work (alpha scans, alignment search, mask build) happens once
here. The per-frame paths are small lookups only.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from PySide6.QtGui import QImage, QPixmap

# petdex canonical row order (v1 8x9; v2 8x11 shares the first 9 rows)
ROWS = [
    "idle", "running-right", "running-left", "waving", "jumping",
    "failed", "waiting", "running", "review",
]

ROW_FPS = {
    # deliberately unhurried: fast row playback reads as flicker at this
    # size, especially the jumping row which plays while the pet is carried
    "idle": 5.0,
    "running-right": 8.0,
    "running-left": 8.0,
    "waving": 6.5,
    "jumping": 7.5,
    "failed": 3.2,   # a dizzy faint should look heavy, not twitchy
    "waiting": 5.0,
    "running": 8.0,
    "review": 4.5,
}

FRAMES_PER_ROW = 8
CELL_W, CELL_H = 192, 208

# v2 atlases add 16 gaze directions on rows 9-10 (8 per row).
LOOK_ROWS = (9, 10)
LOOK_COUNT = 16

_ALPHA = 20          # alpha above this counts as "drawn"
_HEAD_FRAC = 0.44    # eye anchor: fraction of the body box height


# --------------------------------------------------------------------------
# pixel probes (operate on ARGB32 QImages; each copies the buffer once into
# bytes and then runs C-speed slice scans / translate masks)
# --------------------------------------------------------------------------
def _argb(img: QImage) -> QImage:
    if img.format() != QImage.Format_ARGB32:
        img = img.convertToFormat(QImage.Format_ARGB32)
    return img


def _bytes(img: QImage) -> bytes:
    return bytes(img.constBits())


_TABLES: dict[int, bytes] = {}


def _alpha_table(thresh: int) -> bytes:
    """Byte-table mapping alpha > thresh -> 1, else 0 (for translate masks)."""
    t = _TABLES.get(thresh)
    if t is None:
        t = bytes(1 if v > thresh else 0 for v in range(256))
        _TABLES[thresh] = t
    return t


def _lowest_opaque_row(img: QImage, thresh: int = _ALPHA) -> int | None:
    """Lowest y that has any drawn pixel (the frame's foot line)."""
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    mv = _bytes(img)
    for y in range(h - 1, -1, -1):
        base = y * bpl
        if max(mv[base + 3:base + w * 4:4]) > thresh:
            return y
    return None


def _foot_span(img: QImage, bottom: int, band: int = 7,
               thresh: int = _ALPHA) -> tuple[int, int] | None:
    """(x_min, x_max) of drawn pixels in the bottom `band` rows."""
    w, bpl = img.width(), img.bytesPerLine()
    mv = _bytes(img)
    tbl = _alpha_table(thresh)
    x_min = x_max = None
    for y in range(max(0, bottom - band + 1), bottom + 1):
        base = y * bpl
        mask = mv[base + 3:base + w * 4:4].translate(tbl)
        a = mask.find(1)
        if a < 0:
            continue
        b = mask.rfind(1)
        if x_min is None or a < x_min:
            x_min = a
        if x_max is None or b > x_max:
            x_max = b
    if x_min is None:
        return None
    return x_min, x_max


def _opaque_bbox(img: QImage, thresh: int = _ALPHA
                 ) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) of drawn pixels."""
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    mv = _bytes(img)
    tbl = _alpha_table(thresh)
    left = right = top = bottom = None
    for y in range(h):
        base = y * bpl
        mask = mv[base + 3:base + w * 4:4].translate(tbl)
        a = mask.find(1)
        if a < 0:
            continue
        b = mask.rfind(1)
        if top is None:
            top = y
        bottom = y
        if left is None or a < left:
            left = a
        if right is None or b > right:
            right = b
    if top is None:
        return None
    return left, top, right, bottom


def _color_grid(img: QImage, cols: int = 48, rows: int = 52) -> list:
    """One sampled (r, g, b, a) per coarse cell - for frame comparisons."""
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    mv = _bytes(img)
    sx = max(1, w // cols)
    sy = max(1, h // rows)
    grid = []
    for gy in range(rows):
        y = min(h - 1, gy * sy)
        base = y * bpl
        for gx in range(cols):
            i = base + min(w - 1, gx * sx) * 4
            grid.append((mv[i + 2], mv[i + 1], mv[i], mv[i + 3]))  # RGB from BGRA
    return grid


def _grid_diff(a: list, b: list) -> int:
    """Number of coarse cells that differ between two colour grids."""
    bad = 0
    for pa, pb in zip(a, b):
        if abs(pa[3] - pb[3]) > 40:
            bad += 1
        elif (pa[3] > 40 and pb[3] > 40
              and abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2]) > 90):
            bad += 1
    return bad


def _sample_grid(img: QImage, cols: int = 48, rows: int = 52,
                 thresh: int = _ALPHA) -> bytearray:
    """Coarse coverage grid: cell = 1 if its sample pixel is drawn."""
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    mv = _bytes(img)
    sx = max(1, w // cols)
    sy = max(1, h // rows)
    grid = bytearray(cols * rows)
    k = 0
    for gy in range(rows):
        y = min(h - 1, gy * sy)
        y2 = min(h - 1, y + sy // 2)
        base = y * bpl
        base2 = y2 * bpl
        for gx in range(cols):
            x = min(w - 1, gx * sx)
            x2 = min(w - 1, x + sx // 2)
            # two taps per cell (corner + diagonal) keeps thin outlines alive
            if (mv[base + x * 4 + 3] > thresh
                    or mv[base2 + x2 * 4 + 3] > thresh):
                grid[k] = 1
            k += 1
    return grid


def _best_align(a: bytearray, b: bytearray, cols: int, rows: int,
                max_cells: int = 4) -> tuple[int, int, int]:
    """Shift offset (cells) that best aligns grid b onto a, plus mismatch."""
    best = (0, 0, 1 << 30)
    for dy in range(-max_cells, max_cells + 1):
        for dx in range(-max_cells, max_cells + 1):
            bad = 0
            for gy in range(rows):
                sy = gy - dy
                if sy < 0 or sy >= rows:
                    bad += cols
                    continue
                row_b = sy * cols
                row_a = gy * cols
                for gx in range(cols):
                    sx = gx - dx
                    a_v = a[row_a + gx]
                    b_v = b[row_b + sx] if 0 <= sx < cols else 0
                    if a_v != b_v:
                        bad += 1
            if bad < best[2]:
                best = (dx, dy, bad)
    return best


def _count_valid_frames(imgs: list[QImage]) -> int:
    """petdex sheets pad rows with fully transparent frames (jumping has 5,
    waving 4...). Count the non-empty prefix so animation never blinks out."""
    count = 0
    for img in imgs:
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()
        mv = _bytes(img)
        opaque = total = 0
        for y in range(0, h, 16):
            base = y * bpl
            for x in range(0, w, 16):
                total += 1
                if mv[base + x * 4 + 3] > _ALPHA:
                    opaque += 1
        if total and opaque > total * 0.02:
            count += 1
        else:
            break
    return max(1, count)


# --------------------------------------------------------------------------
class HitMask:
    """Coarse silhouette mask for hit tests (union over several frames so the
    test does not flicker while the sprite animates).  Grid coordinates are
    source-cell pixels; lookups are O(1)."""

    def __init__(self, cols: int = 48, rows: int = 52) -> None:
        self.cols = cols
        self.rows = rows
        self.grid = bytearray(cols * rows)

    def add(self, img: QImage) -> None:
        g = _sample_grid(img, self.cols, self.rows)
        grid = self.grid
        for i, v in enumerate(g):
            if v:
                grid[i] = 1

    def contains(self, src_x: float, src_y: float) -> bool:
        gx = int(src_x * self.cols / CELL_W)
        gy = int(src_y * self.rows / CELL_H)
        if 0 <= gx < self.cols and 0 <= gy < self.rows:
            return bool(self.grid[gy * self.cols + gx])
        return False


# --------------------------------------------------------------------------
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
        self.rows_count = max(1, img.height() // CELL_H)
        self.cell_h = img.height() // self.rows_count

        # ---- the nine classic rows ---------------------------------------
        self.frames: dict[str, list[QPixmap]] = {}
        self.frame_counts: dict[str, int] = {}
        self._qimages: dict[str, list[QImage]] = {}
        for r, name in enumerate(ROWS):
            if r >= self.rows_count:
                break
            imgs = [_argb(img.copy(c * self.cell_w, r * self.cell_h,
                                   self.cell_w, self.cell_h))
                    for c in range(FRAMES_PER_ROW)]
            self._qimages[name] = imgs
            self.frames[name] = [QPixmap.fromImage(im) for im in imgs]
            self.frame_counts[name] = _count_valid_frames(imgs)
        self.default_frames = self.frames.get("idle") or next(iter(self.frames.values()))

        # ---- v2 gaze directions ------------------------------------------
        self.look_frames: list[QPixmap] = []
        if self.rows_count > max(LOOK_ROWS):
            for r in LOOK_ROWS:
                for c in range(FRAMES_PER_ROW):
                    pm = QPixmap.fromImage(
                        img.copy(c * self.cell_w, r * self.cell_h,
                                 self.cell_w, self.cell_h))
                    self.look_frames.append(pm)
                if len(self.look_frames) >= LOOK_COUNT:
                    break
        self.has_look = len(self.look_frames) >= LOOK_COUNT

        self._measure()

    # ------------------------------------------------------------------
    def _measure(self) -> None:
        """One-time geometry measurement from the atlas pixels."""
        # ground line: most common frame bottom among grounded rows
        self.frame_bottoms: dict[str, list[int | None]] = {}
        votes: list[int] = []
        for name, imgs in self._qimages.items():
            bottoms: list[int | None] = [_lowest_opaque_row(im) for im in imgs]
            self.frame_bottoms[name] = bottoms
            if name != "failed":
                votes.extend(b for b in bottoms if b is not None)
        self.ground_y = float(statistics.mode(votes)) if votes else float(CELL_H - 6)

        # per-frame foot centre (x) - used to pin every frame to one anchor
        self.foot_cx: dict[str, list[float]] = {}
        for name, imgs in self._qimages.items():
            cx_list: list[float] = []
            for i, im in enumerate(imgs):
                b = self.frame_bottoms[name][i]
                span = _foot_span(im, b) if b is not None else None
                cx_list.append((span[0] + span[1]) / 2.0 if span else -1.0)
            self.foot_cx[name] = cx_list
        idle_cx = [v for v in self.foot_cx.get("idle", []) if v >= 0]
        self.anchor_src_x = statistics.median(idle_cx) if idle_cx else CELL_W / 2.0

        # body box of the first idle frame: drives eye anchor and body width
        bbox = _opaque_bbox(self._qimages["idle"][0]) if "idle" in self._qimages else None
        if bbox:
            l, t, r, b = bbox
            self.body_box = bbox
            self.body_w = float(r - l)
            # eyes sit in the head, roughly 44% down the body box
            self.eye_anchor = (self.anchor_src_x, t + _HEAD_FRAC * (b - t))
        else:
            self.body_box = None
            self.body_w = CELL_W * 0.6
            self.eye_anchor = (self.anchor_src_x, self.cell_h * 0.42)

        # blink frame: the idle frame closest to frame 0 that still differs
        # from it - that is the closed-eye drawing, because pet artists keep
        # the body identical and only redraw the eyes.  (A dark-ink scan
        # fails here: these atlases draw the whole body with dark outlines.)
        idle_imgs = self._qimages.get("idle", [])[:self.frame_counts.get("idle", 0)]
        self.blink_frames: list[int] = []
        if len(idle_imgs) > 1:
            grids = [_color_grid(im) for im in idle_imgs]
            base_grid = grids[0]
            diffs = [_grid_diff(g, base_grid) for g in grids[1:]]
            nonzero = [d for d in diffs if d > 0]
            if nonzero:
                limit = 0.5 * max(nonzero)
                best = min((d, i + 1) for i, d in enumerate(diffs) if 0 < d <= limit)
                self.blink_frames = [best[1]]

        # alignment of a blink frame against look[0] (they are not the same
        # drawing; without this the eye sockets jump a few pixels)
        self.blink_align = (0, 0)
        if self.has_look and self.blink_frames:
            look0 = _argb(self.look_frames[0].toImage())
            blink0 = self._qimages["idle"][self.blink_frames[0]]
            a = _sample_grid(look0)
            b = _sample_grid(blink0)
            dx, dy, _ = _best_align(a, b, 48, 52)
            self.blink_align = (int(dx * CELL_W / 48), int(dy * CELL_H / 52))

        # silhouette mask: union of idle + look frames (what the pet wears
        # 90% of the time)
        self.hit_mask = HitMask()
        for im in self._qimages["idle"]:
            self.hit_mask.add(im)
        for pm in self.look_frames:
            self.hit_mask.add(_argb(pm.toImage()))

        # QImages no longer needed once measured (look frames stay as pixmaps)
        self._qimages = {}

    # ------------------------------------------------------------------
    # public lookups (per-frame safe: dict/float reads only)
    # ------------------------------------------------------------------
    def frame(self, row: str, index: int) -> QPixmap:
        frames = self.frames.get(row, self.default_frames)
        n = self.frame_counts.get(row, len(frames))
        return frames[int(index) % max(1, n)]

    def look(self, d: int) -> QPixmap:
        if not self.look_frames:
            return self.frame("idle", 0)
        return self.look_frames[int(d) % LOOK_COUNT]

    def draw_offset(self, row: str, index: int) -> tuple[float, float]:
        """Source-pixel offset that pins this frame's foot to the anchor:
        keeps x steady across gaze turns, and lifts ``failed[7]`` (drawn 36px
        above the baseline) back down onto the ground."""
        if row == "look":
            idx = int(index) % LOOK_COUNT
            if self.has_look:
                span = _cached(self, "look_foot_cx")
                if span is None:
                    span = []
                    for pm in self.look_frames:
                        im = _argb(pm.toImage())
                        b = _lowest_opaque_row(im)
                        s = _foot_span(im, b) if b is not None else None
                        span.append((s[0] + s[1]) / 2.0 if s else self.anchor_src_x)
                    _cache(self, "look_foot_cx", span)
                dx = self.anchor_src_x - span[idx]
                bottoms = _cached(self, "look_bottoms")
                if bottoms is None:
                    bottoms = []
                    for pm in self.look_frames:
                        im = _argb(pm.toImage())
                        b = _lowest_opaque_row(im)
                        bottoms.append(b if b is not None else int(self.ground_y))
                    _cache(self, "look_bottoms", bottoms)
                dy = self.ground_y - bottoms[idx]
                return dx, dy
            return 0.0, 0.0
        bottoms = self.frame_bottoms.get(row)
        cxs = self.foot_cx.get(row)
        dx = dy = 0.0
        if cxs and index < len(cxs) and cxs[index] >= 0:
            dx = self.anchor_src_x - cxs[index]
        if bottoms and index < len(bottoms) and bottoms[index] is not None:
            dy = self.ground_y - bottoms[index]
        return dx, dy

    def lift(self, row: str, index: int) -> float:
        """How far this frame floats above the ground line (0 for grounded)."""
        bottoms = self.frame_bottoms.get(row)
        if bottoms and index < len(bottoms) and bottoms[index] is not None:
            return max(0.0, self.ground_y - bottoms[index])
        return 0.0


# tiny attribute cache (keeps __init__ fast; look geometry is lazy)
def _cache(obj, name: str, value) -> None:
    setattr(obj, "_c_" + name, value)


def _cached(obj, name: str):
    return getattr(obj, "_c_" + name, None)


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
