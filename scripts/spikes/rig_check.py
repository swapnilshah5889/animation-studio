"""Rig check for a downloaded character .blend (STEP-SLICE task 1). Safe to re-run.

Run headless (autoexec stays off: the rig's bundled UI script is not needed to inspect or render):
    blender -b <rig.blend> --python scripts/spikes/rig_check.py -- <out_dir> <name>

Writes <out_dir>/<name>_report.json (armatures, bone counts, face and mouth controls, shape keys) and
<out_dir>/<name>_front.png and <name>_three_quarter.png, rendered with EEVEE at 960x540.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

FACE_WORDS = ("mouth", "lip", "jaw", "teeth", "tongue", "eye", "lid", "brow", "cheek", "nose", "smile")


def report(name: str) -> dict:
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    out = {"blender": bpy.app.version_string, "file": bpy.data.filepath, "armatures": []}
    for a in arms:
        bones = [b.name for b in a.data.bones]
        face = sorted(b for b in bones if any(w in b.lower() for w in FACE_WORDS))
        out["armatures"].append({"name": a.name, "bones": len(bones), "face_bones": len(face), "face_sample": face[:40]})
    keys = {}
    for m in meshes:
        sk = m.data.shape_keys
        if sk and len(sk.key_blocks) > 1:
            keys[m.name] = [k.name for k in sk.key_blocks][:40]
    out["meshes"] = len(meshes)
    out["shape_keys"] = keys
    out["actions"] = [a.name for a in bpy.data.actions][:20]
    out["text_blocks"] = [t.name for t in bpy.data.texts]
    return out


def visible_bounds() -> tuple[Vector, Vector]:
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    dg = bpy.context.evaluated_depsgraph_get()
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or o.hide_render or not o.visible_get():
            continue
        e = o.evaluated_get(dg)
        for c in e.bound_box:
            w = e.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def set_eevee(scene) -> str:
    for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = eng
            return eng
        except TypeError:
            continue
    return scene.render.engine


def render(out_dir: Path, name: str) -> dict:
    scene = bpy.context.scene
    engine = set_eevee(scene)
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.film_transparent = False
    lo, hi = visible_bounds()
    centre, size = (lo + hi) / 2, hi - lo
    height = max(size.z, 0.1)
    cam_data = bpy.data.cameras.new("check_cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("check_cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    light = bpy.data.objects.new("check_key", bpy.data.lights.new("check_key", "SUN"))
    light.data.energy = 3.0
    light.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(light)
    dist = height * 1.6 / (36 / 50) + 0.5
    shots = {}
    for label, yaw in (("front", 0.0), ("three_quarter", 35.0)):
        a = math.radians(yaw)
        # Blender characters face -Y by convention, so the camera sits on -Y looking at +Y.
        cam.location = centre + Vector((math.sin(a) * dist, -math.cos(a) * dist, 0))
        direction = centre - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        path = out_dir / f"{name}_{label}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        shots[label] = str(path)
    return {"engine": engine, "bounds_m": [round(v, 3) for v in size], "renders": shots}


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    out_dir, name = Path(argv[0]), argv[1]
    out_dir.mkdir(parents=True, exist_ok=True)
    data = report(name)
    data["render"] = render(out_dir, name)
    (out_dir / f"{name}_report.json").write_text(json.dumps(data, indent=1))
    print("RIG_CHECK_OK", out_dir / f"{name}_report.json")


main()
