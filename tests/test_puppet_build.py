"""Building a puppet from a design sheet (task 4.4), on a synthetic character drawn on the
skeleton: a scarf across the neck, a tail behind one leg, trousers, paws, and a face. Every
rule of the cut is checked where it shows: the scarf stays on the torso, the tail doesn't
follow the leg, the face is painted out but the nose stays, the arms hang at rest, and
turning the arms back reproduces the sheet. SAM is faked (no GPU)."""

import json
import math
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
    complete_hidden,
    compose,
    figure_mask,
    head_mask,
    limb_fit,
    recentre_shins,
    reclaim_limb_orphans,
    sam_agrees,
)
from studio_core.puppet.consistency import ViewCut, asked_turn, compare_views, face_offset
from studio_core.puppet.design import CANVAS
from studio_core.puppet.skeleton import Skeleton, place, rig_bones, turnaround
from studio_core.schema import validate_file

FRONT, SIDE = turnaround(CANVAS)
BG = (250, 250, 248)
FUR, CREAM, SCARF = (230, 120, 40), (245, 225, 190), (60, 160, 70)
PANTS, DARK = (70, 90, 170), (40, 30, 30)


def face_points(sk: Skeleton) -> dict[str, tuple[float, float]]:
    (_, ny), (_, ty) = sk.joints["neck"], sk.joints["head_top"]
    r = (ny - ty) / 2
    eye_y, nose = sk.joints["r_eye"][1], sk.joints["nose"]
    return {  # where the skeleton puts them: turned with the head in the three-quarter view
        "eye_l": (sk.joints["l_eye"][0], eye_y),  # the character's left: screen-right
        "eye_r": (sk.joints["r_eye"][0], eye_y),
        "nose": (nose[0], nose[1] + 6),  # a little below the eye line: never touching an eye
        "mouth": (nose[0], nose[1] + 0.2 * r),
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


def test_a_muzzle_below_the_nose_line_stays_on_the_head() -> None:
    """Bo's case (task 4.9): a muzzle in its own colour, all of it below the skeleton's nose
    line, between the cheeks. The colour rule alone left it on the torso. The scarf below the
    chin still isn't head."""
    img = sheet()
    draw = ImageDraw.Draw(img)
    (nx, ny), nose_y = FRONT.joints["neck"], FRONT.joints["nose"][1]
    r = (ny - FRONT.joints["head_top"][1]) / 2
    muzzle = [nx - 0.5 * r, nose_y + 2, nx + 0.5 * r, ny - 0.15 * r]
    draw.ellipse(muzzle, fill=(240, 236, 150))  # pale yellow: no head colour above the line
    img = np.asarray(img).astype("float32")
    figure, _ = figure_mask(img, FRONT)
    head = head_mask(img, figure, FRONT)
    centre = (nx, (muzzle[1] + muzzle[3]) / 2)
    assert at(figure, centre) and at(head, centre)
    assert not at(head, face_points(FRONT)["scarf"])


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


def test_a_coat_edge_beside_the_wrist_stays_on_the_torso() -> None:
    """Mia's wave: past the wrist the corridor widens for hands, and a strip of the coat's front
    edge, in the sleeve's own colour, hung on the hand's outline and went with the forearm.
    Only a hand's own colour may spread there."""
    sk = FRONT
    base = sheet()
    draw = ImageDraw.Draw(base)
    bones = rig_bones(sk)
    bone = bones["forearm_l"]
    r = limb_fit(figure_mask(pixels(), sk)[0], sk, bone)["radius_px"]
    (ax, ay), (bx, by) = bone["joint_px"], bone["end_px"]
    length = math.hypot(bx - ax, by - ay)
    nx, ny = -(by - ay) / length, (bx - ax) / length
    sx, sy = (bx + nx * 1.8 * r * (1 if nx > 0 else -1), by + ny * 1.8 * r * (1 if nx > 0 else -1))
    draw.line([(bx, by), (sx, sy)], fill=DARK, width=4)  # the hand's outline reaches the strip
    draw.rectangle([sx - 4, sy - 12, sx + 4, sy + 12], fill=FUR)
    img = np.asarray(base).astype("float32")
    figure, _ = figure_mask(img, sk)
    fits = {n: limb_fit(figure, sk, bones[n]) for n in build.LIMBS}
    parts = assign_parts(img, figure, head_mask(img, figure, sk), bones, fits)
    assert at(figure, (sx, sy)) and not at(parts["forearm_l"], (sx, sy))
    assert at(parts["forearm_l"], sk.joints["l_hand"])


def test_hair_below_the_neck_line_stays_on_the_head() -> None:
    """Mia's curls hang to her shoulders, past the neck line. The head ended there in a flat
    cut and the rest stayed on the torso, so a turned head left a ragged band behind."""
    j = FRONT.joints
    (nx, ny), nose_y = j["neck"], j["nose"][1]
    half = abs(j["l_shoulder"][0] - j["r_shoulder"][0]) / 2
    base = sheet()
    ImageDraw.Draw(base).rectangle(
        [nx - half - 40, nose_y, nx - 0.5 * half, ny + 0.015 * FRONT.height_px], fill=FUR
    )
    img = np.asarray(base).astype("float32")
    figure, _ = figure_mask(img, FRONT)
    head = head_mask(img, figure, FRONT)
    assert at(head, (nx - half - 25, ny + 6))
    assert not at(head, face_points(FRONT)["scarf"])


def test_a_shin_drawn_beside_its_bone_slides_onto_the_drawing() -> None:
    """Mia's three-quarter shin_r (drift 0.9): the leg fit kept the skeleton behind a coat, and
    the shin's bone ran 23 px beside the drawn leg."""
    sk = FRONT
    bones = rig_bones(sk)
    (kx, ky), (_, ay) = bones["shin_r"]["joint_px"], bones["shin_r"]["end_px"]
    figure = np.zeros(CANVAS[::-1], dtype=bool)
    figure[int(ky) - 10 : int(ay) + 10, int(kx) + 22 - 40 : int(kx) + 22 + 40] = True
    fits = {n: limb_fit(figure, sk, bones[n]) for n in ("shin_r", "shin_l")}
    assert 0.6 < fits["shin_r"]["drift"] <= 1.2 and not fits["shin_r"]["ok"]
    moved = recentre_shins(sk, bones, fits)
    assert moved.joints["r_hip"] == sk.joints["r_hip"]
    assert moved.joints["l_knee"] == sk.joints["l_knee"]  # no leg drawn there: left alone
    assert limb_fit(figure, moved, rig_bones(moved)["shin_r"])["drift"] < 0.25


def test_a_pale_highlight_inside_a_leg_goes_with_the_leg() -> None:
    """Pim, the bird: white shine down the cream trousers. It isn't the leg's core colour, so the
    colour rule left it on the torso, where it stays behind when the leg moves. Pale pixels
    between a leg's own pixels join it; pale pixels beside it, or dark ones between, don't."""
    h, w = 100, 80
    rgb = np.full((h, w, 3), (120.0, 100.0, 90.0), dtype="float32")
    mask = np.ones((h, w), dtype=bool)
    rgb[:, 28:32] = (252, 252, 246)  # a highlight down the leg
    rgb[:, 10:14] = (252, 252, 246)  # pale, but outside the leg
    rgb[10:20, 18:22] = (30, 30, 30)  # a dark seam
    mine = np.zeros((h, w), dtype=bool)
    mine[:, 20:28] = mine[:, 32:40] = True  # the leg, split by the highlight
    names = ("thigh_l", "shin_l", "thigh_r", "shin_r", "upper_arm_l", "forearm_l", "upper_arm_r",
             "forearm_r", "torso")  # fmt: skip
    parts = {n: np.zeros((h, w), dtype=bool) for n in names}
    parts["thigh_l"] = mine
    bone = {"joint_px": (30, 0), "end_px": (30, 99)}
    far = {"joint_px": (5, 0), "end_px": (5, 1)}
    bones = {n: far for n in names}
    bones["thigh_l"] = bone
    fits = {n: {"radius_px": 12.0} for n in names}
    build.join_leg_highlights(rgb, mask, np.zeros((h, w), dtype=bool), parts, bones, fits)
    assert parts["thigh_l"][50, 29] and parts["thigh_l"][50, 30]  # the highlight joined
    assert not parts["thigh_l"][50, 11]  # pale but beside the leg, not between its edges
    assert not parts["thigh_l"][15, 19]  # the dark seam beside the leg is not pale: left alone


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


def test_a_nose_on_the_outline_is_still_the_nose() -> None:
    """Bo's three-quarter view (task 4.9): the nose touches the head's outline, so the two
    make one long black blob, and an open mouth below it is a smaller black blob. The nose
    must still be found and kept, and the eyes painted out (not one taken for the nose)."""
    img = sheet()
    draw = ImageDraw.Draw(img)
    (nx, ny), (_, ty) = FRONT.joints["neck"], FRONT.joints["head_top"]
    r = (ny - ty) / 2
    head_box = [nx - 0.8 * r, ty, nx + 0.8 * r, ny + 0.1 * r]
    draw.ellipse(head_box, outline=DARK, width=4)
    f = face_points(FRONT)
    mx, my = f["nose"]
    draw.line([(mx, my), (head_box[2], my)], fill=DARK, width=4)  # nose joined to the outline
    draw.ellipse([mx - 6, my + 13, mx + 6, my + 21], fill=DARK)  # an open mouth
    img = np.asarray(img).astype("float32")
    figure, _ = figure_mask(img, FRONT)
    head = head_mask(img, figure, FRONT)
    cleaned, _, notes = clean_face(img, head, FRONT)
    luma = cleaned @ np.array([0.299, 0.587, 0.114])
    assert notes["nose_found"] and abs(notes["nose_px"][1] - my) < 4
    assert luma[int(my), int(mx)] < 60  # the nose stays
    for eye in ("eye_l", "eye_r"):
        assert luma[int(f[eye][1]), int(f[eye][0])] > 120, eye  # painted out


def test_a_mouth_by_the_snout_is_painted_out() -> None:
    """A turned head (Bo's three-quarter view, task 4.9): the nose and a drawn mouth sit by
    the head's edge, beyond the face zone (centred on the head, a share of its width either
    side). The mouth must be painted out all the same, and the nose kept."""
    base = np.asarray(sheet()).astype("float32")
    head = head_mask(base, figure_mask(base, FRONT)[0], FRONT)
    nose_y = int(FRONT.joints["nose"][1])
    xs = np.nonzero(head[nose_y])[0]
    zone_right = (xs.min() + xs.max()) / 2 + 0.42 * (xs.max() - xs.min() + 1)  # clean_face's
    my = nose_y + 20
    inside = int(np.nonzero(build._shrink(head, 6)[my])[0].max())  # 6 px in from the outline
    x0, x1 = int(zone_right) + 1, inside - 1
    assert x1 - x0 >= 2  # room for a mouth stroke the plain zone can't see

    img = sheet()
    draw = ImageDraw.Draw(img)
    nx = int(xs.max()) - 14
    draw.ellipse([nx - 10, nose_y - 8, nx + 10, nose_y + 8], fill=DARK)  # the nose
    draw.rectangle([x0, my - 1, x1, my + 1], fill=DARK)  # a mouth stroke by the snout
    img = np.asarray(img).astype("float32")
    figure, _ = figure_mask(img, FRONT)
    cleaned, _, notes = clean_face(img, head_mask(img, figure, FRONT), FRONT)
    luma = cleaned @ np.array([0.299, 0.587, 0.114])
    assert notes["nose_found"] and abs(notes["nose_px"][0] - nx) < 4
    assert luma[nose_y, nx] < 60  # the nose stays
    assert luma[my, (x0 + x1) // 2] > 120  # the mouth is painted out


def test_eyes_are_found_when_there_is_no_dark_nose() -> None:
    """A bird (Step 4 varied cast): a light beak and dark eyes at the beak's height. The
    near-black nose finder must not take one eye for the nose and drop the pair."""
    img = sheet()
    draw = ImageDraw.Draw(img)
    f = face_points(FRONT)
    mx, my = f["nose"]
    for eye in ("eye_l", "eye_r"):
        ex, ey = f[eye]
        draw.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], fill=CREAM)  # no high fox eyes
    draw.ellipse([mx - 10, my - 8, mx + 10, my + 8], fill=CREAM)  # the beak is light, not black
    for eye in ("eye_l", "eye_r"):
        ex, _ = f[eye]
        draw.ellipse([ex - 7, my - 7, ex + 7, my + 7], fill=DARK)  # dark eyes at the beak's height
    img = np.asarray(img).astype("float32")
    figure, _ = figure_mask(img, FRONT)
    head = head_mask(img, figure, FRONT)
    _, _, notes = clean_face(img, head, FRONT)
    assert notes["eyes_found"] == ["left", "right"], notes


