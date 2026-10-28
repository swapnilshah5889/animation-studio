"""Character rigs: rig.json (schemas/rig.schema.json) → a Synfig bone rig (D-027).

    rig = load_rig(Path("films/kite-day/characters/pip/rig.json"))
    built = build_character(rig, "front", space, file_prefix="../../characters/pip",
                            offsets={"upper_arm_l": Animated(...)})
    canvas.bones += built.bones; group.children.append(built.group)

Conventions (rig.schema.json):
- **Rest pose = the art as drawn.** Each bone points along `direction_deg` (90 = up, -90 = down).
- **Offsets** are what motions and poses animate: degrees from the rest pose, relative to the
  parent bone (counter-clockwise, y up). Offset 0 everywhere = the drawn pose.
- A bone's Synfig angle is relative to its parent: `(direction - parent_direction) + offset`.
- A child's joint (`attach.at_px`, a pixel in a part of the parent bone) becomes the bone origin
  in the parent bone's frame: the pixel vector from the parent part's pivot, rotated by
  `-parent_direction` (the same turn that lays the parent's art along +x).
- Each part is a flat group linked to its bone with `base = rotate(-direction)`, so draw order
  comes from `draw_order`, not from the hierarchy.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from studio_core.schema import validate
from studio_core.sif import (
    Angle,
    Animated,
    Bone,
    BoneLink,
    Group,
    ImportLayer,
    Layer,
    SkeletonDeformation,
    SkeletonLayer,
    Space,
    Transform,
    Vec,
    Waypoint,
)


class RigError(ValueError):
    pass


@dataclass(frozen=True)
class Rig:
    data: dict[str, Any]
    folder: Path  # the character folder; part files are relative to it

    @property
    def id(self) -> str:
        return self.data["id"]

    def view(self, name: str | None = None) -> dict[str, Any]:
        name = name or self.data["default_view"]
        if name not in self.data["views"]:
            raise RigError(
                f"rig {self.id!r} has no {name!r} view; it has {sorted(self.data['views'])}"
            )
        return self.data["views"][name]


def load_rig(path: Path, *, check_files: bool = True) -> Rig:
    data = json.loads(path.read_text())
    issues = validate("rig", data)
    if issues:
        raise RigError(f"{path}: " + "; ".join(map(str, issues)))
    rig = Rig(data, path.parent)
    if check_files:
        missing = sorted(
            {
                p["file"]
                for v in data["views"].values()
                for p in [*v["parts"].values(), *v.get("bendable_limbs", [])]
                if not (rig.folder / p["file"]).is_file()
            }
        )
        if missing:
            raise RigError(f"{path}: part files not found: {missing}")
    return rig


# --------------------------------------------------------------------------- geometry


def rotate(v: Vec, degrees: float) -> Vec:
    r = math.radians(degrees)
    return Vec(v.x * math.cos(r) - v.y * math.sin(r), v.x * math.sin(r) + v.y * math.cos(r))


def joint_vector_px(view: dict[str, Any], bone: str) -> Vec:
    """The child's joint relative to the parent part's pivot, in image pixels with y up."""
    attach = view["bones"][bone]["attach"]
    part = view["parts"][attach["part"]]
    (ax, ay), (px, py) = attach["at_px"], part["pivot_px"]
    return Vec(ax - px, py - ay)


def chain(view: dict[str, Any], bone: str) -> list[str]:
    """Bones from the root down to `bone`."""
    out = []
    current: str | None = bone
    while current is not None:
        out.append(current)
        current = view["bones"][current]["parent"]
    return out[::-1]


def clamp_offset(view: dict[str, Any], bone: str, offset: float) -> float:
    """Keep an offset inside the bone's `limits_deg` (unlimited when none are given)."""
    limits = view["bones"][bone].get("limits_deg")
    if not limits:
        return offset
    return max(limits["min"], min(limits["max"], offset))


def world_pose(
    view: dict[str, Any], offsets: dict[str, float] | None = None
) -> dict[str, tuple[Vec, float]]:
    """Forward kinematics in art pixels (y up), root joint at (0, 0).

    Returns {bone: (joint position, world direction in degrees)}. Used by tests to predict where
    a rendered part lands, and later for pointing and look-at targets.
    """
    offsets = offsets or {}
    out: dict[str, tuple[Vec, float]] = {}
    for bone in _parents_first(view):
        spec = view["bones"][bone]
        parent = spec["parent"]
        rot_from_rest = (
            0.0 if parent is None else out[parent][1] - view["bones"][parent]["direction_deg"]
        )
        direction = spec["direction_deg"] + rot_from_rest + offsets.get(bone, 0.0)
        if parent is None:
            out[bone] = (Vec(0, 0), direction)
            continue
        parent_pos = out[parent][0]
        v = rotate(joint_vector_px(view, bone), rot_from_rest)
        out[bone] = (Vec(parent_pos.x + v.x, parent_pos.y + v.y), direction)
    return out


