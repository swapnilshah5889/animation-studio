"""Cheap automatic checks on a generated design sheet (task 4.3, D-047).

    report = check_sheet(image, [front, three_quarter])
    report.ok, report.problems

A candidate becomes a puppet only if it can be cut cleanly, which pixel geometry can judge
without any model:

- **Plain background:** the sheet's border pixels agree on one colour, which also gives the
  colour key for the silhouette.
- **One figure per view:** the silhouette's pieces are grouped by the skeleton they sit on
  (light clothes on a light background can split one figure into pieces; those still count as
  the figure). A piece on no skeleton is an extra shape: a prop, a second character, a
  signature, scattered leaves.
- **Scale:** the silhouette is about as tall as the skeleton that steered it.
- **On the skeleton:** the skeleton's joints fall inside the silhouette. If SDXL ignored the pose,
  the joints land on background. This is the "pose drift" measure.
- **Limbs clear** (front view): between each hand and the hip on that side there is
  background, so the arm can be cut away from the torso.

Faces aren't checked here (no model): the owner looks, and the build step paints the face area
over anyway (D-047). The colour key is only a check: clothes close to the background colour
read as background, so the real cut (task 4.4) uses SAM 2.1.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter

from studio_core.puppet.skeleton import OPENPOSE, Skeleton

BG_TOLERANCE = 30.0  # RGB distance still counted as background
FG_THRESHOLD = 45.0  # RGB distance from the background that counts as figure
SCALE = 4  # components are found on a 1/4-size mask (fast, plenty for figure-sized blobs)
MIN_SHAPE = 0.0005  # share of the image; smaller pieces are specks (about 23x23 px at 1344x768)


@dataclass
class FigureCheck:
    view: str
    found: bool
    height_ratio: float = 0.0  # silhouette height / skeleton height
    joints_inside: float = 0.0  # share of skeleton joints on the silhouette
    joints_off: list[str] = field(default_factory=list)  # the joints that missed it
    limbs_clear: bool | None = None  # front view only


@dataclass
class SheetCheck:
    background_plain: float  # share of border pixels within BG_TOLERANCE of the background
    background_rgb: tuple[int, int, int]
    figures: list[FigureCheck] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def background(img: np.ndarray) -> tuple[np.ndarray, float]:
    """Median border colour, and the share of border pixels close to it."""
    h, w, _ = img.shape
    m = max(2, int(min(h, w) * 0.02))
    border = np.concatenate(
        [img[:m].reshape(-1, 3), img[-m:].reshape(-1, 3), img[:, :m].reshape(-1, 3),
         img[:, -m:].reshape(-1, 3)]
    )  # fmt: skip
    bg = np.median(border, axis=0)
    close = np.linalg.norm(border - bg, axis=1) < BG_TOLERANCE
    return bg, float(close.mean())


def silhouette(img: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """Figure mask: far enough from the background colour, small specks and holes cleaned."""
    mask = np.linalg.norm(img - bg, axis=2) > FG_THRESHOLD
    pil = Image.fromarray((mask * 255).astype("uint8"))
    pil = pil.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))  # close holes
    pil = pil.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))  # drop specks
    return np.asarray(pil) > 127


def components(mask: np.ndarray) -> list[np.ndarray]:
    """Connected components (4-neighbour) of a boolean mask, largest first, as boolean masks."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    sizes = []
    for y0, x0 in zip(*np.nonzero(mask), strict=True):
        if labels[y0, x0]:
            continue
        label = len(sizes) + 1
        labels[y0, x0] = label
        queue, size = deque([(y0, x0)]), 0
        while queue:
            y, x = queue.popleft()
            size += 1
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = label
                    queue.append((ny, nx))
        sizes.append(size)
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i])
    return [labels == i + 1 for i in order]


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """The mask plus every region the border can't reach: a white shirt inside a dark outline
    is figure, not background."""
    outside = np.zeros_like(mask)
    for region in components(~mask):
        if region[0].any() or region[-1].any() or region[:, 0].any() or region[:, -1].any():
            outside |= region
    return ~outside


