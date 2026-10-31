# ruff: noqa: RUF059
"""Inside Blender: bake JSON -> flat 2D scene -> PNG frames. See __init__.py for the command."""

import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
bake_path, out_dir = Path(argv[0]), Path(argv[1])
opt = dict(zip(argv[2::2], argv[3::2], strict=False)) if "--rigid" not in argv else {}
if "--rigid" in argv:
    i = argv.index("--rigid")
    rest = argv[2:i] + argv[i + 1 :]
    opt = dict(zip(rest[0::2], rest[1::2], strict=False))
ENGINE = opt.get("--engine", "EEVEE")
W, H = (int(v) for v in opt.get("--size", "960x540").split("x"))
RIGID = "--rigid" in argv
SAMPLES = int(opt.get("--samples", "8"))
PX = 0.01  # Blender units per stage pixel
GRID_Y = 40  # limb mesh rows (columns scale with width)

bake = json.loads(bake_path.read_text())
SW, SH = bake["size"]
out_dir.mkdir(parents=True, exist_ok=True)
t_start = time.perf_counter()

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = bake["fps"]
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.image_settings.compression = 3
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.display_settings.display_device = "sRGB"
scene.render.film_transparent = bool(bake.get("transparent"))
if bake.get("transparent"):
    scene.render.image_settings.color_mode = "RGBA"
if ENGINE == "EEVEE":
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = SAMPLES
elif ENGINE == "WORKBENCH":
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.render_aa = "8"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.show_object_outline = False
else:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = False
    scene.cycles.max_bounces = 0
    scene.cycles.filter_width = 1.0

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.ortho_scale = SW * PX / bake["zoom"]
cam_data.clip_start, cam_data.clip_end = 0.1, 100
cam = bpy.data.objects.new("cam", cam_data)
cam.location = (SW * PX / 2, SH * PX / 2, 20)
scene.collection.objects.link(cam)
scene.camera = cam

_images = {}


def image(path):
    if path not in _images:
        _images[path] = bpy.data.images.load(path)
        _images[path].alpha_mode = "STRAIGHT"
    return _images[path]


