"""The pose sweep (Step 4B, task 4B.1): every motion at its extreme poses, checked for holes,
seams and detached parts.

    report = sweep_character(film, "kit")    # every view, every motion, no GPU
    report.defects                           # [Defect(kind="seam", motion="wave[left]", ...)]

Why: a puppet that looks right at rest can break up at the end of a swing (a limb pivots off its
neighbour and background shows through). The sweep makes that measurable, so later cut fixes
(4B.2 to 4B.5) are judged by a number instead of by a viewer's eye.

How, in three layers:
1. **Which frames (pure).** `extreme_frames` samples a motion's keyframes: for every animated
   channel (a bone's angle, or the x / y of a joint shift) the frames where it reaches its
   minimum and its maximum. A motion that only ever reaches an extreme at a key lands exactly
   on those frames, because the motions are keyframed at their reversal points.
2. **Rendering (Synfig backend, CPU).** A scratch film under renders/pose-sweep/work/ links the
   real character folders and holds a **probe background**: a flat magenta (#ff00ff) backdrop, the
   same sentinel idea as the background preview (studio_core.preview.background). Anything that
   is not magenta is figure; magenta inside the figure is a hole. The frames are the ones
   `studio_core.shot.build_shot` builds for a shot with one character and one motion.
3. **Checks (pure, numpy).** `check_frame` takes an RGB frame and returns the defects:
   - **hole**: a background region fully enclosed by figure, small next to the figure (a large
     enclosed gap, like a hand on the hip, is a pose and not a defect);
   - **seam**: a thin background sliver inside the figure's silhouette (the silhouette is the
     figure morphologically closed by `close_px`), whether enclosed or open at one end;
   - **detached**: a connected figure piece bigger than a speck that does not touch the main body.
   Thresholds are `Thresholds`; they are in pixels at the sweep's render size (`SWEEP_SIZE`).
"""

from __future__ import annotations

import json
import math
import shutil
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from studio_core.config import StudioConfig, load_config
from studio_core.motions import MOTIONS, animate
from studio_core.motions.timeline import Clip
from studio_core.preview.common import Log, font, quiet, rest_box
from studio_core.rig import load_rig
from studio_core.scene import DESIGN
from studio_core.shot import build_shot, load_shot
from studio_core.shot_spec import (
    FPS,
    FilmFolder,
    add_action,
    create_shot,
    place_character,
)
from studio_core.sif import Vec
from studio_core.sif.render import render_frames

SHOT = "s00_sh02"
PROBE = "pose_sweep_probe"
SENTINEL = (255, 0, 255)  # the probe backdrop: magenta, as in the background preview
SWEEP_SIZE = (960, 540)  # render size; figure height is FIGURE_FRACTION of it
FIGURE_FRACTION = 0.62
FEET = (0.5, 0.92)
VIEWS = ("front", "three_quarter")
# Motions with a `side` parameter are swept once per side the rig has arms (or a head) for.
SIDED = {
    "wave": ("upper_arm", "forearm"),
    "point": ("upper_arm",),
    "talk_gesture": ("upper_arm",),
    "head_tilt": ("head",),
    "shrug": ("head",),
    "look_around": ("head",),
    "laugh": ("head",),
    "think": ("upper_arm", "forearm"),
}
SKIPPED = ("blink",)  # moves only the eyes, which the face drawing owns


@dataclass(frozen=True)
class Thresholds:
    """What counts as a defect, in pixels at SWEEP_SIZE (960x540)."""

    magenta_tol: int = 60  # a pixel within this per channel of the sentinel is background
    close_px: int = 6  # the silhouette closes gaps up to 2x this wide
    seam_width_px: int = 4  # a background region this narrow or narrower is a sliver
    seam_min_px: int = 14  # area of the smallest enclosed sliver reported
    seam_open_len_px: int = (
        90  # an open sliver (a slit, not enclosed) must be this long (bbox diagonal)
    )
    hole_min_px: int = 12  # area of the smallest enclosed hole reported
    hole_max_frac: float = 0.01  # larger than this share of the figure: a gap in the pose
    speck_frac: float = 0.002  # a detached piece must exceed this share of the figure
    speck_min_px: int = 30


# --------------------------------------------------------------------------- which frames (pure)


