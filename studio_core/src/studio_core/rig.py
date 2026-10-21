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

from studio_core.schema import validate
from studio_core.sif import (
    Angle,
    Animated,
    Bone,
    BoneLink,
    Group,
    ImportLayer,
    Layer,
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
                for p in v["parts"].values()
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


def build_character(
    rig: Rig,
    view_name: str | None,
    space: Space,
    *,
    file_prefix: str,
    offsets: dict[str, float | Animated] | None = None,
    extra_layers: dict[str, list[Layer]] | None = None,
) -> BuiltCharacter:
    """Bones + linked parts for one view. `offsets` animate bones (Animated values hold Angle
    offsets from rest). `extra_layers` adds layers right after a part (e.g. the face over the
    head) that follow that part's bone. Part paths become `file_prefix/<file>` (relative to the
    .sif)."""
    view = rig.view(view_name)
    offsets = offsets or {}
    unknown = sorted(set(offsets) - set(view["bones"]))
    if unknown:
        raise RigError(f"unknown bones {unknown}; rig {rig.id!r} has {sorted(view['bones'])}")

    bones: dict[str, Bone] = {}
    for name in _parents_first(view):
        spec = view["bones"][name]
        parent = spec["parent"]
        parent_dir = 0.0 if parent is None else view["bones"][parent]["direction_deg"]
        origin = Vec(0, 0)
        if parent is not None:
            v = rotate(joint_vector_px(view, name), -parent_dir)
            origin = Vec(space.length(v.x), space.length(v.y))
        bones[name] = Bone(
            name,
            parent=None if parent is None else bones[parent],
            origin=origin,
            angle=_offset_value(spec["direction_deg"] - parent_dir, offsets.get(name)),
            length=space.length(spec.get("length_px", 1.0)),
            namespace=rig.id,
        )

    children: list[Layer] = []
    for part_name in view["draw_order"]:
        part = view["parts"][part_name]
        bone_spec = view["bones"][part["bone"]]
        image = ImportLayer.with_pivot(
            part_name,
            f"{file_prefix}/{part['file']}",
            tuple(part["size_px"]),
            part["pivot_px"],
            space,
        )
        base = Transform(angle=Angle(-bone_spec["direction_deg"]))
        children.append(
            Group(part_name, transform=BoneLink(bones[part["bone"]], base), children=[image])
        )
        for extra in (extra_layers or {}).get(part_name, []):
            children.append(extra)
    ordered = list(bones.values())
    children.append(SkeletonLayer(f"{rig.id} skeleton", bones=ordered))
    return BuiltCharacter(Group(f"{rig.id}-rig", children=children), ordered, bones)