def material(name, path):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image(path)
    tex.interpolation = "Linear"
    tex.extension = "CLIP"
    emit = nt.nodes.new("ShaderNodeEmission")
    clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
    nt.links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    nt.links.new(clear.outputs[0], mix.inputs[1])
    nt.links.new(emit.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    mat.surface_render_method = "BLENDED"
    mat.use_backface_culling = False
    mat["tex"] = tex.name
    return mat


def grid_mesh(name, left, top, w, h, nx, ny, z=0.0):
    """A textured grid covering an image placed with its top-left at (left, top) (stage px)."""
    verts, uvs, faces = [], [], []
    for j in range(ny + 1):
        for i in range(nx + 1):
            u, v = i / nx, 1 - j / ny
            verts.append((((left + u * w) * PX), ((top - (1 - v) * h) * PX), 0.0))
            uvs.append((u, v))
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append((a, a + 1, a + nx + 2, a + nx + 1))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    uv = mesh.uv_layers.new(name="uv")
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            uv.data[li].uv = uvs[mesh.loops[li].vertex_index]
    mesh.update()
    return mesh, verts


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def limb_weights(rest, upper, lower, half_width, x, y):
    """Weight of the lower bone for a point (character space): 0 above the joint, 1 below,
    a smoothstep across +-R along the limb's rest axis."""
    ux, uy, _ = rest[upper]
    lx, ly, ld = rest[lower]
    axis = Vector((lx - ux, ly - uy)).normalized()
    d = (x - lx) * axis.x + (y - ly) * axis.y
    r = half_width * 0.7
    return smoothstep(-r, r, d)


def build_character(ch, z0):
    cid, rest = ch["id"], ch["rest"]
    # armature: one bone per rig bone, head at the joint, along the rest direction
    arm_data = bpy.data.armatures.new(cid)
    arm = bpy.data.objects.new(cid + "-arm", arm_data)
    scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    order = sorted(ch["bones"], key=lambda b: len(chain(ch, b)))
    for b in order:
        x, y, d = rest[b]
        eb = arm_data.edit_bones.new(b)
        eb.head = (x * PX, y * PX, 0)
        length = max(ch["bones"][b]["length_px"] or 20, 5) * PX
        eb.tail = (
            eb.head.x + length * math.cos(math.radians(d)),
            eb.head.y + length * math.sin(math.radians(d)),
            0,
        )
        eb.roll = 0
        if ch["bones"][b]["parent"]:
            eb.parent = arm_data.edit_bones[ch["bones"][b]["parent"]]
    bpy.ops.object.mode_set(mode="OBJECT")

    if ch.get("skin") and not RIGID:
        return build_skinned(ch, arm, z0)

    limb_owner = {}
    limbs = [] if RIGID else ch["limbs"]
    for limb in limbs:
        for p in ch["parts"]:
            if p["bone"] in limb["bones"]:
                limb_owner[p["name"]] = limb["name"]
    slot, items = {}, []
    for i, p in enumerate(ch["parts"]):
        if p["name"] in limb_owner:
            slot.setdefault(limb_owner[p["name"]], i)
            continue
        items.append((i, "part", p))
    for limb in limbs:
        items.append((slot[limb["name"]], "limb", limb))
    items.sort(key=lambda t: t[0])

    head_obj = None
    mats = {}
    for order_i, (_, kind, item) in enumerate(items):
        rig_dir = Path(ch["rig_dir"])
        w, h = item["size_px"]
        px, py = item["pivot_px"]
        bone = item["bone"] if kind == "part" else item["bones"][0]
        jx, jy, _ = rest[bone]
        left, top = jx - px, jy + py  # image top-left in rest space (y up)
        if kind == "part" and item["name"] in ("head", "torso"):
            nx, ny = 1, 1
        elif kind == "part":
            nx, ny = 2, 2
        else:
            nx, ny = max(4, round(w / 6)), GRID_Y
        mesh, verts = grid_mesh(
            item["name"],
            left * ch["scale"],
            top * ch["scale"],
            w * ch["scale"],
            h * ch["scale"],
            nx,
            ny,
        )
        obj = bpy.data.objects.new(item["name"], mesh)
        obj.location.z = z0 + order_i * 0.01
        scene.collection.objects.link(obj)
        mat = material(item["name"], str(rig_dir / item["file"]))
        mats[item["name"]] = mat
        obj.data.materials.append(mat)
        mod = obj.modifiers.new("arm", "ARMATURE")
        mod.object = arm
        if kind == "part":
            vg = obj.vertex_groups.new(name=bone)
            vg.add(list(range(len(verts))), 1.0, "REPLACE")
        else:
            up, lo = item["bones"]
            hw = w / 2
            g_up, g_lo = obj.vertex_groups.new(name=up), obj.vertex_groups.new(name=lo)
            for vi, (vx, vy, _) in enumerate(verts):
                wl = limb_weights(rest, up, lo, hw, vx / PX, vy / PX)
                g_up.add([vi], 1 - wl, "REPLACE")
                g_lo.add([vi], wl, "REPLACE")
        if kind == "part" and ch.get("face") and item["name"] == ch["face"]["part"]:
            head_obj = (obj, mat)
    return {"arm": arm, "head": head_obj, "data": ch, "mats": mats}


def build_skinned(ch, arm, z0):
    """Spike D-093: one continuous skinned mesh for the whole body (skin.py), plus the rigid head
    sprite on top (it carries the per-frame face)."""
    sk = json.loads(Path(ch["skin"]["mesh"]).read_text())
    verts = [(x * PX, y * PX, 0.0) for x, y in sk["verts"]]
    mesh = bpy.data.meshes.new("skin")
    mesh.from_pydata(verts, [], [tuple(t) for t in sk["tris"]])
    uv = mesh.uv_layers.new(name="uv")
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            uv.data[li].uv = sk["uvs"][mesh.loops[li].vertex_index]
    mesh.update()
    obj = bpy.data.objects.new("skin", mesh)
    obj.location.z = z0
    scene.collection.objects.link(obj)
    obj.data.materials.append(material("skin", ch["skin"]["png"]))
    mod = obj.modifiers.new("arm", "ARMATURE")
    mod.object = arm
    for bone, ws in sk["weights"].items():
        vg = obj.vertex_groups.new(name=bone)
        for vi, wt in ws:
            vg.add([vi], wt, "REPLACE")
    head_obj = None
    if ch.get("face"):
        p = next(p for p in ch["parts"] if p["name"] == ch["face"]["part"])
        jx, jy, _ = ch["rest"][p["bone"]]
        w, h = p["size_px"]
        hm, hv = grid_mesh(
            "head",
            (jx - p["pivot_px"][0]) * ch["scale"],
            (jy + p["pivot_px"][1]) * ch["scale"],
            w * ch["scale"],
            h * ch["scale"],
            1,
            1,
        )
        ho = bpy.data.objects.new("head", hm)
        ho.location.z = z0 + 0.01
        scene.collection.objects.link(ho)
        hmat = material("head", str(Path(ch["rig_dir"]) / p["file"]))
        ho.data.materials.append(hmat)
        hmod = ho.modifiers.new("arm", "ARMATURE")
        hmod.object = arm
        hg = ho.vertex_groups.new(name=p["bone"])
        hg.add(list(range(len(hv))), 1.0, "REPLACE")
        head_obj = (ho, hmat)
    return {"arm": arm, "head": head_obj, "data": ch}


def chain(ch, b):
    out = [b]
    while ch["bones"][out[-1]]["parent"]:
        out.append(ch["bones"][out[-1]]["parent"])
    return out


# background: a textured plane at the back
if not bake.get("transparent"):
    bg = bake["background"]
    bgi = image(bg)
    bw, bh = bgi.size
    bg_mesh, _ = grid_mesh("bg", (SW - bw) / 2, (SH + bh) / 2, bw, bh, 1, 1)
    bg_obj = bpy.data.objects.new("bg", bg_mesh)
    bg_obj.location.z = -1
    bg_obj.data.materials.append(material("bg", bg))
    scene.collection.objects.link(bg_obj)

built = [build_character(ch, 0.1 + i * 2) for i, ch in enumerate(bake["characters"])]
t_built = time.perf_counter()


def pose(built_ch, frame):
    ch, arm = built_ch["data"], built_ch["arm"]
    fr = ch["frames"][frame]
    for b in sorted(ch["bones"], key=lambda b: len(chain(ch, b))):
        x, y, d = fr["bones"][b]
        pb = arm.pose.bones[b]
        rest_rot = pb.bone.matrix_local.to_3x3().to_4x4()
        delta = Matrix.Rotation(math.radians(d - ch["rest"][b][2]), 4, "Z")
        pb.matrix = Matrix.Translation((x * PX, y * PX, 0)) @ delta @ rest_rot
        bpy.context.view_layer.update()
    if built_ch["head"] and "head" in fr:
        obj, mat = built_ch["head"]
        mat.node_tree.nodes[mat["tex"]].image = image(fr["head"])
    for name, path in fr.get("part_images", {}).items():  # a turned head's hair (D-097)
        m = built_ch.get("mats", {}).get(name)
        if m:
            m.node_tree.nodes[m["tex"]].image = image(path)


first, last = 0, bake["n_frames"] - 1
if "--frames" in opt:
    a, _, b = opt["--frames"].partition("-")
    first, last = int(a), int(b or a)
times = []
for f in range(first, last + 1):
    t0 = time.perf_counter()
    for bc in built:
        pose(bc, f)
    if bake.get("camera_track"):  # per-frame zoom and centre (stage px, y up in Blender units)
        zoom, ccx, ccy = bake["camera_track"][f]
        cam_data.ortho_scale = SW * PX / zoom
        cam.location = (ccx * PX, (SH - ccy) * PX, 20)
    scene.render.filepath = str(out_dir / f"{f:04d}.png")
    bpy.ops.render.render(write_still=True)
    times.append(time.perf_counter() - t0)

stats = {
    "frames": len(times),
    "build_s": round(t_built - t_start, 2),
    "render_total_s": round(sum(times), 2),
    "s_per_frame": round(sum(times) / len(times), 3),
    "first_frame_s": round(times[0], 3),
    "render_engine": scene.render.engine,
}
(out_dir / "stats.json").write_text(json.dumps(stats))
print("STATS", stats)