def _extremes(values: list[tuple[int, float]]) -> dict[int, str]:
    """{frame: 'min' | 'max'} for a channel's (frame, value) keys; empty if it never moves."""
    lo = min(values, key=lambda kv: kv[1])
    hi = max(values, key=lambda kv: kv[1])
    if hi[1] - lo[1] < 1e-6:
        return {}
    return {lo[0]: "min", hi[0]: "max"}


def extreme_frames(clip: Clip) -> dict[int, list[str]]:
    """The frames where a clip's channels reach their minimum and maximum, each with the reasons
    ('upper_arm_l angle max'). Angle channels use the angle; shift channels, x and y separately."""
    found: dict[int, list[str]] = {}
    for (kind, bone), keys in clip.channels.items():
        axes: dict[str, list[tuple[int, float]]] = {}
        for k in keys:
            v = k.value
            if isinstance(v, Vec):
                axes.setdefault(f"{kind} x", []).append((k.frame, float(v.x)))
                axes.setdefault(f"{kind} y", []).append((k.frame, float(v.y)))
            elif isinstance(v, (int, float)):
                axes.setdefault(kind, []).append((k.frame, float(v)))
        for axis, values in axes.items():
            for frame, which in _extremes(values).items():
                found.setdefault(frame, []).append(f"{bone} {axis} {which}")
    return dict(sorted(found.items()))


