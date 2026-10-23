"""Can characters stand in front of this background? Cheap pixel checks (task 4.6, D-054).

    report = check_plate(image)       # a 1536x576 draft or a 2880x1080 plate
    report.ok, report.problems

Characters stand with their feet near the bottom of the frame (shot positions use y ≈ 0.92)
and fill most of its height, so a background's **ground band**, the rows where their feet
go, has to be open ground: grass, a path, sand. Not a wall of rocks, a fence, a pond
across the whole front, or a tree trunk.

- **Busy ground:** the share of strong edges in the band. Grass texture and a path's edges
  stay under the limit; outlined objects (rocks, flowers drawn big, fences) go over it.
- **Blocked ground:** the share of the band whose colour is far from the band's own main
  colours: big flowers, rocks or a stream standing out from the ground. (Water filling the
  whole band would itself be the main colour: telling it from a field needs a vision check.)
- **Depth:** the top and the bottom of the picture differ (sky or far scenery above, ground
  below), which the depth layers (task 4.7) need.

No model is used, so "no people or animals" is the prompt's job, and the owner's eye's (a
vision check can come later, sequenced, D-018).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter

GROUND_BAND = (0.78, 0.97)  # rows (share of the height) where characters' feet go
EDGE_LIMIT = 0.10  # max share of edge pixels in the band
BLOCK_LIMIT = 0.2  # max share of the band far from its main colours
EDGE_STRENGTH = 20.0  # gradient magnitude (luma, 0-255) that counts as an edge: SDXL paints
# softly, so outlines of flowers and rocks are around 20-40, grass texture below
FAR_COLOUR = 70.0  # RGB distance from every main colour that counts as "another object"
MIN_DEPTH = 30.0  # min RGB distance between the top band's and the bottom band's mean colours


@dataclass
class PlateCheck:
    ground_edges: float  # share of strong edges in the ground band
    ground_blocked: float  # share of the ground band far from its main colours
    depth_contrast: float  # RGB distance between the top and bottom bands' mean colours
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _edges(img: np.ndarray) -> np.ndarray:
    """Gradient magnitude of a slightly blurred luma image (texture finer than ~2 px is
    smoothed away, so paper grain and grass stippling don't count as objects)."""
    luma = Image.fromarray((img @ np.array([0.299, 0.587, 0.114])).clip(0, 255).astype("uint8"))
    smooth = np.asarray(luma.filter(ImageFilter.GaussianBlur(1.5)), dtype="float32")
    gy, gx = np.gradient(smooth)
    return np.hypot(gx, gy) * 2  # central differences span 2 px


def _main_colours(pixels: np.ndarray, k: int = 4) -> np.ndarray:
    strip = Image.fromarray(pixels.reshape(1, -1, 3).astype("uint8"))
    q = strip.quantize(k, method=Image.Quantize.MEDIANCUT)
    counts = np.bincount(np.asarray(q).ravel(), minlength=k)
    flat = q.getpalette()
    keep = [i for i, c in enumerate(counts) if c >= 0.1 * len(pixels)]  # the main ones only
    return np.array([flat[3 * i : 3 * i + 3] for i in keep], dtype="float32")


def check_plate(image: Image.Image) -> PlateCheck:
    img = np.asarray(image.convert("RGB")).astype("float32")
    h = img.shape[0]
    top, bottom = int(GROUND_BAND[0] * h), int(GROUND_BAND[1] * h)
    band = img[top:bottom]
    edges = float((_edges(img)[top:bottom] > EDGE_STRENGTH).mean())
    pixels = band.reshape(-1, 3)
    colours = _main_colours(pixels)
    nearest = np.min([np.linalg.norm(pixels - c, axis=1) for c in colours], axis=0)
    blocked = float((nearest > FAR_COLOUR).mean())
    depth = float(np.linalg.norm(img[: h // 5].mean(axis=(0, 1)) - band.mean(axis=(0, 1))))
    report = PlateCheck(round(edges, 3), round(blocked, 3), round(depth, 1))
    if edges > EDGE_LIMIT:
        report.problems.append(
            f"the ground where characters stand is busy ({edges:.0%} edges; keep it open)"
        )
    if blocked > BLOCK_LIMIT:
        report.problems.append(
            f"something covers {blocked:.0%} of the ground where characters stand"
        )
    if depth < MIN_DEPTH:
        report.problems.append("the top and the bottom look alike (no sky or distance above)")
    return report