def ground_offset_px(view: dict[str, Any]) -> float:
    """How far below the root joint the lowest art pixel is, at rest (art px, positive = below).
    Scenes place characters by their feet: root = feet position + this offset upwards."""
    rest = world_pose(view)
    lowest = 0.0
    for part in view["parts"].values():
        joint = rest[part["bone"]][0]
        bottom = joint.y - (part["size_px"][1] - part["pivot_px"][1])  # rest pose: parts unrotated
        lowest = min(lowest, bottom)
    return -lowest


def bendable_limbs(view: dict[str, Any]) -> list[dict[str, Any]]:
    """The view's limbs drawn as one bending image ([] for a plain two-part rig)."""
    return list(view.get("bendable_limbs", []))


def _parents_first(view: dict[str, Any]) -> list[str]:
    return sorted(view["bones"], key=lambda b: len(chain(view, b)))


# --------------------------------------------------------------------------- building


@dataclass
class BuiltCharacter:
    group: Group  # flat part groups in draw order + the GUI-only skeleton layer
    bones: list[Bone]  # add these to Canvas.bones (root canvas only)
    by_name: dict[str, Bone]


def _offset_value(base_deg: float, offset: float | Animated | None) -> Angle | Animated:
    """Synfig bone angle = rest angle relative to the parent + the (possibly animated) offset."""
    if offset is None:
        return Angle(base_deg)
    if isinstance(offset, (int, float)):
        return Angle(base_deg + offset)
    return Animated(
        "angle",
        tuple(
            Waypoint(w.frame, Angle(base_deg + w.value.degrees), w.interp) for w in offset.waypoints
        ),
    )


def _origin_value(
    joint_px: Vec, shift: Animated | None, parent_dir: float, space: Space
) -> Vec | Animated:
    """Bone origin in the parent bone's frame (units): the joint, plus an optional animated shift
    (both in the parent art's pixel frame, y up), turned by -parent_dir."""

    def to_bone_frame(v: Vec) -> Vec:
        r = rotate(v, -parent_dir)
        return Vec(space.length(r.x), space.length(r.y))

    if shift is None:
        return to_bone_frame(joint_px)
    return Animated(
        "vector",
        tuple(
            Waypoint(
                w.frame,
                to_bone_frame(Vec(joint_px.x + w.value.x, joint_px.y + w.value.y)),
                w.interp,
            )
            for w in shift.waypoints
        ),
    )


# Skeleton Deformation mesh for a limb drawn vertically (docs/spikes/bending-limbs.md)
LIMB_GRID = (48, 192)
LIMB_REACH = 1.1  # the influence radius is this x the limb's widest half-width


def _limb_half_width_px(path: Path) -> float:
    """Half the widest row of opaque pixels of a limb image."""
    alpha = Image.open(path).convert("RGBA").getchannel("A").point(lambda a: 255 if a > 8 else 0)
    box = alpha.getbbox()
    return 1.0 if box is None else (box[2] - box[0]) / 2


def _build_limb(
    rig: Rig,
    view: dict[str, Any],
    limb: dict[str, Any],
    pose: dict[str, Bone],
    space: Space,
    file_prefix: str,
) -> tuple[Group, list[Bone]]:
    """One limb image + a Skeleton Deformation: a static rest chain (the art as drawn) paired
    with the animated pose chain (the rig's own two bones). Returns the group and the rest bones
    (they go in the canvas skeleton, before any layer)."""
    upper, lower = limb["bones"]
    rest_pose = world_pose(view)
    (up_pos, up_dir), (lo_pos, _) = rest_pose[upper], rest_pose[lower]
    (pw, ph), (px, py), (jx, jy) = limb["size_px"], limb["pivot_px"], limb["joint_px"]
    half_w = _limb_half_width_px(rig.folder / limb["file"])
    width = space.length(half_w * LIMB_REACH)
    to_lower = rotate(Vec(lo_pos.x - up_pos.x, lo_pos.y - up_pos.y), -up_dir)
    upper_len = math.hypot(jx - px, jy - py)
    lower_len = max(math.hypot(cx - jx, cy - jy) for cx in (0, pw) for cy in (0, ph))
    ns = f"{rig.id}:rest:{limb['name']}"
    rest_up = Bone(
        f"{limb['name']} rest {upper}",
        origin=Vec(space.length(up_pos.x), space.length(up_pos.y)),
        angle=Angle(up_dir),
        length=space.length(upper_len),
        namespace=ns,
        width=width,
    )
    rest_lo = Bone(
        f"{limb['name']} rest {lower}",
        parent=rest_up,
        origin=Vec(space.length(to_lower.x), space.length(to_lower.y)),
        angle=Angle(view["bones"][lower]["direction_deg"] - view["bones"][upper]["direction_deg"]),
        length=space.length(lower_len),
        namespace=ns,
        width=width,
    )
    for bone, length in ((pose[upper], upper_len), (pose[lower], lower_len)):
        bone.width = width
        bone.length = space.length(length)
    # The image sits where the art was drawn: its pivot on the rest shoulder.
    origin = Vec(space.length(up_pos.x), space.length(up_pos.y))
    tl = Vec(origin.x - space.length(px), origin.y + space.length(py))
    br = Vec(origin.x + space.length(pw - px), origin.y - space.length(ph - py))
    image = ImportLayer(limb["name"], f"{file_prefix}/{limb['file']}", tl=tl, br=br)
    margin = space.length(10)  # the mesh covers the whole image
    deform = SkeletonDeformation(
        f"{limb['name']} bend",
        pairs=[(rest_up, pose[upper]), (rest_lo, pose[lower])],
        point1=Vec(tl.x - margin, tl.y + margin),
        point2=Vec(br.x + margin, br.y - margin),
        nx=LIMB_GRID[0],
        ny=LIMB_GRID[1],
    )
    return Group(limb["name"], children=[image, deform]), [rest_up, rest_lo]