def motion_variants(view: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """(label, motion, params) for every motion in the library the rig can perform: sided motions
    once per side that has the bones; `point` and `wave` at full energy to reach the extremes."""
    roles = {spec.get("role") for spec in view["bones"].values()}
    sides = {
        spec.get("side") for spec in view["bones"].values() if spec.get("side") in ("left", "right")
    }
    out = []
    for name in MOTIONS:
        if name in SKIPPED:
            continue
        if name in SIDED:
            if not all(r in roles for r in SIDED[name]):
                continue
            for side in sorted(sides):
                out.append((f"{name}[{side}]", name, {"side": side, "energy": 1.0}))
        else:
            out.append((name, name, {"energy": 1.0}))
    return out


# --------------------------------------------------------------------------- the checks (pure)


@dataclass(frozen=True)
class Defect:
    kind: str  # "hole" | "seam" | "detached"
    area_px: int
    center: tuple[int, int]  # (x, y) in the frame
    box: tuple[int, int, int, int]  # (left, top, right, bottom) in the frame
    character: str = ""
    view: str = ""
    motion: str = ""
    frame: int = -1

    def message(self) -> str:
        return (
            f"{self.character} {self.view} {self.motion} frame {self.frame}: {self.kind} "
            f"of {self.area_px} px at {self.center}"
        )


def figure_mask(rgb: np.ndarray, tol: int) -> np.ndarray:
    """True where the pixel is figure (not the magenta probe backdrop)."""
    diff = np.abs(rgb.astype(np.int16) - np.array(SENTINEL, dtype=np.int16))
    return diff.max(axis=2) > tol


def _shift_stack(mask: np.ndarray, r: int, op: Any) -> np.ndarray:
    """op over the (2r+1)x(2r+1) square neighbourhood (edges count as False)."""
    if r <= 0:
        return mask
    pad = np.pad(mask, r, constant_values=False)
    h, w = mask.shape
    out = None
    # separable: rows then columns
    for axis_len, axis in ((w, 1), (h, 0)):
        src = pad if out is None else np.pad(out, r, constant_values=False)
        acc = None
        for d in range(2 * r + 1):
            sl = src[r : r + h, d : d + axis_len] if axis == 1 else src[d : d + axis_len, r : r + w]
            acc = sl.copy() if acc is None else op(acc, sl)
        out = acc
    assert out is not None
    return out


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    return _shift_stack(mask, r, np.logical_or)


def erode(mask: np.ndarray, r: int) -> np.ndarray:
    """Erosion that treats the outside of the array as set, so a region touching the edge keeps
    its width there."""
    return ~dilate(~mask, r) if r > 0 else mask


def close(mask: np.ndarray, r: int) -> np.ndarray:
    """Morphological closing: fills gaps up to 2r wide."""
    padded = np.pad(mask, r + 1, constant_values=False)
    return erode(dilate(padded, r), r)[r + 1 : -(r + 1), r + 1 : -(r + 1)]


def label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected components, labels 1..n (0 = not in the mask). Run-based union-find, so it
    is cheap on large flat regions."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    parent: list[int] = [0]

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    prev: list[tuple[int, int, int]] = []  # (start, end exclusive, id) of the row above
    for y in range(h):
        row = mask[y]
        padded = np.concatenate(([False], row, [False]))
        edges = np.flatnonzero(padded[1:] != padded[:-1])
        runs = []
        for s, e in zip(edges[0::2], edges[1::2], strict=True):
            rid = len(parent)
            parent.append(rid)
            runs.append((int(s), int(e), rid))
            for ps, pe, pid in prev:
                if ps < e and s < pe:  # overlapping columns: 4-connected
                    ra, rb = find(rid), find(pid)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
            labels[y, s:e] = rid
        prev = runs
    roots = np.array([find(i) for i in range(len(parent))], dtype=np.int32)
    uniq = {int(r): i for i, r in enumerate(sorted(set(roots[1:].tolist())), start=1)}
    lut = np.zeros(len(parent), dtype=np.int32)
    for i in range(1, len(parent)):
        lut[i] = uniq[int(roots[i])]
    return lut[labels], len(uniq)


def _defect(kind: str, comp: np.ndarray, origin: tuple[int, int]) -> Defect:
    ys, xs = np.nonzero(comp)
    ox, oy = origin
    return Defect(
        kind,
        int(comp.sum()),
        (int(xs.mean()) + ox, int(ys.mean()) + oy),
        (int(xs.min()) + ox, int(ys.min()) + oy, int(xs.max()) + ox + 1, int(ys.max()) + oy + 1),
    )


def check_frame(rgb: np.ndarray, th: Thresholds | None = None) -> list[Defect]:
    """Holes, seams and detached parts in one frame rendered on the magenta probe backdrop."""
    th = th or Thresholds()
    fg_full = figure_mask(rgb, th.magenta_tol)
    if not fg_full.any():
        return []
    ys, xs = np.nonzero(fg_full)
    pad = th.close_px * 2 + 4
    x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
    x1, y1 = min(rgb.shape[1], int(xs.max()) + 1 + pad), min(rgb.shape[0], int(ys.max()) + 1 + pad)
    fg = fg_full[y0:y1, x0:x1]
    origin = (x0, y0)
    found: list[Defect] = []

    # detached parts: figure components other than the main body, bigger than a speck
    # (joined across one-pixel cracks, which are seams and not detachment)
    fg_labels, n = label(dilate(fg, 1))
    fg_labels = np.where(fg, fg_labels, 0)
    sizes = np.bincount(fg_labels.ravel(), minlength=n + 1)[1:]
    main = int(np.argmax(sizes)) + 1
    speck = max(th.speck_min_px, th.speck_frac * int(sizes.max()))
    for i in range(1, n + 1):
        if i != main and sizes[i - 1] > speck:
            found.append(_defect("detached", fg_labels == i, origin))

    # holes and seams: background inside the (closed) silhouette
    bg = ~fg
    bg_labels, m = label(bg)
    outside = {
        int(v)
        for v in np.unique(
            np.concatenate((bg_labels[0], bg_labels[-1], bg_labels[:, 0], bg_labels[:, -1]))
        )
        if v
    }
    hull = close(fg, th.close_px)
    figure_area = int(fg.sum())
    kr = th.seam_width_px // 2  # erosion radius that removes regions of width <= seam_width
    for i in range(1, m + 1):
        comp = bg_labels == i
        enclosed = i not in outside
        inside = comp if enclosed else comp & hull
        if not inside.any():
            continue
        for j in range(1, label(inside)[1] + 1) if not enclosed else [1]:
            piece = inside if enclosed else label(inside)[0] == j
            area = int(piece.sum())
            thin = not erode(piece, kr).any()
            if thin and area >= th.seam_min_px:
                d = _defect("seam", piece, origin)
                x0, y0, x1, y1 = d.box
                # Open slivers are mostly the pose's own slits (an arm hanging beside the body,
                # fur notches); only a long one counts. An enclosed sliver always does.
                if enclosed or math.hypot(x1 - x0, y1 - y0) >= th.seam_open_len_px:
                    found.append(d)
            elif enclosed and not thin and th.hole_min_px <= area <= th.hole_max_frac * figure_area:
                found.append(_defect("hole", piece, origin))
    return found


# --------------------------------------------------------------------------- the sweep


@dataclass
class FrameResult:
    view: str
    motion: str
    frame: int
    reasons: list[str]
    defects: list[Defect]
    image: Image.Image | None = field(default=None, repr=False)  # the rendered frame


@dataclass
class SweepReport:
    character: str
    thresholds: Thresholds
    results: list[FrameResult] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def defects(self) -> list[Defect]:
        return [d for r in self.results for d in r.defects]

    def counts(self) -> dict[str, dict[str, int]]:
        """{"<view> <motion>": {"hole": n, "seam": n, "detached": n, "frames": n}}"""
        out: dict[str, dict[str, int]] = {}
        for r in self.results:
            row = out.setdefault(
                f"{r.view} {r.motion}", {"hole": 0, "seam": 0, "detached": 0, "frames": 0}
            )
            row["frames"] += 1
            for d in r.defects:
                row[d.kind] += 1
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "character": self.character,
            "seconds": round(self.seconds, 1),
            "thresholds": asdict(self.thresholds),
            "counts": self.counts(),
            "frames": [
                {
                    "view": r.view,
                    "motion": r.motion,
                    "frame": r.frame,
                    "reasons": r.reasons,
                    "defects": [
                        {
                            k: v
                            for k, v in asdict(d).items()
                            if k not in ("character", "view", "motion", "frame")
                        }
                        for d in r.defects
                    ],
                }
                for r in self.results
            ],
        }


