"""Check a .sif file before rendering it.

The Synfig CLI fails badly on some mistakes: it aborts (bones after layers), refuses the file
with a cryptic message (a missing bone link), or renders a part blank and exits 0 (a missing
PNG). This validator catches them up front with readable messages. It parses the file itself,
so it also checks .sif files edited by hand in Synfig Studio.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

BONE_LINKS = ("name", "parent", "origin", "angle", "scalex", "length")
BONE_LINK_PARTS = ("bone", "base_value", "translate", "rotate", "skew", "scale_x", "scale_y")


def validate_sif(path: Path) -> list[str]:
    """Problems found in the file; [] means it is safe to render."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"not well-formed XML: {exc}"]
    if root.tag != "canvas":
        return [f"root element is <{root.tag}>, expected <canvas>"]
    issues: list[str] = []

    # <bones>: root canvas only, before every layer.
    children = list(root)
    bones_idx = [i for i, el in enumerate(children) if el.tag == "bones"]
    layer_idx = [i for i, el in enumerate(children) if el.tag == "layer"]
    if len(bones_idx) > 1:
        issues.append("more than one <bones> section")
    if bones_idx and layer_idx and bones_idx[0] > layer_idx[0]:
        issues.append("<bones> must come before the first <layer> (the CLI aborts otherwise)")
    for inline in root.iter("canvas"):
        if inline is not root and inline.find("bones") is not None:
            issues.append("an inline canvas has a <bones> section; bones belong in the root canvas")

    defined: dict[str, str] = {}
    bones_el = children[bones_idx[0]] if bones_idx else None
    if bones_el is not None:
        roots = bones_el.findall("bone_root")
        if len(roots) != 1:
            issues.append(f"<bones> needs exactly one <bone_root>, found {len(roots)}")
        for r in roots:
            defined[r.get("guid", "")] = "bone_root"
        for bone in bones_el.findall("bone"):
            guid = bone.get("guid", "")
            name_el = bone.find("name/string")
            name = name_el.text if name_el is not None else "?"
            if guid in defined:
                issues.append(f"duplicate bone GUID {guid} ({name!r} and {defined[guid]!r})")
            defined[guid] = name or "?"
            missing = [link for link in BONE_LINKS if bone.find(link) is None]
            if missing:
                issues.append(f"bone {name!r} is missing {missing}")

    # Every reference to a bone must resolve.
    for ref in root.iter("bone_valuenode"):
        guid = ref.get("guid", "")
        if guid not in defined:
            issues.append(f"reference to undefined bone GUID {guid}")
    for container in list(root.iter("layer")):
        for ref in container.iter("bone"):  # inside layers <bone> is a reference by GUID
            if len(ref) == 0 and ref.get("guid", "") not in defined:
                issues.append(
                    f"layer {container.get('desc')!r} refers to undefined bone {ref.get('guid')}"
                )
    for link in root.iter("bone_link"):
        missing = [p for p in BONE_LINK_PARTS if link.find(p) is None]
        if missing:
            issues.append(f"<bone_link> is missing {missing}")
        if not link.get("type"):
            issues.append('<bone_link> is missing its type attribute (e.g. type="transformation")')

    # Imported images must exist (missing ones render blank without an error).
    for layer in root.iter("layer"):
        if layer.get("type") != "import":
            continue
        name_el = layer.find("param[@name='filename']/string")
        if name_el is None or not (name_el.text or "").strip():
            issues.append(f"import layer {layer.get('desc')!r} has no filename")
            continue
        file = Path(name_el.text)
        target = file if file.is_absolute() else path.parent / file
        if not target.is_file():
            issues.append(f"import layer {layer.get('desc')!r}: image not found: {name_el.text}")
    return sorted(set(issues), key=issues.index)