def _near(mask: np.ndarray, point: tuple[float, float], reach: int) -> bool:
    """Any mask pixel within `reach` (a square window) of the point."""
    x, y = int(point[0]), int(point[1])
    return bool(mask[max(0, y - reach) : y + reach + 1, max(0, x - reach) : x + reach + 1].any())


def _limbs_clear(mask: np.ndarray, sk: Skeleton) -> bool:
    """Background somewhere on the middle of the line from each wrist to the hip below it."""
    for side in ("l", "r"):
        (wx, wy), (hx, hy) = sk.joints[f"{side}_wrist"], sk.joints[f"{side}_hip"]
        gap = False
        for t in np.linspace(0.25, 0.75, 40):
            x, y = round(wx + (hx - wx) * t), round(wy + (hy - wy) * t)
            if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and not mask[y, x]:
                gap = True
                break
        if not gap:
            return False
    return True


def skeleton_box(sk: Skeleton, margin: float) -> tuple[float, float, float, float]:
    xs = [x for x, _ in sk.joints.values()]
    ys = [y for _, y in sk.joints.values()]
    pad = sk.height_px * margin
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def check_sheet(image: Image.Image, skeletons: list[Skeleton]) -> SheetCheck:
    img = np.asarray(image.convert("RGB")).astype("float32")
    bg, plain = background(img)
    report = SheetCheck(plain, tuple(int(c) for c in bg))
    if plain < 0.9:
        report.problems.append(f"the background isn't plain ({plain:.0%} of the border matches)")
    mask = silhouette(img, bg)
    small = fill_holes(mask[::SCALE, ::SCALE])
    h, w = mask.shape
    mask |= np.repeat(np.repeat(small, SCALE, axis=0), SCALE, axis=1)[:h, :w]
    blobs = [b for b in components(small) if b.sum() * SCALE * SCALE > MIN_SHAPE * mask.size]
    centres = [(xs.mean() * SCALE, ys.mean() * SCALE) for ys, xs in map(np.nonzero, blobs)]
    claimed: set[int] = set()
    for sk in skeletons:
        check = FigureCheck(sk.view, found=False)
        report.figures.append(check)
        x0, y0, x1, y1 = skeleton_box(sk, 0.15)
        mine = [i for i, (cx, cy) in enumerate(centres) if x0 <= cx <= x1 and y0 <= cy <= y1]
        claimed.update(mine)
        if not mine:
            report.problems.append(f"{sk.view}: no figure where the skeleton is")
            continue
        pieces = np.any([blobs[i] for i in mine], axis=0)
        grown = np.repeat(np.repeat(pieces, SCALE, axis=0), SCALE, axis=1)
        figure = np.zeros_like(mask)
        figure[: grown.shape[0], : grown.shape[1]] = grown[: mask.shape[0], : mask.shape[1]]
        figure &= mask
        ys = np.nonzero(figure.any(axis=1))[0]
        check.found = True
        check.height_ratio = round(float((ys[-1] - ys[0]) / sk.height_px), 3)
        names = [n for n in OPENPOSE if n not in sk.hidden and "ear" not in n]
        reach = max(1, int(sk.height_px * 0.015))  # a joint just off the edge still counts
        check.joints_off = [n for n in names if not _near(figure, sk.joints[n], reach)]
        check.joints_inside = round(1 - len(check.joints_off) / len(names), 3)
        if sk.view == "front":
            check.limbs_clear = _limbs_clear(figure, sk)
            if not check.limbs_clear:
                report.problems.append(
                    "front: an arm or hand touches the body or tail (it can't be cut free)"
                )
        if not 0.8 <= check.height_ratio <= 1.15:
            report.problems.append(
                f"{sk.view}: figure height is {check.height_ratio:.0%} of the pose"
            )
        if check.joints_inside < 0.85:
            report.problems.append(
                f"{sk.view}: only {check.joints_inside:.0%} of the joints are on the figure "
                f"(the pose wasn't followed; off: {', '.join(check.joints_off)})"
            )
    extra = [i for i in range(len(blobs)) if i not in claimed]
    if extra:
        report.problems.append(
            f"{len(extra)} extra shape(s) away from the figures (props, text, shadows or clutter)"
        )
    return report
