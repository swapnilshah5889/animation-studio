"""Rowan front-only rig test (D-107), stage 2: stack the painted layers in Blender and animate 6 s.

    blender -b --factory-startup --python scripts/spikes/rowan_rig_blend.py -- <layers_dir> <frames_dir>

Flat painted layers in depth (2.5D): a wide plate far behind, Rowan's body and head as separate planes, swap
patches for blinks and mouth shapes, a second body drawing with the raised arm for the wave. Unlit (emission)
so the watercolour keeps its exact colours; a perspective camera pushes in, so the plate shifts against Rowan.
Layer pixels map 1 px = 1 mm, with the canonical's top-left at x=0, z=0 and image y going down to -z.
"""

import math
import sys
from pathlib import Path

import bpy

FPS, FRAMES = 24, 144
PX = 0.001  # metres per canonical pixel
CANON_W, CANON_H = 832, 1216


def t2f(t: float) -> int:
    return 1 + round(t * FPS)


def plane(name: str, image: Path, w_px: int, h_px: int, depth: float, parent=None, pivot=None):
    """A plane showing `image`, its top-left at canonical (0, 0); `pivot` (px) sets its origin."""
    bpy.ops.mesh.primitive_plane_add(size=1)
    ob = bpy.context.object
    ob.name = name
    ob.rotation_euler = (math.pi / 2, 0, 0)  # face the camera on -Y
    bpy.ops.object.transform_apply(rotation=True)
    ob.scale = (w_px * PX, 1, h_px * PX)
    bpy.ops.object.transform_apply(scale=True)
    ob.location = (w_px * PX / 2, depth, -h_px * PX / 2)
    bpy.ops.object.transform_apply(location=True)  # mesh now spans canonical (0..w, 0..-h)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.surface_render_method = "DITHERED"  # depth-tested; BLENDED sorts by origin and hid the mouths
    nt = mat.node_tree
    nt.nodes.clear()
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(image))
    tex.interpolation = "Cubic"
    em = nt.nodes.new("ShaderNodeEmission")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])
    nt.links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    ob.data.materials.append(mat)
    if pivot is not None:  # move the origin to the pivot without moving the picture
        px, pz = pivot[0] * PX, -pivot[1] * PX
        ob.data.transform(__import__("mathutils").Matrix.Translation((-px, 0, -pz)))
        ob.location = (px, 0, pz)
    if parent is not None:
        bpy.context.view_layer.update()  # matrix_world is stale until the depsgraph updates
        world = ob.matrix_world.copy()
        ob.parent = parent
        ob.matrix_world = world
    return ob


def show(ob, keys: list[tuple[float, bool]]) -> None:
    """Visibility swaps (drawing replacement), held: constant interpolation."""
    for t, on in keys:
        ob.hide_render = not on
        ob.keyframe_insert("hide_render", frame=t2f(t))
    for fc in (
        ob.animation_data.action.fcurves if hasattr(ob.animation_data.action, "fcurves") else []
    ):
        for kp in fc.keyframe_points:
            kp.interpolation = "CONSTANT"


