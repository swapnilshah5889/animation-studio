"""Bendable limbs from the cut parts, engine-neutral: the upper and lower part of a limb pasted
into ONE image in the rest pose (what `bendable_limbs` in rig.schema.json describes).

The part PNGs already overlap at the joint (the lower part carries a cap of the figure's own
pixels), so pasting them in draw order gives one continuous drawing; an engine then bends that
single image along the two bones instead of showing two rigid pieces.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from studio_core.rig import world_pose

LIMB_ROLES = (("thigh", "shin"), ("upper_arm", "forearm"))


def limb_pairs(view: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(name, upper bone, lower bone) for every two-bone limb of the view."""
    out = []
    for upper, spec in view["bones"].items():
        for up_role, lo_role in LIMB_ROLES:
            if spec.get("role") != up_role:
                continue
            for lower, lspec in view["bones"].items():
                if lspec.get("parent") == upper and lspec.get("role") == lo_role:
                    out.append((f"{up_role}_{spec.get('side', 'c')}", upper, lower))
    return out


def add_bendable_limbs(rig_dir: Path, view_name: str = "front") -> list[dict[str, Any]]:
    """Write limb images into `rig_dir/limbs/` and `bendable_limbs` into the rig's view.
    Idempotent: the same inputs give the same files. Returns the limb entries."""
    rig_path = rig_dir / "rig.json"
    data = json.loads(rig_path.read_text())
    view = data["views"][view_name]
    rest = world_pose(view)
    (rig_dir / "limbs").mkdir(exist_ok=True)
    limbs = []
    for name, upper, lower in limb_pairs(view):
        owned = [p for p in view["draw_order"] if view["parts"][p]["bone"] in (upper, lower)]
        # each part's top-left corner in rest space (x right, y up); parts are drawn unrotated
        boxes = {}
        for p in owned:
            part = view["parts"][p]
            joint = rest[part["bone"]][0]
            w, h = part["size_px"]
            px, py = part["pivot_px"]
            boxes[p] = (joint.x - px, joint.y + py, w, h)  # left, top (y up), size
        left = min(b[0] for b in boxes.values())
        top = max(b[1] for b in boxes.values())
        right = max(b[0] + b[2] for b in boxes.values())
        bottom = min(b[1] - b[3] for b in boxes.values())
        w, h = round(right - left), round(top - bottom)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for p in owned:
            img = Image.open(rig_dir / view["parts"][p]["file"]).convert("RGBA")
            x, y = round(boxes[p][0] - left), round(top - boxes[p][1])
            canvas.alpha_composite(img, (x, y))
        file = f"limbs/{view_name}_{name}.png"
        canvas.save(rig_dir / file)
        up_joint, lo_joint = rest[upper][0], rest[lower][0]
        limbs.append(
            {
                "name": f"{view_name}_{name}",
                "bones": [upper, lower],
                "file": file,
                "size_px": [w, h],
                "pivot_px": [round(up_joint.x - left, 1), round(top - up_joint.y, 1)],
                "joint_px": [round(lo_joint.x - left, 1), round(top - lo_joint.y, 1)],
            }
        )
    view["bendable_limbs"] = limbs
    rig_path.write_text(json.dumps(data, indent=2) + "\n")
    return limbs