def build_character(
    rig: Rig,
    view_name: str | None,
    space: Space,
    *,
    file_prefix: str,
    offsets: dict[str, float | Animated] | None = None,
    shifts: dict[str, Animated] | None = None,
    attachments: dict[str, list[Layer]] | None = None,
    bend: bool = True,
) -> BuiltCharacter:
    """Bones + linked parts for one view. `offsets` animate bones (Animated values hold Angle
    offsets from rest). `attachments` adds layers drawn in a part's local frame (units, the
    part's pivot at 0,0, y up, before any rotation), right after that part in the draw order and
    linked to the same bone: the procedural face rides on the head this way. `shifts` move a
    bone's joint: Animated Vec values in art pixels (y up) in the parent part's frame; on the root
    bone they move the whole character. Part paths become `file_prefix/<file>` (relative to the
    .sif). `bend` draws each of the view's `bendable_limbs` as one image bent along its two
    bones (Skeleton Deformation) in place of the parts of those bones; False (or a view without
    limbs) builds exactly the plain two-part rig."""
    view = rig.view(view_name)
    offsets = offsets or {}
    shifts = shifts or {}
    unknown = sorted((set(offsets) | set(shifts)) - set(view["bones"]))
    if unknown:
        raise RigError(f"unknown bones {unknown}; rig {rig.id!r} has {sorted(view['bones'])}")
    attachments = attachments or {}
    stray = sorted(set(attachments) - set(view["parts"]))
    if stray:
        raise RigError(
            f"attachments for unknown parts {stray}; rig {rig.id!r} has {sorted(view['parts'])}"
        )

    bones: dict[str, Bone] = {}
    for name in _parents_first(view):
        spec = view["bones"][name]
        parent = spec["parent"]
        parent_dir = 0.0 if parent is None else view["bones"][parent]["direction_deg"]
        joint_px = Vec(0, 0) if parent is None else joint_vector_px(view, name)
        origin = _origin_value(joint_px, shifts.get(name), parent_dir, space)
        bones[name] = Bone(
            name,
            parent=None if parent is None else bones[parent],
            origin=origin,
            angle=_offset_value(spec["direction_deg"] - parent_dir, offsets.get(name)),
            length=space.length(spec.get("length_px", 1.0)),
            namespace=rig.id,  # .sif bone GUIDs derive from the rig id + bone name
        )

    limbs = bendable_limbs(view) if bend else []
    replaced: set[str] = set()  # parts drawn by their limb instead
    slot: dict[str, list[dict[str, Any]]] = {}  # the part whose draw slot limbs take -> limbs
    for limb in limbs:
        owned = [p for p in view["draw_order"] if view["parts"][p]["bone"] in limb["bones"]]
        replaced.update(owned)
        slot.setdefault(owned[0] if owned else view["draw_order"][-1], []).append(limb)
    rest_bones: list[Bone] = []

    children: list[Layer] = []
    for part_name in view["draw_order"]:
        part = view["parts"][part_name]
        for limb in slot.get(part_name, []):
            group, rest = _build_limb(rig, view, limb, bones, space, file_prefix)
            children.append(group)
            rest_bones.extend(rest)
        if part_name in replaced:  # the limb draws it; keep what is attached to it
            if attachments.get(part_name):
                link = BoneLink(
                    bones[part["bone"]],
                    Transform(angle=Angle(-view["bones"][part["bone"]]["direction_deg"])),
                )
                children.append(
                    Group(
                        f"{part_name} attachments", transform=link, children=attachments[part_name]
                    )
                )
            continue
        bone_spec = view["bones"][part["bone"]]
        image = ImportLayer.with_pivot(
            part_name,
            f"{file_prefix}/{part['file']}",
            tuple(part["size_px"]),
            part["pivot_px"],
            space,
        )
        base = Transform(angle=Angle(-bone_spec["direction_deg"]))
        link = BoneLink(bones[part["bone"]], base)
        children.append(Group(part_name, transform=link, children=[image]))
        if attachments.get(part_name):
            children.append(
                Group(f"{part_name} attachments", transform=link, children=attachments[part_name])
            )
    ordered = list(bones.values())
    children.append(SkeletonLayer(f"{rig.id} skeleton", bones=ordered))
    return BuiltCharacter(Group(f"{rig.id}-rig", children=children), ordered + rest_bones, bones)