def scratch_film(work: Path, characters: dict[str, Path]) -> FilmFolder:
    """A throwaway film under `work` that links the real character folders (read only: nothing is
    written into them) and holds the magenta probe background."""
    root = work / "sweep"
    shutil.rmtree(root, ignore_errors=True)
    (root / "characters").mkdir(parents=True)
    for cid, folder in characters.items():
        (root / "characters" / cid).symlink_to(folder.resolve(), target_is_directory=True)
    bg = root / "backgrounds" / PROBE
    (bg / "layers").mkdir(parents=True)
    Image.new("RGB", (DESIGN.width, DESIGN.height), SENTINEL).save(bg / "layers" / "probe.png")
    (bg / "layers.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": PROBE,
                "name": "Pose sweep probe",
                "size_px": [DESIGN.width, DESIGN.height],
                "backdrop": "#ff00ff",
                "layers": [{"name": "probe", "file": "layers/probe.png", "parallax": 1.0}],
            },
            indent=2,
        )
    )
    return FilmFolder(root)


def fit_scale(view: dict[str, Any]) -> float:
    _, bottom, _, top = rest_box(view)
    return round(min(3.0, max(0.2, FIGURE_FRACTION * DESIGN.height / (top - bottom))), 3)


def sweep_character(
    film: FilmFolder,
    character: str,
    *,
    views: Iterable[str] = VIEWS,
    only_motions: Iterable[str] | None = None,
    size: tuple[int, int] = SWEEP_SIZE,
    thresholds: Thresholds | None = None,
    keep_images: bool = False,
    cfg: StudioConfig | None = None,
    log: Log = quiet,
) -> SweepReport:
    """Render `character` (a rig in `film`) at the extreme poses of every motion in every view it
    has, and check each frame. The film must hold the probe background (`scratch_film`)."""
    cfg = cfg or load_config()
    th = thresholds or Thresholds()
    t0 = time.monotonic()
    report = SweepReport(character, th)
    rig = load_rig(film.rig_file(character))
    wanted = set(only_motions) if only_motions else None
    for view_name in views:
        if view_name not in rig.data["views"]:
            continue
        view = rig.view(view_name)
        scale = fit_scale(view)
        for label_, motion, params in motion_variants(view):
            if wanted and label_ not in wanted and motion not in wanted:
                continue
            action = {"motion": motion, "start_s": 0.0, "params": params}
            probe = animate(view, [action], fps=FPS, n_frames=FPS * 20)
            extremes = extreme_frames(probe.clips[0])
            if not extremes:
                log(f"{character} {view_name} {label_}: nothing moves, skipped")
                continue
            duration = math.ceil((probe.clips[0].end + 2) / FPS * 2) / 2
            create_shot(film, SHOT, max(1.0, duration), PROBE, replace=True)
            place_character(
                film, SHOT, character, list(FEET), view=view_name, scale=scale, facing="right"
            )
            add_action(film, SHOT, character, motion, 0.0, params=params)
            built = build_shot(film.root, load_shot(film.root, SHOT), fps=FPS)
            folder = film.root / "shots" / SHOT
            sif = built.canvas.save(folder / "scene.sif")
            for frame, reasons in extremes.items():
                if frame >= built.n_frames:
                    continue
                out = render_frames(
                    sif, folder / "frame", begin=frame, end=frame, size=size, cfg=cfg
                )
                img = Image.open(out[0]).convert("RGB")
                defects = [
                    Defect(**{**asdict(d), "character": character, "view": view_name,
                              "motion": label_, "frame": frame})
                    for d in check_frame(np.asarray(img), th)
                ]  # fmt: skip
                report.results.append(
                    FrameResult(view_name, label_, frame, reasons, defects, img.copy())
                    if keep_images
                    else FrameResult(view_name, label_, frame, reasons, defects)
                )
                shutil.rmtree(folder / "frame", ignore_errors=True)
            n_def = sum(
                len(r.defects) for r in report.results if r.view == view_name and r.motion == label_
            )
            log(f"{character} {view_name} {label_}: {len(extremes)} frames, {n_def} defects")
    report.seconds = time.monotonic() - t0
    return report