def test_a_single_brown_eye_is_an_eye_not_a_nose() -> None:
    """The real bird (Step 4 varied cast): a turned head with one brown eye (not near-black) and no
    nose. The only mark on the face must not be taken for the nose."""
    img = sheet()
    draw = ImageDraw.Draw(img)
    f = face_points(FRONT)
    for eye in ("eye_l", "eye_r"):
        ex, ey = f[eye]
        draw.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], fill=CREAM)  # clear the fox's eyes
    mx, my = f["nose"]
    draw.ellipse([mx - 10, my - 8, mx + 10, my + 8], fill=CREAM)  # no nose
    ex, ey = f["eye_l"]
    brown = (120, 70, 55)
    draw.ellipse([ex - 8, ey - 12, ex + 8, ey + 12], fill=brown)  # the one eye
    img = np.asarray(img).astype("float32")
    figure, _ = figure_mask(img, FRONT)
    head = head_mask(img, figure, FRONT)
    _, anchors, notes = clean_face(img, head, FRONT)
    assert notes["eyes_found"] == ["left"], notes
    assert abs(anchors["eyes"]["left"][0] - ex) < 4 and abs(anchors["eyes"]["left"][1] - ey) < 4


def _far_arm(joint_x: int, sleeve: tuple[int, int, int], forearm: tuple[int, int, int]):
    """A far arm drawn behind a wide body, sticking out to the right: a sleeve from the body's
    edge (x=120) to x=165, then a forearm to x=200. Returns what complete_hidden takes."""
    h, w = 120, 220
    rgb = np.full((h, w, 3), 245.0, dtype="float32")
    figure = np.zeros((h, w), dtype=bool)
    figure[10:110, 10:120] = True  # the body
    figure[50:70, 120:200] = True  # the arm
    rgb[figure] = (200, 150, 90)
    rgb[50:70, 120:165] = sleeve
    rgb[50:70, 165:200] = forearm
    ys, xs = np.mgrid[0:h, 0:w]
    names = ("upper_arm_l", "upper_arm_r", "forearm_l", "forearm_r", "torso")
    parts = {n: np.zeros((h, w), dtype=bool) for n in names}
    parts["upper_arm_l"] = figure & (xs >= joint_x) & (xs < 165) & (ys >= 50) & (ys < 70)
    parts["forearm_l"] = figure & (xs >= 165) & (ys >= 50) & (ys < 70)
    parts["torso"] = figure & ~parts["upper_arm_l"] & ~parts["forearm_l"]
    far = {"joint_px": (joint_x, 60), "end_px": (165, 60)}
    elsewhere = {"joint_px": (30, 5), "end_px": (60, 5)}  # no figure there: nothing hidden
    bones = {"upper_arm_l": far, "forearm_l": {"joint_px": (165, 60), "end_px": (200, 60)},
             "upper_arm_r": elsewhere, "forearm_r": elsewhere}  # fmt: skip
    fits = {n: {"radius_px": 10.0} for n in bones}
    return rgb, figure, parts, bones, fits, names


