"""Render the hand-written bone examples and check them against forward kinematics."""

import math
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from studio_core.config import REPO_ROOT, load_config
from studio_core.sif.render import render_frames

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(not load_config().path("tools", "synfig").exists(), reason="no synfig CLI"),
]
EXAMPLES = REPO_ROOT / "tests" / "fixtures" / "sif_examples"

# bones_arm_minimal.sif: shoulder at (-3, 1), upper bone length 3, angles per frame
# (upper, forearm relative to upper). The white marker sits at forearm-local x = 2.6.
SHOULDER, UPPER_LEN, MARKER_X = (-3.0, 1.0), 3.0, 2.6
KEYS = {0: (-20, 0), 12: (10, 70), 24: (-60, -40)}


def predicted_marker_px(frame: int) -> tuple[float, float]:
    a1, a2 = (math.radians(a) for a in KEYS[frame])
    ex = SHOULDER[0] + UPPER_LEN * math.cos(a1)
    ey = SHOULDER[1] + UPPER_LEN * math.sin(a1)
    wx, wy = ex + MARKER_X * math.cos(a1 + a2), ey + MARKER_X * math.sin(a1 + a2)
    return (wx + 8) * 40, (4.5 - wy) * 40  # 640x360 canvas, view-box -8..8 x 4.5..-4.5


def white_centroid(path: Path) -> tuple[float, float]:
    im = Image.open(path).convert("RGB")
    pts = [
        (x, y) for y in range(im.height) for x in range(im.width) if min(im.getpixel((x, y))) > 250
    ]
    assert pts, f"no white marker in {path.name}"
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def test_bone_rig_matches_forward_kinematics(tmp_path: Path) -> None:
    frames = render_frames(EXAMPLES / "bones_arm_minimal.sif", tmp_path / "f")
    assert len(frames) == 48
    for frame in KEYS:
        mx, my = white_centroid(frames[frame])
        px, py = predicted_marker_px(frame)
        assert abs(mx - px) < 1.5 and abs(my - py) < 1.5, (frame, (mx, my), (px, py))


def test_skeleton_deformation_renders(tmp_path: Path) -> None:
    frames = render_frames(EXAMPLES / "deform_limb.sif", tmp_path / "f")
    assert len(frames) == 48
    # The bent pose (frame 12) differs from the straight rest pose (frame 0).
    a, b = Image.open(frames[0]).convert("RGB"), Image.open(frames[12]).convert("RGB")
    assert ImageChops.difference(a, b).getbbox() is not None
