"""Bending limbs (4B.4): the schema, the Skeleton Deformation layer, the rig build and a render.

The render tests use Pip's left arm as ONE hand-made image (tests/fixtures/handmade/pip_arm_l.png:
his upper arm and forearm composited straight) declared as a bendable limb."""

import copy
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from studio_core.config import REPO_ROOT, load_config
from studio_core.rig import RigError, build_character, load_rig
from studio_core.schema import validate
from studio_core.sif import (
    Angle,
    Bone,
    Canvas,
    Color,
    Group,
    ImportLayer,
    SkeletonDeformation,
    Space,
    Vec,
)
from studio_core.sif.validate import validate_sif

PIP_DIR = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip"
ARM = REPO_ROOT / "tests" / "fixtures" / "handmade" / "pip_arm_l.png"
LIMB = {
    "name": "arm_l",
    "bones": ["upper_arm_l", "forearm_l"],
    "file": "parts/arm_l.png",
    "size_px": [56, 264],
    "pivot_px": [28, 20],  # the shoulder, as in the upper arm part
    "joint_px": [28, 132],  # the elbow: the forearm's attach point in the upper arm part
}
needs_synfig = pytest.mark.skipif(
    not load_config().path("tools", "synfig").exists(), reason="no synfig CLI"
)


def pip_with_arm(folder: Path, limb: dict | None = LIMB) -> Path:
    """A copy of Pip's folder whose rig declares the one-image left arm."""
    shutil.copytree(PIP_DIR, folder)
    shutil.copy(ARM, folder / "parts" / "arm_l.png")
    data = json.loads((folder / "rig.json").read_text())
    if limb:
        data["views"]["front"]["bendable_limbs"] = [limb]
    (folder / "rig.json").write_text(json.dumps(data))
    return folder / "rig.json"


# ------------------------------------------------------------------------------- the schema


def rig_data(**limb_changes: object) -> dict:
    data = json.loads((PIP_DIR / "rig.json").read_text())
    data["views"]["front"]["bendable_limbs"] = [{**LIMB, **limb_changes}]
    return data


def messages(data: dict) -> str:
    return "; ".join(str(i) for i in validate("rig", data))


def test_a_valid_limb_passes_and_pip_without_limbs_still_does() -> None:
    assert validate("rig", rig_data()) == []
    assert validate("rig", json.loads((PIP_DIR / "rig.json").read_text())) == []


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"bones": ["upper_arm_l", "thigh_l"]}, "must be a child of 'upper_arm_l'"),
        ({"bones": ["forearm_l", "upper_arm_l"]}, "must be a child of 'forearm_l'"),
        ({"bones": ["upper_arm_l", "nope"]}, "unknown bone 'nope'"),
        ({"joint_px": [28, 300]}, "outside the limb image"),
        ({"pivot_px": [28, -1]}, "outside the limb image"),
        ({"joint_px": [28, 180]}, "the joint is"),  # not where the rig's elbow is
        ({"file": "parts/arm.jpg"}, "does not match"),
    ],
)
def test_bad_limbs_are_refused_with_the_reason(change: dict, text: str) -> None:
    assert text in messages(rig_data(**change))


def test_a_bone_may_be_in_one_limb_only_and_names_are_unique() -> None:
    data = rig_data()
    data["views"]["front"]["bendable_limbs"].append(copy.deepcopy(LIMB))
    text = messages(data)
    assert "appears twice" in text and "already in limb 'arm_l'" in text


def test_a_missing_limb_image_is_refused_on_load(tmp_path: Path) -> None:
    rig_json = pip_with_arm(tmp_path / "pip")
    (rig_json.parent / "parts" / "arm_l.png").unlink()
    with pytest.raises(RigError, match=r"part files not found: \['parts/arm_l.png'\]"):
        load_rig(rig_json)


# ------------------------------------------------------------------- the layer and the XML