def test_a_far_sleeve_of_its_own_colour_is_cut_as_drawn() -> None:
    """Pim, the bird: a white sleeve out of the body, then a blue forearm. The upper arm comes
    out halfway along, but a plain sleeve in the forearm's blue would be the wrong colour, and
    the drawn white one would stay on the torso when the arm moves."""
    rgb, figure, parts, bones, fits, names = _far_arm(45, (250, 245, 235), (140, 210, 240))
    fills, notes = complete_hidden(rgb, figure, parts, bones, fits, names)
    assert notes["upper_arm_l"]["drawn"] == "fill" and not fills["upper_arm_l"]["sleeve"], notes
    assert parts["upper_arm_l"][60, 140] and not parts["torso"][60, 140]  # the sleeve moves


def test_a_far_sleeve_in_the_forearms_colour_is_a_plain_sleeve() -> None:
    """Bo: the same fur on the sleeve and the forearm, so a plain sleeve stands in for it."""
    rgb, figure, parts, bones, fits, names = _far_arm(45, (120, 80, 50), (122, 82, 52))
    _, notes = complete_hidden(rgb, figure, parts, bones, fits, names)
    assert notes["upper_arm_l"]["drawn"] == "sleeve", notes


def test_a_mostly_hidden_far_arm_is_a_plain_sleeve_whatever_shows() -> None:
    """Kit: the arm comes out at the very end of the upper arm; what shows isn't sleeve."""
    rgb, figure, parts, bones, fits, names = _far_arm(5, (250, 245, 235), (140, 210, 240))
    bones["upper_arm_l"] = {"joint_px": (5, 60), "end_px": (130, 60)}
    parts["upper_arm_l"] = (
        figure & (np.mgrid[0:120, 0:220][1] < 130) & (np.mgrid[0:120, 0:220][0] >= 50)
    )
    _, notes = complete_hidden(rgb, figure, parts, bones, fits, names)
    assert notes["upper_arm_l"]["drawn"] == "sleeve", notes


