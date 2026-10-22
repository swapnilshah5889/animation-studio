"""The puppet skeleton: one set of numbers for both the pose image and the rig (task 4.2, D-047).

    front, three_quarter = turnaround()            # two figures on one 1344x768 canvas
    image = pose_image([front, three_quarter], (1344, 768))   # → ControlNet (OpenPose)
    bones = rig_bones(front)                       # → rig.json bones (task 4.4)

Generation is *told* where the joints are: the skeleton is drawn as an OpenPose-style stick
figure and SDXL is conditioned on it (xinsir union ProMax). So the rig doesn't have to guess
where a generated character's elbows are; it uses the same numbers that made the picture.

**Proportions** come from Pip, the placeholder puppet (a child-like cartoon: the head is about
40% of the height). **The pose** is a gentle A-pose: arms about 25° out from hanging and legs
slightly apart, so every limb is clear of the body for cutting, yet close enough to "arms
down" that the motion library's offsets look natural.

**Coordinates:** a template is defined in *design units* (y up, the ground at 0, the figure's
centre line at x = 0, the full height = 1). `place` maps it into canvas pixels (y down).
**Sides** are the character's own: its left is on the viewer's right in the front view.

**Three-quarter view:** the figure is turned 45° to face screen-right, a rotation about the
vertical axis with cartoon depth: the near side (the character's right) widens a little and
the far side tucks in (a plain rotation narrows both sides alike and reads as a thin front
view). The far ear is hidden, so it isn't drawn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from PIL import Image, ImageDraw

View = Literal["front", "three_quarter"]

# OpenPose COCO-18 body keypoints, in the order every OpenPose tool uses. r/l = the character's
# right/left.
OPENPOSE = (
    "nose",
    "neck",
    "r_shoulder",
    "r_elbow",
    "r_wrist",
    "l_shoulder",
    "l_elbow",
    "l_wrist",
    "r_hip",
    "r_knee",
    "r_ankle",
    "l_hip",
    "l_knee",
    "l_ankle",
    "r_eye",
    "l_eye",
    "r_ear",
    "l_ear",
)
# Limb pairs (indices into OPENPOSE) and the standard OpenPose colours, as ControlNets were
# trained on them.
LIMBS = (
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10),
    (1, 11), (11, 12), (12, 13), (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
)  # fmt: skip
COLORS = (
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0),
    (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
    (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85),
)  # fmt: skip

# Rig bones: (name, role, side, parent, from joint, to joint). Pivots sit at the "from" joint.
BONES = (
    ("torso", "torso", "center", None, "pelvis", "neck"),
    ("head", "head", "center", "torso", "neck", "head_top"),
    ("upper_arm_l", "upper_arm", "left", "torso", "l_shoulder", "l_elbow"),
    ("forearm_l", "forearm", "left", "upper_arm_l", "l_elbow", "l_hand"),
    ("upper_arm_r", "upper_arm", "right", "torso", "r_shoulder", "r_elbow"),
    ("forearm_r", "forearm", "right", "upper_arm_r", "r_elbow", "r_hand"),
    ("thigh_l", "thigh", "left", "torso", "l_hip", "l_knee"),
    ("shin_l", "shin", "left", "thigh_l", "l_knee", "l_foot"),
    ("thigh_r", "thigh", "right", "torso", "r_hip", "r_knee"),
    ("shin_r", "shin", "right", "thigh_r", "r_knee", "r_foot"),
)
# Joint limits by role and side (degrees from rest), as on Pip (D-029).
LIMITS = {
    ("torso", "center"): (-15, 15),
    ("head", "center"): (-25, 25),
    ("upper_arm", "left"): (-30, 170),
    ("upper_arm", "right"): (-170, 30),
    ("forearm", "left"): (-20, 140),
    ("forearm", "right"): (-140, 20),
    ("thigh", "left"): (-35, 35),
    ("thigh", "right"): (-35, 35),
    ("shin", "left"): (-10, 60),
    ("shin", "right"): (-60, 10),
}
# Back to front, as Pip: legs, torso, the far arm behind... the near arm and the head in front.
DRAW_ORDER = (
    "thigh_r", "shin_r", "thigh_l", "shin_l", "torso",
    "upper_arm_r", "forearm_r", "upper_arm_l", "forearm_l", "head",
)  # fmt: skip

# Pip's proportions in design units (height = 1, ground = 0, y up). Pip is 767 px tall:
# hips 240 px up, neck 482, head top 767; shoulders ±78 px; hips ±32 px.
_PX = 767.0
HIP_Y = 240 / _PX
NECK_Y = 482 / _PX
HEAD_TOP_Y = 1.0
SHOULDER_DY = -27 / _PX  # shoulders sit a little below the neck
SHOULDER_X = 78 / _PX
HIP_X = 32 / _PX
UPPER_ARM = 112 / _PX
FOREARM = 105 / _PX  # elbow → wrist
HAND = 27 / _PX  # wrist → fingertips
THIGH = 102 / _PX
SHIN = 116 / _PX  # knee → ankle
FOOT = 20 / _PX  # ankle → sole
HEAD_W = 220 / _PX
NOSE_Y = NECK_Y + 0.42 * (HEAD_TOP_Y - NECK_Y)
EYE_DX, EYE_DY = 0.17 * HEAD_W, 0.06 * (HEAD_TOP_Y - NECK_Y)
EAR_DX = 0.46 * HEAD_W
NOSE_DEPTH = 0.35 * HEAD_W  # how far the nose and eyes stand out in front of the head's axis
NEAR, FAR = 1.12, 0.72  # three-quarter view: widening of the near side, narrowing of the far side


@dataclass(frozen=True)
class Skeleton:
    view: View
    joints: dict[str, tuple[float, float]]  # canvas pixels, y down
    hidden: frozenset[str] = field(default_factory=frozenset)  # OpenPose points not drawn

    @property
    def height_px(self) -> float:
        return self.joints["sole"][1] - self.joints["head_top"][1]


def _template(arm_out_deg: float, leg_out_deg: float) -> dict[str, tuple[float, float, float]]:
    """Front-view joints in design units: (x, y, z), y up, z toward the viewer."""
    j: dict[str, tuple[float, float, float]] = {
        "pelvis": (0.0, HIP_Y, 0.0),
        "neck": (0.0, NECK_Y, 0.0),
        "head_top": (0.0, HEAD_TOP_Y, 0.0),
        "nose": (0.0, NOSE_Y, NOSE_DEPTH),
    }
    for side, sx in (("l", 1.0), ("r", -1.0)):  # the character's left is on the viewer's right
        j[f"{side}_eye"] = (sx * EYE_DX, NOSE_Y + EYE_DY, NOSE_DEPTH * 0.8)
        j[f"{side}_ear"] = (sx * EAR_DX, NOSE_Y + EYE_DY, 0.0)
        shoulder = (sx * SHOULDER_X, NECK_Y + SHOULDER_DY)
        a = math.radians(arm_out_deg)
        down_out = (sx * math.sin(a), -math.cos(a))  # unit vector: down, tilted outwards
        elbow = (shoulder[0] + down_out[0] * UPPER_ARM, shoulder[1] + down_out[1] * UPPER_ARM)
        wrist = (elbow[0] + down_out[0] * FOREARM, elbow[1] + down_out[1] * FOREARM)
        hand = (wrist[0] + down_out[0] * HAND, wrist[1] + down_out[1] * HAND)
        legs = math.radians(leg_out_deg)
        leg_dir = (sx * math.sin(legs), -math.cos(legs))
        hip = (sx * HIP_X, HIP_Y)
        knee = (hip[0] + leg_dir[0] * THIGH, hip[1] + leg_dir[1] * THIGH)
        ankle = (knee[0] + leg_dir[0] * SHIN, knee[1] + leg_dir[1] * SHIN)
        foot = (ankle[0], ankle[1] - FOOT)
        for name, (x, y) in (
            ("shoulder", shoulder),
            ("elbow", elbow),
            ("wrist", wrist),
            ("hand", hand),
            ("hip", hip),
            ("knee", knee),
            ("ankle", ankle),
            ("foot", foot),
        ):
            j[f"{side}_{name}"] = (x, y, 0.0)
    lowest = min(y for _, y, _ in j.values())
    j["sole"] = (0.0, lowest, 0.0)
    return j


def place(
    view: View,
    *,
    height_px: float,
    feet_px: tuple[float, float],
    arm_out_deg: float = 25.0,
    leg_out_deg: float = 6.0,
) -> Skeleton:
    """A skeleton of `height_px` whose soles touch `feet_px` (canvas pixels, y down)."""
    tpl = _template(arm_out_deg, leg_out_deg)
    sole = tpl["sole"][1]
    scale = height_px / (HEAD_TOP_Y - sole)
    turn = math.radians(45.0) if view == "three_quarter" else 0.0
    joints = {}
    for name, (x, y, z) in tpl.items():
        x_turned = x * math.cos(turn) + z * math.sin(turn)  # rotate about the vertical axis
        if view == "three_quarter":  # cartoon depth: the near side widens, the far side tucks in
            x_turned = x * math.cos(turn) * (NEAR if x < 0 else FAR) + z * math.sin(turn)
        joints[name] = (feet_px[0] + x_turned * scale, feet_px[1] - (y - sole) * scale)
    hidden = frozenset({"l_ear"}) if view == "three_quarter" else frozenset()
    return Skeleton(view, joints, hidden)


def turnaround(
    canvas: tuple[int, int] = (1344, 768), *, fill: float = 0.86, **pose: float
) -> tuple[Skeleton, Skeleton]:
    """Front (left half) and three-quarter (right half) skeletons on one canvas.
    1344x768 is an SDXL training size; each figure is `fill` of the canvas height."""
    w, h = canvas
    height = h * fill
    feet_y = h - (h - height) / 2
    front = place("front", height_px=height, feet_px=(w * 0.25, feet_y), **pose)
    side = place("three_quarter", height_px=height, feet_px=(w * 0.75, feet_y), **pose)
    return front, side


def pose_image(skeletons: list[Skeleton], size: tuple[int, int]) -> Image.Image:
    """OpenPose-style conditioning image: limbs as filled ellipses (60% colour) and joints as
    dots, on black. Line widths scale with the figure so ControlNet sees the same proportions
    at any size (the xinsir models were trained on thick lines)."""
    img = Image.new("RGB", size, (0, 0, 0))
    for sk in skeletons:
        stick = max(4.0, sk.height_px / 110)
        layer = Image.new("RGB", size, (0, 0, 0))
        mask = Image.new("L", size, 0)
        for i, (a, b) in enumerate(LIMBS):
            na, nb = OPENPOSE[a], OPENPOSE[b]
            if na in sk.hidden or nb in sk.hidden:
                continue
            (x1, y1), (x2, y2) = sk.joints[na], sk.joints[nb]
            length = math.hypot(x2 - x1, y2 - y1)
            angle = math.atan2(y2 - y1, x2 - x1)
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            poly = [
                (
                    cx
                    + math.cos(t) * length / 2 * math.cos(angle)
                    - math.sin(t) * stick * math.sin(angle),
                    cy
                    + math.cos(t) * length / 2 * math.sin(angle)
                    + math.sin(t) * stick * math.cos(angle),
                )
                for t in (k * math.pi / 18 for k in range(36))
            ]
            color = tuple(int(c * 0.6) for c in COLORS[i])
            ImageDraw.Draw(layer).polygon(poly, fill=color)
            ImageDraw.Draw(mask).polygon(poly, fill=255)
        img.paste(layer, (0, 0), mask)
        draw = ImageDraw.Draw(img)
        for i, name in enumerate(OPENPOSE):
            if name in sk.hidden:
                continue
            x, y = sk.joints[name]
            r = stick
            draw.ellipse([x - r, y - r, x + r, y + r], fill=COLORS[i])
    return img


def mannequin_image(skeletons: list[Skeleton], size: tuple[int, int]) -> Image.Image:
    """A depth-style mannequin on the same joints: an oval head, a torso and round-ended limbs,
    grey on black (brighter = nearer). The stick figure says where the joints are; the
    mannequin says where the body *isn't*, so a weak depth condition keeps the arms off the
    torso (OpenPose alone let SDXL rest them against it, task 4.3). In three-quarter view the
    near limbs are lighter and the far ones darker."""
    img = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(img)
    for sk in skeletons:
        j, h = sk.joints, sk.height_px
        three_quarter = sk.view == "three_quarter"

        def limb(side: str, shade: int, j=j, h=h) -> None:
            grey = (shade,) * 3
            for chain, width in (
                (("shoulder", "elbow", "wrist", "hand"), h * 0.075),
                (("hip", "knee", "ankle", "foot"), h * 0.086),
            ):
                points = [j[f"{side}_{n}"] for n in chain]
                draw.line(points, fill=grey, width=round(width), joint="curve")
                for x, y in points[1:]:
                    r = width * (0.6 if (x, y) == points[-1] else 0.5)
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=grey)

        limb("l", 120 if three_quarter else 170)  # the far side in 3/4, drawn first
        torso = [j["r_shoulder"], j["l_shoulder"], j["l_hip"], j["r_hip"]]
        draw.polygon(torso, fill=(160,) * 3)
        draw.line([j["neck"], j["pelvis"]], fill=(160,) * 3, width=round(h * 0.12))
        (nx, ny), (_, ty) = j["neck"], j["head_top"]
        r = (ny - ty) / 2
        cx = (j["nose"][0] + nx) / 2 if three_quarter else nx
        draw.ellipse([cx - 0.85 * r, ty, cx + 0.85 * r, ny + 0.15 * r], fill=(185,) * 3)
        limb("r", 200 if three_quarter else 170)
    return img


def direction_deg(sk: Skeleton, start: str, end: str) -> float:
    """Direction from one joint to another in degrees, y up (the rig's convention)."""
    (x1, y1), (x2, y2) = sk.joints[start], sk.joints[end]
    return math.degrees(math.atan2(-(y2 - y1), x2 - x1))


def rig_bones(sk: Skeleton) -> dict[str, dict]:
    """The rig's bones for a skeleton: role, side, parent, rest direction, length, limits, and
    the canvas pixels of each bone's joint (its pivot). Attach points inside parent parts are
    filled in when the parts are cut (task 4.4)."""
    bones = {}
    for name, role, side, parent, start, end in BONES:
        (x1, y1), (x2, y2) = sk.joints[start], sk.joints[end]
        lo, hi = LIMITS[(role, side)]
        bones[name] = {
            "role": role,
            "side": side,
            "parent": parent,
            "direction_deg": round(direction_deg(sk, start, end), 2),
            "length_px": round(math.hypot(x2 - x1, y2 - y1), 1),
            "limits_deg": {"min": lo, "max": hi},
            "joint_px": (round(x1, 1), round(y1, 1)),
            "end_px": (round(x2, 1), round(y2, 1)),
        }
    return bones
