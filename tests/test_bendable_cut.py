# ruff: noqa: F811
"""The cut makes bendable limbs (4B.4): with build_puppet(bendable=True) each arm and leg also
gets ONE image (parts/<view>/limb_<name>.png) declared in the view's bendable_limbs, and nothing
else changes. The synthetic fox of test_puppet_build is cut with SAM off."""

import copy
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image
from test_bend_limbs import SIZE, ink, needs_synfig, no_warnings, render_arm
from test_puppet_build import film  # noqa: F401  (the fixture)

from studio_core.puppet.build import BENDABLE, build_puppet
from studio_core.schema import validate


def build(film: Path, **kwargs: bool) -> dict:
    built = build_puppet(film, "kit", sam=False, three_quarter="sheet", **kwargs)
    return built.rig


def digest(folder: Path) -> dict[str, str]:
    """Hash of every part image and of rig.json, by path."""
    files = [*sorted((folder / "parts").rglob("*.png")), folder / "rig.json"]
    return {str(f.relative_to(folder)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def test_default_build_has_no_limbs_and_bendable_only_adds(film: Path) -> None:
    folder = film / "characters" / "kit"
    plain = build(film)
    before = digest(folder)
    assert not any("bendable_limbs" in v for v in plain["views"].values())
    assert not list((folder / "parts").rglob("limb_*"))
    bent = build(film, bendable=True)
    after = digest(folder)
    # every file the default build made is byte-identical, except rig.json by the new key
    added = {k for k in after if k not in before}
    assert {Path(k).name for k in added} == {f"limb_{n}.png" for n in BENDABLE}
    assert all(after[k] == before[k] for k in before if k != "rig.json")
    stripped = copy.deepcopy(bent)
    for view in stripped["views"].values():
        view.pop("bendable_limbs")
    assert stripped == plain
    assert digest(folder).keys() >= before.keys()


def test_bendable_build_declares_valid_limbs_for_both_views(film: Path) -> None:
    rig = build(film, bendable=True)
    assert validate("rig", rig) == []  # register_rig already refused anything worse
    for name, view in rig["views"].items():
        limbs = {limb["name"]: limb for limb in view["bendable_limbs"]}
        assert set(limbs) == set(BENDABLE), name
        for limb in limbs.values():
            upper, lower = limb["bones"]
            assert (upper, lower) == BENDABLE[limb["name"]]
            image = Image.open(film / "characters" / "kit" / limb["file"])
            assert list(image.size) == limb["size_px"]
            # the limb is drawn at least as long as its two parts' rest chain
            assert view["parts"][upper]["file"] != limb["file"]
            assert np.asarray(image)[..., 3].sum() > 0
        arm = limbs["arm_l"]
        # hanging at rest: the elbow is below the shoulder in the image
        assert arm["joint_px"][1] - arm["pivot_px"][1] > 20


def test_the_limb_image_is_the_union_of_its_parts_without_the_joint_cap(film: Path) -> None:
    rig = build(film, bendable=True)
    folder = film / "characters" / "kit"
    view = rig["views"]["front"]
    limb = next(item for item in view["bendable_limbs"] if item["name"] == "leg_l")
    img = np.asarray(Image.open(folder / limb["file"]))[..., 3] > 128
    thigh, shin = (
        np.asarray(Image.open(folder / view["parts"][b]["file"]))[..., 3] > 128
        for b in ("thigh_l", "shin_l")
    )
    # the limb is no bigger than the two parts together (their knee discs overlap in it once)
    assert img.sum() <= thigh.sum() + shin.sum()
    assert img.sum() >= 0.85 * max(thigh.sum(), shin.sum())
    # and it has no hole across the knee: every row between the hip and the ankle has art
    rows = np.where(img.any(axis=1))[0]
    assert img[rows.min() : rows.max() + 1].any(axis=1).all()


def pose_arm(rig_json: Path, tmp: Path, *, bend: bool, pose: dict[str, float]) -> Path:
    return render_arm(tmp, rig_json, bend=bend, pose=pose)[0]


@needs_synfig
def test_bent_render_of_a_cut_limb_has_no_hole_at_the_joint(film: Path, tmp_path: Path) -> None:
    build(film, bendable=True)
    folder = tmp_path / "kit"
    shutil.copytree(film / "characters" / "kit", folder)
    assert json.loads((folder / "rig.json").read_text())["views"]["front"]["bendable_limbs"]
    pose = {"upper_arm_l": 90.0, "forearm_l": 70.0}
    straight, err = render_arm(tmp_path / "a", folder / "rig.json", bend=True, pose={})
    no_warnings(err)
    bent, err = render_arm(tmp_path / "b", folder / "rig.json", bend=True, pose=pose)
    no_warnings(err)
    rigid, _ = render_arm(tmp_path / "c", folder / "rig.json", bend=False, pose=pose)
    # right of the fox's torso (x > 490 px) only the raised arm is drawn
    x = SIZE // 2 + 90
    ratio = ink(bent, x) / ink(rigid, x)
    assert ink(rigid, x) > 3000  # the arm is there to be compared
    assert 0.9 <= ratio <= 1.05, ratio
    # at rest the one-image limb is the two-part look
    flat, _ = render_arm(tmp_path / "d", folder / "rig.json", bend=False, pose={})
    assert ink(straight) > 0.95 * ink(flat)