def test_a_far_shin_that_misses_the_short_sole_still_passes() -> None:
    assert build.far_side_ok({"coverage": 0.81})  # 17 of 21 samples: the sole is short
    assert not build.far_side_ok({"coverage": 0.76})  # a real gap: the bone leaves the figure


def test_a_thigh_beside_a_touching_leg_is_judged_by_the_leg_fit() -> None:
    """Bo's dungaree legs touch: the thigh's cross-section runs into the other leg and reads as
    drifted by a radius, though the leg fit found the skeleton already on the legs."""
    merged = {"coverage": 1.0, "drift": 1.09}
    assert build.touching_thigh_ok(merged, {"skeleton_score": 0.71, "changed": False})
    assert not build.touching_thigh_ok(merged, {"skeleton_score": 0.4, "changed": False})
    assert not build.touching_thigh_ok(merged, {"skeleton_score": 0.8, "changed": True})
    assert not build.touching_thigh_ok({"coverage": 0.5, "drift": 1.09}, {"skeleton_score": 0.8})


def test_build_writes_a_valid_rig_with_both_views(film: Path) -> None:
    built = build_puppet(film, "kit", name="Kit", sam=False, three_quarter="sheet")
    folder = film / "characters" / "kit"
    assert built.rig_path == folder / "rig.json" and validate_file(built.rig_path) == []
    assert set(built.rig["views"]) == {"front", "three_quarter"}
    for name, view in built.rig["views"].items():
        report = built.report["views"][name]
        parts = {p.name for p in (folder / "parts" / name).iterdir()}
        assert parts == {f"{b}.png" for b in view["bones"]}, name
        for part_name, part in view["parts"].items():
            w, h = Image.open(folder / part["file"]).size
            assert [w, h] == part["size_px"]
            assert 0 <= part["pivot_px"][0] <= w and 0 <= part["pivot_px"][1] <= h, part_name
        for arm in ("upper_arm_l", "upper_arm_r", "forearm_l", "forearm_r"):
            assert view["bones"][arm]["direction_deg"] == pytest.approx(-90, abs=0.5)
        assert report["limbs_ok"] and report["silhouette"]["method"] == "colour key", name
        assert report["face"]["nose_found"] and report["face"]["eyes_found"] == ["left", "right"]
        for image in ("parts.png", "face.png", "poses.png"):
            assert (folder / "build" / name / image).is_file()
    tq = built.rig["views"]["three_quarter"]
    assert tq["draw_order"][:2] == ["upper_arm_l", "forearm_l"]  # the far arm behind
    assert "kit" in json.loads((film / "film.json").read_text())["characters"]
    palette = json.loads((folder / "palette.json").read_text())["colors"]
    assert {c["hex"] for c in palette[:3]} & {"#e67828", "#e57828", "#e67827"}  # the fur leads
    assert (folder / "build" / "report.json").is_file()
    assert built.report["consistency"]["ok"], built.report["consistency"]["problems"]