def deformation_canvas() -> Canvas:
    rest_up = Bone("rest_up", origin=Vec(0, 2), angle=Angle(-90), length=1, width=0.4)
    rest_lo = Bone("rest_lo", parent=rest_up, origin=Vec(1, 0), length=1, width=0.4)
    pose_up = Bone("up", origin=Vec(0, 2), angle=Angle(-90), length=1)
    pose_lo = Bone("lo", parent=pose_up, origin=Vec(1, 0), angle=Angle(60), length=1)
    deform = SkeletonDeformation(
        "bend",
        pairs=[(rest_up, pose_up), (rest_lo, pose_lo)],
        point1=Vec(-1, 3),
        point2=Vec(1, 0),
    )
    c = Canvas(width=64, height=64, fps=24, frames=1, ppu=20)
    c.bones = [rest_up, rest_lo, pose_up, pose_lo]
    c.layers = [Group("limb", children=[ImportLayer("arm", file="arm.png"), deform])]
    return c


def test_deformation_xml_golden() -> None:
    c = deformation_canvas()
    deform = ET.tostring(c.layers[0].children[1].to_xml(), encoding="unicode")  # type: ignore[attr-defined]
    guids = [b.guid for b in c.bones]
    pair = (
        '<entry><composite type="pair_bone_object_bone_object">'
        '<first><bone type="bone_object" guid="{}" /></first>'
        '<second><bone type="bone_object" guid="{}" /></second></composite></entry>'
    )
    assert deform == (
        '<layer type="skeleton_deformation" active="true" exclude_from_rendering="false" '
        'version="0.2" desc="bend"><param name="bones">'
        '<static_list type="pair_bone_object_bone_object">'
        + pair.format(guids[0], guids[2])
        + pair.format(guids[1], guids[3])
        + "</static_list></param>"
        '<param name="point1"><vector><x>-1.000000</x><y>3.000000</y></vector></param>'
        '<param name="point2"><vector><x>1.000000</x><y>0.000000</y></vector></param>'
        '<param name="x_subdivisions"><integer value="48" /></param>'
        '<param name="y_subdivisions"><integer value="192" /></param></layer>'
    )


def test_bone_width_is_written_only_when_set() -> None:
    wide = ET.tostring(Bone("a", width=0.5).to_xml(), encoding="unicode")
    plain = ET.tostring(Bone("a").to_xml(), encoding="unicode")
    assert '<width><real value="0.500000" /></width><tipwidth>' in wide
    assert "width" not in plain


def test_validator_knows_the_deformation_layer(tmp_path: Path) -> None:
    (tmp_path / "arm.png").write_bytes(ARM.read_bytes())
    good = deformation_canvas().save(tmp_path / "good.sif")
    assert validate_sif(good) == []

    # a rest bone without width: everything outside it would vanish
    c = deformation_canvas()
    c.bones[0].width = None
    issues = validate_sif(c.save(tmp_path / "nowidth.sif"))
    assert any("rest bone" in i and "width" in i for i in issues), issues

    # a pair that refers to a bone that is not in <bones>
    c = deformation_canvas()
    c.bones.pop()
    issues = validate_sif(c.save(tmp_path / "unknown.sif"))
    assert any("undefined bone" in i for i in issues), issues

    # nothing below it to bend
    c = deformation_canvas()
    group = c.layers[0]
    group.children.reverse()  # type: ignore[attr-defined]
    assert any("first layer" in i for i in validate_sif(c.save(tmp_path / "first.sif")))


# ------------------------------------------------------------------------- the rig build


def test_a_character_without_limbs_builds_the_same_with_or_without_bend() -> None:
    rig = load_rig(PIP_DIR / "rig.json")
    space = Space(1920, 1080, 120)
    on = build_character(rig, "front", space, file_prefix="p", bend=True)
    off = build_character(rig, "front", space, file_prefix="p", bend=False)
    canvas = lambda b: Canvas(  # noqa: E731
        width=1920, height=1080, fps=24, frames=1, ppu=120, layers=[b.group], bones=b.bones
    ).to_string()
    assert canvas(on) == canvas(off)
    assert "skeleton_deformation" not in canvas(on) and "<width>" not in canvas(on)


def test_limb_replaces_its_parts_and_bend_false_is_the_two_part_build(tmp_path: Path) -> None:
    rig = load_rig(pip_with_arm(tmp_path / "pip"))
    plain = load_rig(PIP_DIR / "rig.json")
    space = Space(1920, 1080, 120)
    built = build_character(rig, "front", space, file_prefix="p")
    names = [layer.desc for layer in built.group.children]  # type: ignore[attr-defined]
    # the limb takes the first of its parts' draw slots; neither arm part is drawn
    assert names.index("arm_l") == names.index("forearm_r") + 1  # where upper_arm_l was
    assert "upper_arm_l" not in names and "forearm_l" not in names
    assert "forearm_r" in names  # the other arm is untouched
    assert len(built.bones) == 10 + 2  # the rest chain rides along for the canvas skeleton
    off = build_character(rig, "front", space, file_prefix="p", bend=False)
    ref = build_character(plain, "front", space, file_prefix="p")
    as_xml = lambda b: Canvas(  # noqa: E731
        width=1920, height=1080, fps=24, frames=1, ppu=120, layers=[b.group], bones=b.bones
    ).to_string()
    assert as_xml(off) == as_xml(ref)


