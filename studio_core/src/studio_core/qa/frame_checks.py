"""Code checks on one rendered frame (facts, no model).

Two kinds of picture are checked:

- the **frame as shown** (`black_frame`): is anything there at all;
- one **probe frame per character**: the same shot and time rendered with only that character,
  on the flat magenta probe backdrop of the pose sweep (`preview/sweep.py`). There "not magenta"
  is figure, so a character that is missing, cropped by the frame, or has holes, seams or
  detached pieces is found by counting pixels. One character per probe keeps the sweep's
  "detached piece" rule meaningful (two characters would be two pieces).

All numbers are pixels at the 960x540 preview size.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from studio_core.preview.sweep import Thresholds, check_frame, figure_mask

BLACK_MEAN = 6.0  # mean brightness (0-255) below this is a black frame
BLACK_SHARE = 0.98  # ... and this share of pixels is near black
MIN_VISIBLE_FRAC = 0.002  # less figure than this share of the frame: the character isn't there
SLOT_ASPECT = 6.0  # a hole this much longer than wide is a slot between limbs, not a hole
# Looser than the sweep's own: a shot frame is one random pose, not a sweep of the extremes.
QA_THRESHOLDS = replace(Thresholds(), seam_min_px=40)
EDGE_RUN_PX = 6  # this many figure pixels along a frame edge = cropped by that edge


@dataclass(frozen=True)
class Finding:
    """A fact found in the frame by code."""

    kind: str  # black_frame | missing | cropped | hole | seam | detached
    detail: str
    character: str = ""


def black_frame(rgb: np.ndarray) -> list[Finding]:
    dark = rgb.max(axis=2) < 16
    if rgb.mean() < BLACK_MEAN and dark.mean() >= BLACK_SHARE:
        return [Finding("black_frame", "the frame is (almost) all black")]
    return []


def edges_touched(fg: np.ndarray) -> list[str]:
    """Which frame edges the figure touches along a run of at least EDGE_RUN_PX pixels."""
    sides = {"left": fg[:, 0], "right": fg[:, -1], "top": fg[0, :], "bottom": fg[-1, :]}
    return [name for name, line in sides.items() if int(line.sum()) >= EDGE_RUN_PX]


def probe_findings(
    character: str, rgb: np.ndarray, thresholds: Thresholds | None = None
) -> list[Finding]:
    """Findings for one character rendered alone on the magenta backdrop."""
    th = thresholds or QA_THRESHOLDS
    fg = figure_mask(rgb, th.magenta_tol)
    share = float(fg.mean())
    if share < MIN_VISIBLE_FRAC:
        return [
            Finding(
                "missing",
                f"{character} is not visible: {share:.2%} of the frame is figure "
                "(off screen, hidden, or scaled to nothing)",
                character,
            )
        ]
    found: list[Finding] = []
    if edges := edges_touched(fg):
        found.append(
            Finding(
                "cropped",
                f"{character} is cut off by the {' and '.join(edges)} edge of the frame",
                character,
            )
        )
    for d in check_frame(rgb, th):
        x0, y0, x1, y1 = d.box
        w, h = x1 - x0, y1 - y0
        if d.kind == "hole" and max(w, h) >= SLOT_ASPECT * min(w, h):
            continue
        found.append(
            Finding(d.kind, f"{character}: {d.kind} of {d.area_px} px at {d.center}", character)
        )
    return found
