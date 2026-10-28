"""Synfig bones: a skeleton in the root canvas, and parts linked to bones.

Format (verified against the v1.5.5 source and by render tests, see synfig-format.md "Bones"):

- `<bones>` sits in the **root** canvas, before any layer, and starts with the global `bone_root`.
- Each bone: name, parent (a `bone_valuenode` reference by GUID), origin (in the parent bone's
  local space), angle (relative to the parent), scalex, length. A bone's local frame has +x along
  the bone.
- A part follows a bone when its group's `transformation` is a `bone_link`:
  `value = bone_matrix ∘ base_value`. `base_value` places the art in the bone's local frame
  (e.g. rotate an image that hangs downwards so it lies along +x).

GUIDs only need to be unique within a file; we derive them from the bone's qualified name, so the
same rig always produces the same XML.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from studio_core.sif.values import Angle, Animated, Transform, Vec, value_xml

ROOT_GUID = hashlib.md5(b"animation-studio:bone_root").hexdigest().upper()


@dataclass(eq=False)
class Bone:
    name: str
    parent: Bone | None = None
    origin: Vec | Animated = field(default_factory=lambda: Vec(0, 0))  # in the parent's space
    angle: Angle | Animated = field(default_factory=lambda: Angle(0))  # relative to the parent
    length: float = 1.0  # drawing / GUI only
    scalex: float = 1.0  # scales this bone and its children
    namespace: str = ""  # e.g. the character id, so two puppets never share GUIDs
    width: float | None = None  # influence radius (units) when a Skeleton Deformation uses the bone

    @property
    def guid(self) -> str:
        return (
            hashlib.md5(f"animation-studio:{self.namespace}:{self.name}".encode())
            .hexdigest()
            .upper()
        )

    def ref(self) -> ET.Element:
        """A handle to this bone (used for `parent` and in `bone_link`)."""
        return ET.Element("bone_valuenode", type="bone_object", guid=self.guid)

    def to_xml(self) -> ET.Element:
        el = ET.Element("bone", type="bone_object", guid=self.guid)
        ET.SubElement(el, "name").append(value_xml(self.name))
        parent = ET.SubElement(el, "parent")
        if self.parent is None:
            parent.append(ET.Element("bone_valuenode", type="bone_object", guid=ROOT_GUID))
        else:
            parent.append(self.parent.ref())
        ET.SubElement(el, "origin").append(value_xml(self.origin))
        ET.SubElement(el, "angle").append(value_xml(self.angle))
        ET.SubElement(el, "scalex").append(value_xml(float(self.scalex)))
        ET.SubElement(el, "length").append(value_xml(float(self.length)))
        if self.width is not None:  # tags only for deformation bones: other rigs stay unchanged
            for tag in ("width", "tipwidth"):
                ET.SubElement(el, tag).append(value_xml(float(self.width)))
        return el


def ordered(bones: list[Bone]) -> list[Bone]:
    """Parents before children (stable), and fail fast on a parent that is not in the list."""
    names = {id(b) for b in bones}
    for b in bones:
        if b.parent is not None and id(b.parent) not in names:
            raise ValueError(f"bone {b.name!r} has a parent {b.parent.name!r} outside the skeleton")
    done: list[Bone] = []
    pending = list(bones)
    while pending:
        progressed = False
        for b in list(pending):
            if b.parent is None or b.parent in done:
                done.append(b)
                pending.remove(b)
                progressed = True
        if not progressed:
            raise ValueError(f"bone cycle among {[b.name for b in pending]}")
    return done


def bones_xml(bones: list[Bone]) -> ET.Element:
    el = ET.Element("bones")
    ET.SubElement(el, "bone_root", type="bone_object", guid=ROOT_GUID)
    for bone in ordered(bones):
        el.append(bone.to_xml())
    return el


@dataclass(frozen=True)
class BoneLink:
    """A group transformation that follows a bone. `base` places the art in the bone's frame."""

    bone: Bone
    base: Transform = field(default_factory=Transform)

    def to_xml(self) -> ET.Element:
        el = ET.Element("bone_link", type="transformation")
        ET.SubElement(el, "bone").append(self.bone.ref())
        ET.SubElement(el, "base_value").append(value_xml(self.base))
        for flag in ("translate", "rotate", "skew", "scale_x", "scale_y"):
            ET.SubElement(el, flag).append(value_xml(True))
        return el