def test_turning_the_arms_back_reproduces_the_sheet(film: Path) -> None:
    built = build_puppet(film, "kit", sam=False, three_quarter="sheet")
    for sk in (FRONT, SIDE):
        view = built.rig["views"][sk.view]
        turned = built.report["views"][sk.view]["arms_turned_to_hang_deg"]
        undo = {b: -turned[b] for b in ("upper_arm_l", "upper_arm_r")}
        posed = compose(view, film / "characters" / "kit", undo, size=CANVAS,
                        root_at=tuple(round(v) for v in sk.joints["pelvis"]))  # fmt: skip
        drawn, _ = figure_mask(pixels(), sk)
        alpha = np.asarray(posed)[..., 3] > 127
        assert (alpha & drawn).sum() / (alpha | drawn).sum() > 0.95, sk.view


def test_sam_joins_the_colour_key_unless_it_went_wrong(
    film: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drawn = {sk.view: figure_mask(pixels(), sk)[0] for sk in (FRONT, SIDE)}
    masks = dict(drawn)

    def fake_segment(film_root, sheet_path, skeletons, out_dir, cfg=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for sk in skeletons:
            paths.append(out_dir / f"mask_{sk.view}.png")
            Image.fromarray((masks[sk.view] * 255).astype("uint8")).save(paths[-1])
        return paths

    monkeypatch.setattr(build, "segment_sheet", fake_segment)
    views = build_puppet(film, "kit", three_quarter="sheet").report["views"]
    assert {v["silhouette"]["method"] for v in views.values()} == {"colour key + SAM 2.1"}
    masks["three_quarter"] = np.zeros_like(drawn["front"])
    masks["three_quarter"][:, 672:] = True  # SAM returned the whole column
    views = build_puppet(film, "kit", three_quarter="sheet").report["views"]
    assert views["front"]["silhouette"]["method"] == "colour key + SAM 2.1"
    assert views["three_quarter"]["silhouette"]["sam_rejected"]


def test_a_loose_piece_of_torso_inside_a_limb_goes_to_the_limb() -> None:
    bones = rig_bones(FRONT)
    fits = {n: {"radius_px": 30.0} for n in build.LIMBS}
    shape = (CANVAS[1], CANVAS[0])
    torso = np.zeros(shape, bool)
    pelvis = FRONT.joints["pelvis"]
    torso[int(pelvis[1]) - 200 : int(pelvis[1]), int(pelvis[0]) - 60 : int(pelvis[0]) + 60] = True
    parts = {n: np.zeros(shape, bool) for n in (*build.LIMBS, "head")}
    shin = bones["shin_r"]
    (jx, jy), (ex, ey) = shin["joint_px"], shin["end_px"]
    mx, my = int((jx + ex) / 2), int((jy + ey) / 2)  # mid-shin: the colour rule left it
    inside = np.zeros(shape, bool)
    inside[my - 15 : my + 15, mx - 8 : mx + 8] = True
    away = np.zeros(shape, bool)
    away[20:50, 20:50] = True  # far from every limb: a wisp of hair, say
    parts["torso"] = torso | inside | away
    reclaim_limb_orphans(parts, bones, fits)
    assert np.array_equal(parts["shin_r"], inside)
    assert np.array_equal(parts["torso"], torso | away)  # the main body and the wisp stay


def test_sam_may_add_a_pale_shirt_the_key_lost_but_not_miss_or_swamp_the_figure() -> None:
    key = np.zeros((100, 100), bool)
    key[10:90, 40:60] = True  # the figure the colour key found: 1600 px
    shirt = key.copy()
    shirt[30:60, 25:75] = True  # SAM adds a white shirt: the IoU is only 0.64
    assert sam_agrees(key, shirt)
    assert not sam_agrees(key, np.roll(key, 30, axis=1))  # SAM found something else
    column = np.zeros_like(key)
    column[:, 30:] = True  # SAM returned the whole column: covers the key, is mostly elsewhere
    assert not sam_agrees(key, column)


def _two_views(tq_skeleton: Skeleton, *, hat: bool = False, beak: bool = False) -> np.ndarray:
    """A sheet whose three-quarter figure is drawn from `tq_skeleton`, maybe with a hat, or with
    a small beak that only the turned head shows."""
    img = Image.new("RGB", CANVAS, BG)
    draw = ImageDraw.Draw(img)
    draw_character(draw, FRONT)
    draw_character(draw, tq_skeleton)
    if hat:
        x, y = tq_skeleton.joints["head_top"]
        draw.ellipse([x - 40, y + 5, x + 40, y + 55], fill=(90, 60, 200))
    if beak:
        x, y = tq_skeleton.joints["nose"]
        draw.ellipse([x - 22, y - 4, x + 22, y + 32], fill=(254, 204, 46))
    return np.asarray(img).astype("float32")


def _consistency(img: np.ndarray) -> dict:
    cuts = {}
    for sk in (FRONT, SIDE):
        figure, _ = figure_mask(img, sk)
        head = head_mask(img, figure, sk)
        bones = rig_bones(sk)
        fits = {n: limb_fit(figure, sk, bones[n]) for n in build.LIMBS}
        parts = assign_parts(img, figure, head, bones, fits)
        cuts[sk.view] = ViewCut(sk, parts)
    return compare_views(img, cuts)


def test_matching_views_are_consistent() -> None:
    report = _consistency(_two_views(SIDE))
    assert report["ok"], report["problems"]
    assert report["turn"]["fraction"] > 0.5


def test_a_hat_in_one_view_only_is_reported() -> None:
    report = _consistency(_two_views(SIDE, hat=True))
    assert [p for p in report["problems"] if p.startswith("head:")]
    assert report["regions"]["head"]["only_three_quarter"][0]["share"] > 0.03


def test_a_small_feature_only_the_turn_shows_is_a_note_not_a_problem() -> None:
    # A bird's beak seen in profile: a few per cent of the head, in one view only (Step 4, Pim).
    report = _consistency(_two_views(SIDE, beak=True))
    share = report["regions"]["head"]["only_three_quarter"][0]["share"]
    assert 0.03 <= share < 0.07, share
    assert report["ok"], report["problems"]
    assert [n for n in report["notes"] if n.startswith("head:")]


def test_an_unturned_three_quarter_view_is_reported() -> None:
    # The "three-quarter" figure drawn as a front view, as SDXL often does.
    unturned = place("front", height_px=SIDE.height_px, feet_px=SIDE.joints["sole"])
    report = _consistency(_two_views(Skeleton("three_quarter", unturned.joints, SIDE.hidden)))
    assert any("barely turned" in p for p in report["problems"])


def _hair_head(eye_xs: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
    """A head that is mostly curly hair (400 wide, 300 tall): a face on its right with big dark
    eyes at `eye_xs`, and on the left an ear and curl shadows drawn as thin dark lines."""
    img = Image.new("RGB", (600, 500), BG)
    draw = ImageDraw.Draw(img)
    draw.ellipse([100, 100, 500, 400], fill=(200, 120, 70))  # the hair
    draw.ellipse([280, 200, 470, 400], fill=(250, 225, 205))  # the face
    for x in range(130, 270, 25):
        draw.line([x, 250, x, 340], fill=(60, 30, 20), width=4)  # curl shadows, the ear
    for x in eye_xs:
        draw.ellipse([x - 14, 276, x + 14, 304], fill=(40, 20, 20))
    head = Image.new("L", img.size, 0)
    ImageDraw.Draw(head).ellipse([100, 100, 500, 400], fill=255)
    return np.asarray(img).astype("float32"), np.asarray(head) > 127


def test_a_wide_head_of_hair_does_not_hide_a_turned_face() -> None:
    # Mia (Step 4): thin ear and curl lines on the hair's side outnumber the eyes' pixels and pull
    # the face marks back to the head's middle, so a clearly turned face scored under half.
    img, head = _hair_head((350, 410))
    offset = face_offset(img, head)
    assert offset is not None
    assert offset / asked_turn(SIDE) >= 0.5, offset


def test_a_wide_head_of_hair_with_a_front_face_is_still_unturned() -> None:
    img, head = _hair_head((270, 330))  # eyes about the head's middle
    offset = face_offset(img, head)
    assert offset is not None
    assert offset / asked_turn(SIDE) < 0.5, offset


def test_nothing_chosen_is_refused(film: Path) -> None:
    data_path = film / "characters" / "kit" / "design" / "candidates.json"
    data = json.loads(data_path.read_text())
    del data["chosen"]
    data_path.write_text(json.dumps(data))
    with pytest.raises(BuildError, match="no design chosen"):
        build_puppet(film, "kit", sam=False, three_quarter="sheet")
