"""The Kenney cast rig (D-100): a valid rig, variants share one canvas, mirrored limbs."""

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("cairosvg", reason="needs cairosvg (and Homebrew cairo) to re-render the SVG")
SRC = Path(os.path.expanduser("~/ai-studio/assets/kenney-toon-characters-1/src/Female person"))
pytestmark = pytest.mark.skipif(not SRC.exists(), reason="Kenney assets not downloaded")

from PIL import Image  # noqa: E402

from studio_core.puppet.kenney import build_kenney_puppet  # noqa: E402
from studio_core.rig import load_rig, world_pose  # noqa: E402


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("kit")
    build_kenney_puppet(SRC, d, px_per_unit=4, name="kit")
    return d


def test_rig_loads_with_the_expected_bones_and_roles(built):
    view = load_rig(built / "rig.json").view("front")
    roles = {b: sp["role"] for b, sp in view["bones"].items()}
    assert roles["torso"] == "torso" and roles["head"] == "head"
    assert {roles[b] for b in view["bones"]} >= {"upper_arm", "forearm", "thigh"}
    assert view["draw_order"][-1] == "head"  # the head is drawn last, over the collar


def test_variants_share_the_canvas_of_their_part_so_a_swap_never_stretches(built):
    view = load_rig(built / "rig.json").view("front")
    variants = json.loads((built / "variants.json").read_text())
    for variant, part in (("legBend", "thigh_l"), ("headFocus", "head"), ("headShock", "head")):
        assert Image.open(built / variants[variant]).size == tuple(view["parts"][part]["size_px"])
    assert Image.open(built / variants["legBend_mirror"]).size == tuple(
        view["parts"]["thigh_r"]["size_px"]
    )


def test_limbs_are_mirrored_about_the_centre_line(built):
    view = load_rig(built / "rig.json").view("front")
    pose = world_pose(view)
    for a, b in (("upper_arm_l", "upper_arm_r"), ("thigh_l", "thigh_r"), ("hand_l", "hand_r")):
        assert pose[a][0].x == pytest.approx(-pose[b][0].x, abs=1.0)
        assert pose[a][0].y == pytest.approx(pose[b][0].y, abs=1.0)


def test_the_feet_define_the_ground_and_the_head_is_above_the_body(built):
    view = load_rig(built / "rig.json").view("front")
    pose = world_pose(view)
    assert pose["head"][0].y > pose["upper_arm_l"][0].y > pose["thigh_l"][0].y
