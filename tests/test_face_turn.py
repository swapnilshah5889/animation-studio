"""The face's style and turn: solid eyes, a foreshortened three-quarter face, the eye classifier
that reads the style from the drawing, and seating a feature on the skin (D-078)."""

import copy
import hashlib
from typing import Any

import numpy as np

from studio_core.config import REPO_ROOT
from studio_core.face import face_layers
from studio_core.puppet.build import classify_eye, seat_on_skin
from studio_core.rig import load_rig
from studio_core.sif import Region, Space

PIP = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip" / "rig.json"
SPACE = Space(1920, 1080, 60)
# repr() of Pip's face layers, every state, as drawn before the style and the turn existed
PIP_FACE_SHA = "b436a287a9844d47fc559b8ccee90e9a4357c236866413e3002fe03c845f634a"


def pip_view(**face: Any) -> dict[str, Any]:
    view = copy.deepcopy(load_rig(PIP).view())
    for key, value in face.items():
        if key in ("eyes", "colors", "brows"):
            view["face"].setdefault(key, {}).update(value)
        else:
            view["face"][key] = value
    return view


def named(layer: Any, *path: str) -> Any:
    for desc in path:
        layer = next(c for c in layer.children if c.desc == desc)
    return layer


def width(region: Any) -> float:
    xs = [p.point.x for p in region.spline.points]
    return max(xs) - min(xs)


def centre_x(region: Any) -> float:
    xs = [p.point.x for p in region.spline.points]
    return (max(xs) + min(xs)) / 2


def eyes_of(layers: list[Any], state: str = "open") -> tuple[Any, Any]:
    left, right = (next(s for s in layers if s.desc == d) for d in ("eye_l", "eye_r"))
    return named(left, state), named(right, state)


# ------------------------------------------------------------------ nothing changes without them


def test_a_rig_without_style_or_turn_draws_the_face_it_always_did() -> None:
    layers = face_layers(load_rig(PIP).view(), SPACE)
    assert hashlib.sha256(repr(layers).encode()).hexdigest() == PIP_FACE_SHA
    # saying the defaults out loud is the same face
    explicit = pip_view(turn=0.0, eyes={"style": "sclera"})
    assert repr(face_layers(explicit, SPACE)) == repr(layers)


# ------------------------------------------------------------------ solid eyes


def test_a_solid_eye_is_a_dark_oval_with_a_highlight_and_no_white() -> None:
    view = pip_view(
        eyes={"style": "solid", "width_px": 30, "highlight_px": [4, -6], "color": "#221100"},
        colors={"skin": "#f0d0b0"},
    )
    left, _ = eyes_of(face_layers(view, SPACE))
    assert [c.desc for c in left.children] == ["eye", "shine"]
    assert left.children[0].color.r < 0.2  # dark
    assert abs(width(left.children[0]) - 30 / 60) < 1e-6  # the drawn eye's width
    assert centre_x(left.children[1]) > centre_x(left.children[0])  # shine to the right
    # blink and half-closed still work: a skin-coloured lid over the oval, then a lid line
    half, closed = (
        eyes_of(face_layers(view, SPACE), "half")[0],
        eyes_of(face_layers(view, SPACE), "closed")[0],
    )
    assert [c.desc for c in half.children] == ["eye", "lid"]
    assert half.children[1].color == half.children[1].color.hex("#f0d0b0")
    assert [c.desc for c in closed.children] == ["lid"]


def test_a_sclera_eye_keeps_its_white() -> None:
    left, _ = eyes_of(face_layers(load_rig(PIP).view(), SPACE))
    assert "white" in [c.desc for c in left.children]


# ------------------------------------------------------------------ the three-quarter turn


def eye_widths(turn: float) -> tuple[float, float]:
    """(far, near) open-eye widths of the face on a head turned toward screen-right."""
    layers = face_layers(pip_view(turn=turn), SPACE)
    left, right = eyes_of(layers)  # the character's left eye is the viewer's right: the far one
    return width(named(left, "white")), width(named(right, "white"))


def test_the_far_eye_is_narrower_by_the_turn() -> None:
    for turn, ratio in ((0.3, 0.69), (0.78, 0.594), (1.0, 0.55), (1.4, 0.55)):
        far, near = eye_widths(turn)
        assert abs(far / near - ratio) < 0.01, (turn, far / near)
    far, near = eye_widths(0.78)
    assert 0.55 <= far / near <= 0.75


def test_a_face_turned_left_foreshortens_the_other_eye() -> None:
    layers = face_layers(pip_view(turn=-0.8), SPACE)
    left, right = eyes_of(layers)  # now the character's right eye (screen-left) is the far one
    assert width(named(right, "white")) < 0.7 * width(named(left, "white"))