# --------------------------------------------------------------------------- the contact sheet


TILE = (150, 210)
KIND_COLOR = {"hole": (255, 0, 0), "seam": (255, 140, 0), "detached": (0, 90, 255)}


def contact_sheet(report: SweepReport, out: Path) -> Path:
    """One labelled image: a row per (view, motion), a tile per extreme frame, the figure on
    light grey (magenta backdrop removed) with each defect boxed (hole red, seam orange,
    detached blue). Needs the report made with keep_images=True."""
    rows: dict[tuple[str, str], list[FrameResult]] = {}
    for r in report.results:
        rows.setdefault((r.view, r.motion), []).append(r)
    label_w, label_h, gap = 190, 18, 4
    cols = max((len(v) for v in rows.values()), default=1)
    sheet = Image.new(
        "RGB",
        (label_w + cols * (TILE[0] + gap), max(1, len(rows)) * (TILE[1] + label_h + gap)),
        (250, 250, 247),
    )
    draw, small = ImageDraw.Draw(sheet), font(13)
    for y, ((view, motion), items) in enumerate(rows.items()):
        top = y * (TILE[1] + label_h + gap)
        n_def = sum(len(r.defects) for r in items)
        draw.text(
            (6, top + 6),
            f"{report.character}\n{view}\n{motion}\n{n_def} defects",
            fill=(40, 40, 60),
            font=small,
        )
        for x, r in enumerate(items):
            if r.image is None:
                continue
            arr = np.asarray(r.image).copy()
            arr[~figure_mask(arr, report.thresholds.magenta_tol)] = (232, 232, 228)
            im = Image.fromarray(arr)
            d = ImageDraw.Draw(im)
            for df in r.defects:
                x0, y0, x1, y1 = df.box
                d.rectangle((x0 - 3, y0 - 3, x1 + 3, y1 + 3), outline=KIND_COLOR[df.kind], width=2)
            ys, xs = np.nonzero(figure_mask(np.asarray(r.image), report.thresholds.magenta_tol))
            cx = int(xs.mean()) if len(xs) else im.width // 2
            cy = int(ys.mean()) if len(ys) else im.height // 2
            half_h = int(im.height * 0.5 * 0.82)  # the same zoom on every tile
            half_w = int(half_h * TILE[0] / TILE[1])
            crop = im.crop((cx - half_w, cy - half_h, cx + half_w, cy + half_h))
            crop = crop.resize(TILE, Image.LANCZOS)
            px = label_w + x * (TILE[0] + gap)
            sheet.paste(crop, (px, top))
            draw.text(
                (px + 2, top + TILE[1] + 2),
                f"f{r.frame} {len(r.defects)}d",
                fill=(40, 40, 60),
                font=small,
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
