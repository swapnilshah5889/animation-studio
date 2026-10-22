"""Building a puppet from a design sheet (task 4.4), on a synthetic character drawn on the
skeleton: a scarf across the neck, a tail behind one leg, trousers, paws, and a face. Every
rule of the cut is checked where it shows: the scarf stays on the torso, the tail doesn't
follow the leg, the face is painted out but the nose stays, the arms hang at rest, and
turning the arms back reproduces the sheet. SAM is faked (no GPU)."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.puppet import build
from studio_core.puppet.build import (
    BuildError,
    assign_parts,
    build_puppet,
    clean_face,
    compose,
    figure_mask,
    head_mask,
    limb_fit,
)
from studio_core.puppet.design import CANVAS
from studio_core.puppet.skeleton import Skeleton, rig_bones, turnaround
from studio_core.schema import validate_file

FRONT, SIDE = turnaround(CANVAS)
BG = (250, 250, 248)
FUR, CREAM, SCARF = (230, 120, 40), (245, 225, 190), (60, 160, 70)
PANTS, DARK = (70, 90, 170), (40, 30, 30)


def face_points(sk: Skeleton) -> dict[str, tuple[float, float]]:
    (nx, ny), (_, ty) = sk.joints["neck"], sk.joints["head_top"]
    r = (ny - ty) / 2
    eye_y, nose = sk.joints["r_eye"][1], sk.joints["nose"]
    return {
        "eye_l": (nx + 0.3 * r, eye_y),  # the character's left: screen-right
        "eye_r": (nx - 0.3 * r, eye_y),
        "nose": nose,
        "mouth": (nx, nose[1] + 0.2 * r),
        "scarf": (sk.joints["l_shoulder"][0] - 12, ny + 8),
        "tail": (sk.joints["pelvis"][0] - 120, sk.joints["pelvis"][1] + 125),
        # on the tail beside the right thigh: inside the thigh's corridor, not under the leg
        "tail_on_thigh": (
            0.8 * (sk.joints["r_knee"][0] - 4) + 0.2 * (sk.joints["pelvis"][0] - 150),
            0.8 * (sk.joints["r_knee"][1] - 30) + 0.2 * (sk.joints["pelvis"][1] + 150),
        ),
    }


def draw_character(draw: ImageDraw.ImageDraw, sk: Skeleton) -> None:
    j, h = sk.joints, sk.height_px
    (nx, ny), (_, ty) = j["neck"], j["head_top"]
    r = (ny - ty) / 2
    px, py = j["pelvis"]
    # tail first (behind everything), crossing behind the right leg
    draw.line([(px - 5, py + 15), (j["r_knee"][0] - 4, j["r_knee"][1] - 30), (px - 150, py + 150)],
              fill=FUR, width=int(h * 0.06), joint="curve")  # fmt: skip
    for side in ("l", "r"):
        draw.line([j[f"{side}_hip"], j[f"{side}_knee"], j[f"{side}_ankle"]], fill=PANTS,
                  width=int(h * 0.06), joint="curve")  # fmt: skip
        fx, fy = j[f"{side}_foot"]
        draw.ellipse([fx - 22, fy - 14, fx + 22, fy + 6], fill=DARK)
    draw.polygon([j["r_shoulder"], j["l_shoulder"], j["l_hip"], j["r_hip"]], fill=FUR)
    draw.line([j["neck"], j["pelvis"]], fill=FUR, width=int(h * 0.1))
    for side in ("l", "r"):
        draw.line([j[f"{side}_shoulder"], j[f"{side}_elbow"], j[f"{side}_wrist"]], fill=FUR,
                  width=int(h * 0.05), joint="curve")  # fmt: skip
        hx, hy = j[f"{side}_hand"]
        draw.ellipse([hx - 16, hy - 16, hx + 16, hy + 16], fill=DARK)
    draw.ellipse([nx - 0.8 * r, ty, nx + 0.8 * r, ny + 0.1 * r], fill=FUR)
    f = face_points(sk)
    mx, my = f["nose"]
    draw.ellipse([mx - 0.45 * r, my - 0.3 * r, mx + 0.45 * r, my + 0.4 * r], fill=CREAM)
    for eye in ("eye_l", "eye_r"):
        ex, ey = f[eye]
        draw.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], fill=DARK)
    draw.ellipse([mx - 10, my - 8, mx + 10, my + 8], fill=DARK)
    ax, ay = f["mouth"]
    draw.line([(ax - 18, ay), (ax + 18, ay)], fill=DARK, width=3)
    draw.rectangle([j["r_shoulder"][0] - 12, ny - 15, j["l_shoulder"][0] + 12, ny + 25], fill=SCARF)


def sheet() -> Image.Image:
    img = Image.new("RGB", CANVAS, BG)
    draw = ImageDraw.Draw(img)
    for sk in (FRONT, SIDE):
        draw_character(draw, sk)
    return img


def pixels() -> np.ndarray:
    return np.asarray(sheet()).astype("float32")


def at(mask: np.ndarray, p: tuple[float, float]) -> bool:
    return bool(mask[int(p[1]), int(p[0])])


@pytest.fixture
def film(tmp_path: Path) -> Path:
    root = tmp_path / "film"
    Film.create(root, "storybook", load_manifest())
    design = root / "characters" / "kit" / "design"
    (design / "c1").mkdir(parents=True)
    sheet().save(design / "c1" / "sheet.png")
    candidate = {
        "id": "c1", "description": "a small fox with a scarf", "seed": 1, "fast": False,
        "sheet": "c1/sheet.png", "ok": True, "problems": [],
    }  # fmt: skip
    data = {
        "schema_version": 1, "character": "kit", "style": "storybook",
        "chosen": "c1", "candidates": [candidate],
    }  # fmt: skip
    (design / "candidates.json").write_text(json.dumps(data))
    return root


def test_the_head_leaves_the_scarf_on_the_torso() -> None:
    img = pixels()
    figure, _ = figure_mask(img, FRONT)
    head = head_mask(img, figure, FRONT)
    f = face_points(FRONT)
    assert all(at(head, f[k]) for k in ("eye_l", "eye_r", "nose", "mouth"))
    assert not at(head, f["scarf"])


def test_limbs_take_their_own_pixels_and_leave_the_tail() -> None:
    img = pixels()
    figure, _ = figure_mask(img, FRONT)
    bones = rig_bones(FRONT)
    fits = {n: limb_fit(figure, FRONT, bones[n]) for n in build.LIMBS}
    assert all(fit["ok"] and fit["coverage"] >= 0.95 for fit in fits.values())
    parts = assign_parts(img, figure, head_mask(img, figure, FRONT), bones, fits)
    f = face_points(FRONT)
    assert at(parts["forearm_l"], FRONT.joints["l_hand"])  # the paw goes with the forearm
    assert at(parts["shin_r"], FRONT.joints["r_foot"])
    assert at(parts["thigh_l"], FRONT.joints["l_knee"])
    assert at(parts["torso"], f["tail"]) and at(parts["torso"], f["tail_on_thigh"])
    covered = np.sum([m.astype(int) for m in parts.values()], axis=0)
    assert covered.max() == 1 and np.array_equal(covered == 1, figure)  # each pixel once


def test_the_face_is_painted_out_but_the_nose_stays() -> None:
    img = pixels()
    figure, _ = figure_mask(img, FRONT)
    head = head_mask(img, figure, FRONT)
    cleaned, anchors, notes = clean_face(img, head, FRONT)
    f = face_points(FRONT)
    luma = cleaned @ np.array([0.299, 0.587, 0.114])
    for mark in ("eye_l", "eye_r", "mouth"):
        x, y = f[mark]
        assert luma[int(y), int(x)] > 120, mark  # fur or muzzle colour now
    assert luma[int(f["nose"][1]), int(f["nose"][0])] < 60
    assert notes["nose_found"] and notes["eyes_found"] == ["left", "right"]
    for side in ("left", "right"):
        ex, ey = anchors["eyes"][side]
        tx, ty = f["eye_l" if side == "left" else "eye_r"]
        assert abs(ex - tx) < 3 and abs(ey - ty) < 3, side
    assert abs(anchors["mouth"]["at"][1] - f["mouth"][1]) < 3


def test_build_writes_a_valid_rig_with_hanging_arms(film: Path) -> None:
    built = build_puppet(film, "kit", name="Kit", sam=False)
    folder = film / "characters" / "kit"
    assert built.rig_path == folder / "rig.json" and validate_file(built.rig_path) == []
    view = built.rig["views"]["front"]
    assert {p.name for p in (folder / "parts").iterdir()} == {f"{b}.png" for b in view["bones"]}
    for name, part in view["parts"].items():
        w, h = Image.open(folder / part["file"]).size
        assert [w, h] == part["size_px"]
        assert 0 <= part["pivot_px"][0] <= w and 0 <= part["pivot_px"][1] <= h, name
    for arm in ("upper_arm_l", "upper_arm_r", "forearm_l", "forearm_r"):
        assert view["bones"][arm]["direction_deg"] == pytest.approx(-90, abs=0.5)
    assert built.report["limbs_ok"] and built.report["silhouette"]["method"] == "colour key"
    assert view["face"]["part"] == "head" and "kit" in json.loads((film / "film.json").read_text())[
        "characters"]  # fmt: skip
    palette = json.loads((folder / "palette.json").read_text())["colors"]
    assert {c["hex"] for c in palette[:3]} & {"#e67828", "#e57828", "#e67827"}  # the fur leads
    for name in ("parts.png", "face.png", "poses.png", "report.json"):
        assert (folder / "build" / name).is_file()


def test_turning_the_arms_back_reproduces_the_sheet(film: Path) -> None:
    built = build_puppet(film, "kit", sam=False)
    view = built.rig["views"]["front"]
    turned = built.report["arms_turned_to_hang_deg"]
    undo = {b: -turned[b] for b in ("upper_arm_l", "upper_arm_r")}
    posed = compose(view, film / "characters" / "kit", undo, size=CANVAS,
                    root_at=tuple(round(v) for v in FRONT.joints["pelvis"]))  # fmt: skip
    drawn, _ = figure_mask(pixels(), FRONT)
    alpha = np.asarray(posed)[..., 3] > 127
    iou = (alpha & drawn).sum() / (alpha | drawn).sum()
    assert iou > 0.95


def test_sam_joins_the_colour_key_unless_it_went_wrong(
    film: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drawn, _ = figure_mask(pixels(), FRONT)

    def fake_segment(film_root, sheet_path, skeletons, out_dir, cfg=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "mask_front.png"
        Image.fromarray((mask * 255).astype("uint8")).save(path)
        return [path]

    monkeypatch.setattr(build, "segment_sheet", fake_segment)
    mask = drawn.copy()
    assert build_puppet(film, "kit").report["silhouette"]["method"] == "colour key + SAM 2.1"
    mask = np.zeros_like(drawn)
    mask[:, :672] = True  # SAM returned the whole column
    notes = build_puppet(film, "kit").report["silhouette"]
    assert notes["sam_rejected"] and notes["method"] == "colour key"


def test_nothing_chosen_is_refused(film: Path) -> None:
    data_path = film / "characters" / "kit" / "design" / "candidates.json"
    data = json.loads(data_path.read_text())
    del data["chosen"]
    data_path.write_text(json.dumps(data))
    with pytest.raises(BuildError, match="no design chosen"):
        build_puppet(film, "kit", sam=False)