# ------------------------------------------------------------------------------- rendering

SIZE = 800
SPACE = Space(SIZE, SIZE, 1)  # 1 px per unit: art pixels map 1:1 to canvas pixels


def render_arm(
    tmp: Path, rig_json: Path, *, bend: bool, pose: dict[str, float]
) -> tuple[Path, str]:
    rig = load_rig(rig_json)
    built = build_character(rig, "front", SPACE, file_prefix="pip", offsets=dict(pose), bend=bend)
    canvas = Canvas(
        width=SIZE,
        height=SIZE,
        fps=24,
        frames=1,
        ppu=1,
        bgcolor=Color(1, 1, 1),
        layers=[Group("place", children=[built.group])],
        bones=built.bones,
    )
    folder = tmp / ("bent" if bend else "rigid")
    folder.mkdir(parents=True)
    (folder / "pip").symlink_to(rig_json.parent)
    sif = canvas.save(folder / "t.sif")
    assert validate_sif(sif) == []
    out = folder / "frame.png"
    synfig = str(load_config().path("tools", "synfig"))
    proc = subprocess.run(
        [synfig, str(sif), "-t", "png", "-o", str(out)], capture_output=True, text=True, cwd=folder
    )
    assert proc.returncode == 0, proc.stderr
    return out, proc.stderr


def ink(png: Path, x_from: int = 0) -> int:
    """Pixels that are not the white background, right of column x_from."""
    img = Image.open(png).convert("RGB").crop((x_from, 0, SIZE, SIZE))
    diff = ImageChops.difference(img, Image.new("RGB", img.size, (255, 255, 255)))
    return sum(diff.convert("L").point(lambda v: 255 if v > 12 else 0).histogram()[255:])


def no_warnings(stderr: str) -> None:
    bad = [ln for ln in stderr.splitlines() if "warning" in ln.lower() or "error" in ln.lower()]
    bad = [ln for ln in bad if "jpeg" not in ln.lower()]  # the known missing-JPEG-module notice
    assert bad == [], bad


@needs_synfig
def test_at_rest_the_one_image_arm_matches_the_two_part_arm(tmp_path: Path) -> None:
    rig_json = pip_with_arm(tmp_path / "pip")
    bent, err = render_arm(tmp_path, rig_json, bend=True, pose={})
    rigid, _ = render_arm(tmp_path, rig_json, bend=False, pose={})
    no_warnings(err)
    a, b = Image.open(bent).convert("RGB"), Image.open(rigid).convert("RGB")
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 80 else 0)
    wrong = sum(diff.histogram()[255:])
    assert wrong < 0.03 * ink(rigid), (wrong, ink(rigid))  # edge pixels only
    assert ink(bent) > 0.97 * ink(rigid)


@needs_synfig
def test_bent_70_degrees_renders_clean_and_the_elbow_curves_not_shrinks(tmp_path: Path) -> None:
    rig_json = pip_with_arm(tmp_path / "pip")
    # the arm raised to point away from the torso, the elbow bent 70 degrees
    pose = {"upper_arm_l": 90.0, "forearm_l": 70.0}
    bent, err = render_arm(tmp_path, rig_json, bend=True, pose=pose)
    rigid, _ = render_arm(tmp_path, rig_json, bend=False, pose=pose)
    no_warnings(err)
    # count only right of the torso (x > 115 px from the centre), where just the arm is drawn
    ratio = ink(bent, SIZE // 2 + 115) / ink(rigid, SIZE // 2 + 115)
    assert 0.9 <= ratio <= 1.05, ratio
    # ...but it is a different picture: the outer edge of the elbow is curved, not a corner
    a, b = Image.open(bent).convert("RGB"), Image.open(rigid).convert("RGB")
    assert ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 80 else 0).getbbox()