def test_the_far_brow_is_shorter_and_pupils_look_to_the_facing_side() -> None:
    front = face_layers(pip_view(), SPACE)
    turned = face_layers(pip_view(turn=0.8), SPACE)

    def brow_span(layers: list[Any], side: int) -> float:
        group = named(next(s for s in layers if s.desc == "brows"), "neutral")
        xs = [p.point.x for p in group.children[side].spline.points]
        return max(xs) - min(xs)

    assert brow_span(turned, 0) < 0.8 * brow_span(front, 0)  # left brow: the far one
    assert abs(brow_span(turned, 1) - brow_span(front, 1)) < 1e-9  # the near brow is unchanged
    for state_eye, base_eye in zip(eyes_of(turned), eyes_of(front), strict=True):
        shift = centre_x(named(state_eye, "pupil")) - centre_x(named(state_eye, "white"))
        assert shift > 0  # toward screen-right, the way the face turns
        assert abs(named(base_eye, "pupil").origin.x - centre_x(named(base_eye, "white"))) < 1e-9


def test_the_turned_mouth_is_shorter_and_sits_toward_the_snout() -> None:
    def mouth_d(layers: list[Any]) -> Region:
        mouth = next(s for s in layers if s.desc == "mouth")
        return named(mouth, "D", "inside")

    front = mouth_d(face_layers(pip_view(), SPACE))
    turned = mouth_d(face_layers(pip_view(turn=1.0), SPACE))
    assert abs(width(turned) / width(front) - 0.7) < 0.01
    assert centre_x(turned) - centre_x(front) > 0.05  # shifted right, the facing side


def test_the_solid_face_foreshortens_too() -> None:
    view = pip_view(turn=1.0, eyes={"style": "solid"})
    left, right = eyes_of(face_layers(view, SPACE))
    assert abs(width(left.children[0]) / width(right.children[0]) - 0.55) < 0.01


# ------------------------------------------------------------------ reading the style

SKIN = np.array([240, 215, 190], dtype="float32")


def canvas(size: int = 60) -> tuple[np.ndarray, np.ndarray]:
    rgb = np.tile(SKIN, (size, size, 1))
    return rgb, np.mgrid[0:size, 0:size]


def test_a_dark_oval_with_a_highlight_is_a_solid_eye() -> None:
    rgb, (yy, xx) = canvas()
    oval = ((xx - 30) / 12) ** 2 + ((yy - 30) / 16) ** 2 <= 1
    shine = (xx - 35) ** 2 + (yy - 24) ** 2 <= 9
    rgb[oval] = (40, 25, 20)
    rgb[shine] = (255, 255, 255)
    luma = rgb @ np.array([0.299, 0.587, 0.114], dtype="float32")
    look = classify_eye(oval & ~shine, luma, rgb)
    assert look["style"] == "solid"
    assert (look["w"], look["h"]) == (25, 33)
    assert look["highlight"][0] > 3 and look["highlight"][1] < -3  # up and to the right
    assert look["color"] == "#281914"


def test_a_ring_round_a_white_with_an_iris_is_a_sclera_eye() -> None:
    rgb, (yy, xx) = canvas()
    r2 = ((xx - 30) / 14) ** 2 + ((yy - 30) / 16) ** 2
    ring = (r2 <= 1) & (r2 > 0.7)
    rgb[r2 <= 1] = (255, 255, 255)
    iris = (xx - 30) ** 2 + (yy - 31) ** 2 <= 49
    rgb[ring | iris] = (40, 25, 20)
    luma = rgb @ np.array([0.299, 0.587, 0.114], dtype="float32")
    assert classify_eye(ring | iris, luma, rgb)["style"] == "sclera"


def test_a_plain_dark_dot_has_no_highlight_so_it_stays_sclera() -> None:
    rgb, (yy, xx) = canvas()
    dot = (xx - 30) ** 2 + (yy - 30) ** 2 <= 36
    rgb[dot] = (30, 30, 30)
    luma = rgb @ np.array([0.299, 0.587, 0.114], dtype="float32")
    assert classify_eye(dot, luma, rgb)["style"] == "sclera"


# ------------------------------------------------------------------ seating a feature on the skin


def head_with_hair() -> tuple[np.ndarray, np.ndarray]:
    """A head 200 wide: skin in its right part, hair over its left third and its top."""
    rgb = np.tile(SKIN, (200, 200, 1))
    head = np.ones((200, 200), dtype=bool)
    rgb[:, :70] = (150, 80, 40)  # hair down the left
    rgb[:40] = (150, 80, 40)  # a fringe
    return rgb, head


def test_an_eye_over_the_hair_moves_onto_the_skin() -> None:
    rgb, head = head_with_hair()
    # drawn at the hair's edge: a good part of the eye's footprint is hair
    at, before, after = seat_on_skin(rgb, head, (72.0, 100.0), 14, 20, 40)
    assert before > 0.3 and after < 0.1
    assert at[0] > 72 + 5  # moved right, off the hair
    assert at[0] - 14 >= 69  # ... clear of it


def test_an_eye_on_the_skin_stays_where_it_is() -> None:
    rgb, head = head_with_hair()
    at, before, after = seat_on_skin(rgb, head, (130.0, 110.0), 14, 20, 40)
    assert at == (130.0, 110.0) and before == after < 0.05


def test_a_feature_with_no_skin_to_go_to_is_left_alone() -> None:
    rgb, head = head_with_hair()
    rgb[:] = (150, 80, 40)
    rgb[95:105, 95:105] = SKIN  # a pinhole of skin: nothing fits
    at, _, _ = seat_on_skin(rgb, head, (96.0, 100.0), 14, 20, 40)
    assert at == (96.0, 100.0)