def key(ob, path: str, index: int, items: list[tuple[float, float]]) -> None:
    for t, v in items:
        getattr(ob, path)[index] = v
        ob.keyframe_insert(path, index=index, frame=t2f(t))


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    lay, out = Path(argv[0]), Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc = bpy.context.scene
    for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            pass
    sc.view_settings.view_transform = "Standard"
    sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
    sc.render.fps, sc.frame_start, sc.frame_end = FPS, 1, FRAMES
    if "--range" in argv:  # render a few frames only, for a quick check
        i = argv.index("--range")
        sc.frame_start, sc.frame_end = int(argv[i + 1]), int(argv[i + 2])
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = str(out / "f_")
    sc.world = bpy.data.worlds.new("w")
    sc.world.color = (0.94, 0.92, 0.86)

    # Rig root: everything of Rowan hangs from it (idle sway moves him as one).
    root = bpy.data.objects.new("rowan", None)
    sc.collection.objects.link(root)
    hip = (380, 700)  # breathing pivot (waist), in canonical px
    # One body drawing with no hanging arm, and ONE arm part that is always shown and only rotates: any
    # swap or cross-fade between two arm drawings read as a pop or a dissolve (reviews 4 and 5).
    body_wave = plane("body_wave", lay / "body_wave.png", CANON_W, CANON_H, 0.0, root, hip)
    arm = plane("arm_wave", lay / "arm_wave.png", CANON_W, CANON_H, -0.002, body_wave, (505, 425))
    neck = (345, 365)
    head = plane("head", lay / "head.png", CANON_W, CANON_H, -0.006, body_wave, neck)
    eyes = plane("eyes_closed", lay / "eyes_closed.png", CANON_W, CANON_H, -0.008, head)
    # Every overlay gets its own depth: coplanar patches z-fought into a black mouth (review 2).
    mouths = {
        n: plane(f"mouth_{n}", lay / f"mouth_{n}.png", CANON_W, CANON_H, -0.010 - 0.001 * i, head)
        for i, n in enumerate(("A", "O", "smile"))
    }

    # The plate: 2 m behind Rowan, scaled up so it fills the wide frame (1824x1024 at 0.7 of canonical scale).
    plate_w, plate_h, k = 1824 / 0.7, 1024 / 0.7, 1.6
    plate = plane("plate", lay / "plate.png", round(plate_w), round(plate_h), 0.0)
    plate.scale = (k, 1, k)
    plate.location = (416 * PX - plate_w * k * PX / 2, 2.0, -620 * PX + plate_h * k * PX / 2)

    # Soft contact shadow under the boots.
    bpy.ops.mesh.primitive_circle_add(vertices=48, radius=1, fill_type="NGON")
    sh = bpy.context.object
    sh.name = "shadow"
    sh.rotation_euler = (math.pi / 2, 0, 0)
    sh.scale = (0.17, 0.022, 1)
    sh.location = (385 * PX, 0.003, -1165 * PX)
    m = bpy.data.materials.new("shadow")
    m.use_nodes = True
    m.surface_render_method = "DITHERED"  # depth-tested; BLENDED sorts by origin and hid the mouths
    nt = m.node_tree
    nt.nodes.clear()
    em, tr, mix, o = (
        nt.nodes.new(t)
        for t in (
            "ShaderNodeEmission",
            "ShaderNodeBsdfTransparent",
            "ShaderNodeMixShader",
            "ShaderNodeOutputMaterial",
        )
    )
    em.inputs["Color"].default_value = (0.25, 0.22, 0.12, 1)
    mix.inputs["Fac"].default_value = 0.35
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], o.inputs["Surface"])
    sh.data.materials.append(m)
    sh.parent = root

    # --- Acting (seconds) ---
    # Breathing: a slow, small stretch of the torso; the head rides on it.
    for b in (body_wave,):
        key(
            b,
            "scale",
            2,
            [(t / 4, 1 + 0.007 * math.sin(2 * math.pi * (t / 4) / 3.2)) for t in range(0, 25)],
        )
    # Idle sway of the whole figure, a few pixels.
    key(root, "location", 0, [(0, 0), (2.0, 0.003), (4.0, -0.002), (6.0, 0.001)])
    # Head tilt: lean in with interest, then back, then a small opposite tilt while talking.
    tilt = [
        (0, 0),
        (0.5, 0),
        (1.4, math.radians(-3)),
        (2.8, math.radians(-3)),
        (3.4, math.radians(1.5)),
        (5.0, math.radians(2)),
        (5.8, 0),
    ]
    key(head, "rotation_euler", 1, tilt)
    # Wave: the arm hangs at the side (turned 152 degrees clockwise, as seen from the camera, from its
    # raised drawing), rises over 0.5 s with an ease and a small overshoot, waves at about 2 Hz, and
    # lowers over 0.5 s back to the side.
    down = math.radians(152)
    swing = [(0, down), (1.5, down), (2.0, math.radians(-8)), (2.12, 0)]
    for t, a in ((2.32, 9), (2.52, -9), (2.72, 0)):
        swing.append((t, math.radians(a)))
    swing += [(3.22, down), (6.0, down)]
    key(arm, "rotation_euler", 1, swing)
    # Blinks: closed lids for 3 frames.
    blinks = [1.1, 2.3, 4.7]
    vis = [(0, False)]
    for b in blinks:
        vis += [(b, True), (b + 3 / FPS, False)]
    show(eyes, vis)
    # Talking, 3.2-4.6 s, mouth shapes held on twos and threes; a smile to finish.
    talk = [
        (3.2, "A"),
        (3.33, "O"),
        (3.45, None),
        (3.55, "A"),
        (3.7, "A"),
        (3.83, None),
        (3.95, "O"),
        (4.1, "A"),
        (4.25, None),
        (4.35, "A"),
        (4.5, None),
        (4.9, "smile"),  # after the 4.7 s blink, not during it
    ]
    for n, ob in mouths.items():
        show(ob, [(0, False)] + [(t, shape == n) for t, shape in talk])

    # Camera: perspective push-in from full figure to a medium shot.
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.lens = 50
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.rotation_euler = (math.pi / 2, 0, 0)
    # Ends a little wider and higher than first tried: review 1 found the cap touching the top edge.
    key(cam, "location", 1, [(0, -3.21), (1.0, -3.21), (5.6, -2.35), (6.0, -2.35)])
    key(cam, "location", 2, [(0, -0.63), (1.0, -0.63), (5.6, -0.47), (6.0, -0.47)])
    key(cam, "location", 0, [(0, 0.385), (6.0, 0.385)])
    for fc in (
        cam.animation_data.action.fcurves if hasattr(cam.animation_data.action, "fcurves") else []
    ):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
    if "--check" in argv:  # print where things are instead of rendering
        from mathutils import Vector

        sc.frame_set(1)
        for ob in (body_wave, head, plate, cam):
            pts = (
                [ob.matrix_world @ Vector(c) for c in ob.bound_box]
                if ob.type == "MESH"
                else [ob.location]
            )
            lo = [round(min(p[i] for p in pts), 3) for i in range(3)]
            hi = [round(max(p[i] for p in pts), 3) for i in range(3)]
            print(
                "CHECK",
                ob.name,
                lo,
                hi,
                [round(math.degrees(a)) for a in ob.matrix_world.to_euler()],
            )
        return
    bpy.ops.render.render(animation=True)
    print("ROWAN_RIG_OK", out)


main()
