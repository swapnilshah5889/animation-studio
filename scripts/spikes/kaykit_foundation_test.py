"""KayKit foundation fix pass (D-108, docs/steps/STEP-KAYKIT-FOUNDATION-FIX.md).

    blender -b --factory-startup --python scripts/spikes/kaykit_foundation_test.py -- \
        <asset_dir> <out_dir> [--stills 1,40,70,113] [--render]

Walk, stop, wave, head turn. KayKit Rogue (CC0) on Rig_Medium, driven only by the asset's own
actions in the NLA: Idle_A as the base, Walking_A fading out into it, an upper-body copy of Waving
fading in and out (the raise and lower), and a four-key additive head turn on the `head` bone.
Code decides the timing:
- the walk exit is the cycle window whose feet are closest to the idle stance;
- quaternion keys share Idle_A's hemisphere, so blends never flip a limb (the old stop pop);
- the walk's travel comes from the planted foot each frame (object translation only).
Hand route A: the right fist is hidden by a mask on a vertex group (source files untouched) and
replaced by a rigid low-poly open-mitten hand weighted 100% to `hand.r`.
Look: smooth normals (the head's from a sphere), a two-step toon ramp, Freestyle on silhouettes,
contours and material edges only, and a hard sun shadow. Prints CHECK lines for the walk-stop gate.
"""

import contextlib
import math
import os
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

FPS = 24
CYCLE = 25  # Walking_A length in frames
WALK_CYCLES = 2  # roughly how long the walk lasts before the stop window
STOP_BLEND = 10
WAVE_LEN, WAVE_BLEND = 51, 10
HEAD_KEYS = ((0, 0.0), (9, 40.0), (16, 40.0), (26, 0.0))  # (offset, yaw degrees) on the head bone
PLANT_Z = 0.16  # a foot bone below this height counts as planted

ARGS = sys.argv[sys.argv.index("--") + 1 :]
ASSET, OUT = Path(ARGS[0]), Path(ARGS[1])
RENDER = "--render" in ARGS
STILLS = [int(x) for x in ARGS[ARGS.index("--stills") + 1].split(",")] if "--stills" in ARGS else []
CHAR = ASSET / "adventurers/KayKit_Adventurers_2.0_FREE/Characters/gltf/Rogue.glb"
ANIMS = ASSET / "animations/KayKit_Character_Animations_1.1/Animations/gltf/Rig_Medium"


def load() -> bpy.types.Object:
    """Import the Rogue and the Rig_Medium action files; keep only the character and the actions."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(CHAR))
    rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.parent is None:  # stray helper sphere shipped in the glb
            bpy.data.objects.remove(o)
    for name in (
        "Rig_Medium_General.glb",
        "Rig_Medium_MovementBasic.glb",
        "Rig_Medium_Simulation.glb",
    ):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(ANIMS / name))
        for o in set(bpy.data.objects) - before:
            bpy.data.objects.remove(o)
    for a in bpy.data.actions:
        a.use_fake_user = True
    for name in ("Walking_A", "Waving"):
        action = bpy.data.actions[name]
        start, end = action.frame_range  # Walking_A is 25.6 frames long at 24 fps
        n = align_quaternions(action, bpy.data.actions["Idle_A"])
        action.use_frame_range = True  # pin the authored range; edited handles must not stretch it
        action.frame_start, action.frame_end = start, end
        print(f"CHECK {name}: {n} quaternion keys moved to Idle_A's hemisphere")
    rig.animation_data_create()
    rig.animation_data.action = None
    return rig


def fcurves(action: bpy.types.Action):
    """F-curves of a (layered, Blender 4.4+) action's first slot, or of a legacy action."""
    try:
        return action.layers[0].strips[0].channelbag(action.slots[0]).fcurves
    except (AttributeError, IndexError):
        return action.fcurves


def align_quaternions(action: bpy.types.Action, ref: bpy.types.Action) -> int:
    """Keep rotation keys in `ref`'s hemisphere (q and -q are the same rotation).

    The NLA blends quaternion components linearly; keys on opposite hemispheres blend through a
    near-zero quaternion and the limb flips for a frame (the leg pop at the walk-to-idle stop).
    Returns the number of keys negated."""
    ref_q: dict[str, list[float]] = {}
    for fc in fcurves(ref):
        if fc.data_path.endswith("rotation_quaternion"):
            ref_q.setdefault(fc.data_path, [1.0, 0.0, 0.0, 0.0])[fc.array_index] = fc.evaluate(
                ref.frame_range[0]
            )
    groups: dict[str, dict[int, bpy.types.FCurve]] = {}
    for fc in fcurves(action):
        if fc.data_path in ref_q:
            groups.setdefault(fc.data_path, {})[fc.array_index] = fc
    flipped = 0
    for path, comps in groups.items():
        if len(comps) != 4:
            continue
        prev_q = ref_q[path]  # first key follows ref, every later key follows the key before it
        for i in range(len(comps[0].keyframe_points)):
            q = [comps[c].keyframe_points[i].co[1] for c in range(4)]
            if sum(a * b for a, b in zip(q, prev_q, strict=True)) < 0:
                q = [-x for x in q]
                for c in range(4):
                    kp = comps[c].keyframe_points[i]
                    kp.co[1], kp.handle_left[1], kp.handle_right[1] = (
                        -kp.co[1],
                        -kp.handle_left[1],
                        -kp.handle_right[1],
                    )
                flipped += 1
            prev_q = q
        for fc in comps.values():
            fc.update()
    return flipped


LOWER_BODY = ("root", "hips", "upperleg", "lowerleg", "foot", "toes")


def upper_body_copy(action: bpy.types.Action) -> bpy.types.Action:
    """Copy of `action` without root, hips and leg channels; the layer below keeps the feet."""
    copy = action.copy()
    copy.name = f"{action.name}_Upper"
    curves = fcurves(copy)
    for fc in list(curves):
        bone = fc.data_path.split('"')[1] if '"' in fc.data_path else ""
        if bone.split(".")[0] in LOWER_BODY:
            curves.remove(fc)
    return copy


def feet_local(rig: bpy.types.Object, action: bpy.types.Action, frame: float) -> dict[str, Vector]:
    """Foot and toe heads in rig space with one action applied directly (no NLA)."""
    rig.animation_data.action = action
    with contextlib.suppress(AttributeError, IndexError):
        rig.animation_data.action_slot = action.slots[0]
    length = action.frame_range[1] - action.frame_range[0]
    t = frame * length / CYCLE if action.name == "Walking_A" else frame  # walk is scaled to CYCLE
    bpy.context.scene.frame_set(int(t), subframe=t - int(t))
    pts = {n: rig.pose.bones[n].head.copy() for n in ("foot.l", "foot.r", "toes.l", "toes.r")}
    rig.animation_data.action = None
    return pts


def pick_walk_exit(rig: bpy.types.Object) -> int:
    """Cycle frame where the stop blend should end: the window whose feet best match Idle_A."""
    idle = feet_local(rig, bpy.data.actions["Idle_A"], 0)
    walk = [feet_local(rig, bpy.data.actions["Walking_A"], f) for f in range(CYCLE)]

    def cost(end: int) -> float:
        total = 0.0
        for k in range(STOP_BLEND + 1):
            w = k / STOP_BLEND  # later frames in the blend matter more
            pose = walk[(end - STOP_BLEND + k) % CYCLE]
            total += w * sum((pose[n] - idle[n]).length for n in pose)
        return total

    return min(range(CYCLE), key=cost)


def strip(rig, name, action, start, blend_in=0, blend_out=0, repeat=1.0, mode="REPLACE"):
    track = rig.animation_data.nla_tracks.new()
    track.name = name
    s = track.strips.new(name, int(start), action)
    with contextlib.suppress(AttributeError, IndexError):
        s.action_slot = action.slots[0]
    s.repeat = repeat
    s.blend_in, s.blend_out = blend_in, blend_out
    s.blend_type = mode
    s.extrapolation = "NOTHING"
    return s


def build_motion(rig: bpy.types.Object) -> tuple[int, int]:
    """Lay out the NLA. Returns (walk end frame, last frame)."""
    exit_phase = pick_walk_exit(rig)
    walk_end = 1 + WALK_CYCLES * CYCLE - CYCLE // 2
    walk_end += (exit_phase - (walk_end - 1)) % CYCLE  # end the strip on the chosen phase
    wave_start = walk_end + 2  # the wave starts once the walk has fully faded
    head_start = wave_start + WAVE_LEN - 1
    end = head_start + HEAD_KEYS[-1][0] + 2
    print(f"CHECK walk exit phase {exit_phase}, walk strip 1-{walk_end}, wave {wave_start}, ")
    print(f"CHECK head {head_start}, end {end}")

    acts = bpy.data.actions
    idle = strip(rig, "Idle", acts["Idle_A"], 1, repeat=end / 25 + 1)
    idle.extrapolation = "HOLD"
    walk_act = acts["Walking_A"]
    walk = strip(rig, "Walk", walk_act, 1)
    walk.scale = CYCLE / (walk_act.frame_range[1] - walk_act.frame_range[0])  # CYCLE frames each
    walk.repeat = (walk_end - 1) / CYCLE
    strip(
        rig,
        "Wave",
        upper_body_copy(acts["Waving"]),
        wave_start,
        blend_in=WAVE_BLEND,
        blend_out=WAVE_BLEND,
    )

    head = bpy.data.actions.new("HeadTurn")
    rig.animation_data.action = head
    pb = rig.pose.bones["head"]
    pb.rotation_mode = "QUATERNION"
    for offset, deg in HEAD_KEYS:
        pb.rotation_quaternion = Quaternion((0, 1, 0), math.radians(deg))
        pb.keyframe_insert("rotation_quaternion", frame=head_start + offset)
    pb.rotation_quaternion = Quaternion()
    rig.animation_data.action = None
    strip(rig, "HeadTurn", head, head_start, mode="COMBINE")
    walk.use_animated_influence = True  # eased fade (zero speed at both ends), not a linear one
    walk.keyframe_insert("influence", frame=1)
    curve = walk.fcurves.find("influence")  # strip-property curves live on the strip itself
    curve.keyframe_points.clear()  # enabling animated influence auto-keys a value; keep only ours
    for fr, value in ((1, 1.0), (walk_end - STOP_BLEND, 1.0), (walk_end, 0.0)):
        curve.keyframe_points.insert(fr, value)
    curve.update()
    return walk_end, end


def root_motion(rig: bpy.types.Object, stop_from: int, until: int) -> None:
    """Move the object so the planted foot keeps its world XY (root motion from the action)."""
    sc = bpy.context.scene

    def feet():
        m = rig.matrix_world
        return {n: m @ rig.pose.bones[n].head for n in ("foot.l", "foot.r")}

    sc.frame_set(1)
    prev = feet()
    rig.keyframe_insert("location", frame=1)
    for fr in range(2, until + 1):
        sc.frame_set(fr)
        cur = feet()
        down = [n for n in cur if cur[n].z < PLANT_Z and prev[n].z < PLANT_Z]
        if len(down) == 2 and fr >= stop_from:  # both down in the stop blend: split the difference
            d = sum((cur[n] - prev[n] for n in down), Vector()) / 2
        else:
            planted = min(cur, key=lambda n: max(cur[n].z, prev[n].z))
            d = cur[planted] - prev[planted]
        rig.location.x -= d.x
        rig.location.y -= d.y
        rig.keyframe_insert("location", frame=fr)
        sc.frame_set(fr)
        prev = feet()


def walk_stop_checks(rig: bpy.types.Object, walk_end: int, end: int) -> None:
    """Planted-foot drift over the clip; foot/toe lateral separation, walk vs stop window."""
    sc = bpy.context.scene
    sc.frame_set(1)
    prev = {n: rig.matrix_world @ rig.pose.bones[n].head for n in ("foot.l", "foot.r")}
    drift = 0.0
    sep: dict[int, float] = {}
    for fr in range(2, end + 1):
        sc.frame_set(fr)
        cur = {n: rig.matrix_world @ rig.pose.bones[n].head for n in ("foot.l", "foot.r")}
        for n in cur:
            if cur[n].z < PLANT_Z and prev[n].z < PLANT_Z:
                step = (cur[n].xy - prev[n].xy).length
                if step > 0.007:
                    print(f"DRIFT f{fr} {n} {step:.4f} z={cur[n].z:.3f}")
                drift = max(drift, step)
        prev = cur
        pb = rig.pose.bones
        sep[fr] = min(
            pb["foot.l"].head.x - pb["foot.r"].head.x, pb["toes.l"].head.x - pb["toes.r"].head.x
        )
    walk_min = min(sep[f] for f in range(2, walk_end - STOP_BLEND))
    stop_min = min(sep[f] for f in range(walk_end - STOP_BLEND, walk_end + 6))
    idle_sep = sep[end]
    print(f"CHECK planted-foot max drift {drift:.4f} u/frame (limit 0.007)")
    print(f"CHECK lateral separation: walk min {walk_min:.3f}, stop-window min {stop_min:.3f}, ")
    print(f"CHECK idle separation {idle_sep:.3f}")


def open_hand(rig: bpy.types.Object) -> None:
    """Hand route A: hide the right fist, add a rigid open-mitten hand on hand.r (palm forward)."""
    arm = bpy.data.objects["Rogue_ArmRight"]
    names = {g.index: g.name for g in arm.vertex_groups}
    fist = arm.vertex_groups.new(name="fist_r")
    idx = []
    for v in arm.data.vertices:
        if v.groups and names[max(v.groups, key=lambda g: g.weight).group] == "hand.r":
            idx.append(v.index)
    fist.add(idx, 1.0, "REPLACE")
    # skin colour: the most common UV among the fist's loops
    uvl = arm.data.uv_layers.active.data
    counts: dict[tuple[float, float], int] = {}
    idx_set = set(idx)
    for loop in arm.data.loops:
        if loop.vertex_index in idx_set:
            key = (round(uvl[loop.index].uv.x, 3), round(uvl[loop.index].uv.y, 3))
            counts[key] = counts.get(key, 0) + 1
    skin_uv = max(counts, key=counts.get)
    mask = arm.modifiers.new("HideFist", "MASK")
    mask.vertex_group, mask.invert_vertex_group = "fist_r", True
    bpy.ops.object.select_all(action="DESELECT")
    with bpy.context.temp_override(object=arm, active_object=arm):
        bpy.ops.object.modifier_move_to_index(modifier="HideFist", index=0)

    # Rest is a T-pose: hand.r runs x=-0.787 to -0.899 along -X at z=1.107; forward is -Y.
    bm = bmesh.new()

    def block(cx, cy, cz, sx, sy, sz, rot=None):
        geom = bmesh.ops.create_cube(bm, size=1.0)["verts"]
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=geom)
        if rot is not None:
            bmesh.ops.rotate(bm, matrix=rot, verts=geom)
        bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=geom)

    block(-0.83, -0.005, 1.10, 0.15, 0.075, 0.19)  # palm, overlapping the wrist cuff
    block(-0.95, -0.005, 1.095, 0.13, 0.06, 0.17)  # fingers as one mitten
    thumb_rot = Matrix.Rotation(math.radians(-35), 3, "Y")
    block(-0.80, -0.02, 1.215, 0.06, 0.06, 0.12, thumb_rot)  # thumb, up and out
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=0.018, segments=2, affect="EDGES")
    me = bpy.data.meshes.new("Rogue_OpenHandR")
    bm.to_mesh(me)
    bm.free()
    uv = me.uv_layers.new(name="UVMap")
    for d in uv.data:
        d.uv = skin_uv
    me.materials.append(arm.material_slots[0].material)
    hand = bpy.data.objects.new("Rogue_OpenHandR", me)
    bpy.context.scene.collection.objects.link(hand)
    hand.parent = rig
    vg = hand.vertex_groups.new(name="hand.r")
    vg.add(list(range(len(me.vertices))), 1.0, "REPLACE")
    hand.modifiers.new("Armature", "ARMATURE").object = rig
    print(f"CHECK fist verts hidden {len(idx)}, open hand verts {len(me.vertices)}, uv {skin_uv}")


def smooth_normals(rig: bpy.types.Object) -> None:
    """Smooth shading everywhere; the head takes a sphere's normals (one clean face shadow)."""
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.parent == rig]
    for o in meshes:
        for p in o.data.polygons:
            p.use_smooth = True
    head = bpy.data.objects["Rogue_Head"]
    pts = [head.matrix_world @ Vector(c) for c in head.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=(lo + hi) / 2)
    sph = bpy.context.object
    sph.name = "HeadNormalSphere"
    sph.scale = (hi - lo) / 2
    for p in sph.data.polygons:
        p.use_smooth = True
    sph.hide_render = True
    world = sph.matrix_world.copy()
    sph.parent, sph.parent_type, sph.parent_bone = rig, "BONE", "head"
    sph.matrix_world = world
    dt = head.modifiers.new("SphereNormals", "DATA_TRANSFER")
    dt.object = sph
    dt.use_loop_data, dt.data_types_loops = True, {"CUSTOM_NORMAL"}
    dt.loop_mapping = "POLYINTERP_NEAREST"
    dt.mix_factor = 0.85


def toonify(mat: bpy.types.Material) -> None:
    nt = mat.node_tree
    img = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    s2r = nt.nodes.new("ShaderNodeShaderToRGB")
    scale = nt.nodes.new("ShaderNodeMath")
    scale.operation, scale.inputs[1].default_value = "MULTIPLY", 0.25
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].color = (0.62, 0.6, 0.72, 1)
    ramp.color_ramp.elements[1].position = 0.42
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(dif.outputs[0], s2r.inputs[0])
    nt.links.new(s2r.outputs[0], scale.inputs[0])
    nt.links.new(scale.outputs[0], ramp.inputs[0])
    if img:
        nt.links.new(img.outputs[0], mul.inputs[6])
    else:
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        mul.inputs[6].default_value = (
            bsdf.inputs["Base Color"].default_value if bsdf else (0.8, 0.8, 0.8, 1)
        )
    nt.links.new(ramp.outputs[0], mul.inputs[7])
    nt.links.new(mul.outputs[2], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs[0])


def stage(end: int) -> None:
    sc = bpy.context.scene
    for m in {
        s.material
        for o in bpy.data.objects
        if o.type == "MESH"
        for s in o.material_slots
        if s.material
    }:
        toonify(m)
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    ground = bpy.context.object
    gm = bpy.data.materials.new("Ground")
    gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.36, 0.62, 0.30, 1)
    toonify(gm)
    ground.data.materials.append(gm)
    ground.visible_shadow = False

    world = bpy.data.worlds.new("Sky")
    sc.world = world
    world.use_nodes = True
    wn, wl = world.node_tree.nodes, world.node_tree.links
    tc, sep = wn.new("ShaderNodeTexCoord"), wn.new("ShaderNodeSeparateXYZ")
    mr, wr = wn.new("ShaderNodeMapRange"), wn.new("ShaderNodeValToRGB")
    mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = -0.1, 0.6
    wr.color_ramp.elements[0].color = (0.98, 0.93, 0.80, 1)
    wr.color_ramp.elements[1].color = (0.55, 0.75, 0.95, 1)
    wl.new(tc.outputs["Window"], sep.inputs[0])
    wl.new(sep.outputs["Y"], mr.inputs["Value"])
    wl.new(mr.outputs[0], wr.inputs[0])
    wl.new(wr.outputs[0], wn["Background"].inputs[0])

    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(55), 0, math.radians(-60)))
    sun = bpy.context.object
    sun.data.energy, sun.data.angle = 10.0, math.radians(0.5)  # hard cast shadow

    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.lens = 50
    sc.collection.objects.link(cam)
    sc.camera = cam
    target = Vector((0.75, 0.9, 0.95))
    for dist, fr in ((8.0, 1), (7.7, end)):  # slow 4% push-in
        cam.location = target + Vector((0.0, -1.0, 0.14)).normalized() * dist
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert("location", frame=fr)
        cam.keyframe_insert("rotation_euler", frame=fr)

    r = sc.render
    r.engine = "BLENDER_EEVEE"
    r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1080, 100
    sc.view_settings.view_transform = "Standard"
    r.use_freestyle = True
    r.line_thickness_mode = "ABSOLUTE"
    r.line_thickness = 1.0
    fs = bpy.context.view_layer.freestyle_settings
    lset = fs.linesets[0] if len(fs.linesets) else fs.linesets.new("Ink")
    lset.select_by_visibility, lset.select_by_edge_types = True, True
    lset.select_silhouette, lset.select_contour, lset.select_external_contour = True, True, True
    lset.select_material_boundary = True
    lset.select_crease, lset.select_border = False, False
    ls = lset.linestyle or bpy.data.linestyles.new("Ink")
    lset.linestyle = ls
    ls.color, ls.thickness = (0.16, 0.11, 0.10), 1.6
    cal = ls.thickness_modifiers.new("Brush", "CALLIGRAPHY")  # pen-like width by direction
    cal.thickness_min, cal.thickness_max, cal.orientation = 0.0, 1.6, math.radians(60)
    cal.blend = "ADD"
    r.image_settings.file_format = "PNG"


def main() -> None:
    rig = load()
    sc = bpy.context.scene
    sc.render.fps = FPS
    rig.rotation_mode = "XYZ"
    rig.rotation_euler = (0, 0, math.radians(-20))  # 3/4 to camera, waving arm nearer
    rig.location = Vector((1.0, 1.6, 0))
    walk_end, end = build_motion(rig)
    sc.frame_start, sc.frame_end = 1, end
    root_motion(rig, walk_end - STOP_BLEND, walk_end + 6)
    walk_stop_checks(rig, walk_end, end)
    open_hand(rig)
    smooth_normals(rig)
    stage(end)
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "foundation_fix.blend"))
    for fr in STILLS:
        sc.frame_set(fr)
        sc.render.filepath = str(OUT / f"still_{fr:03d}.png")
        bpy.ops.render.render(write_still=True)
    if RENDER:
        sc.render.filepath = str(OUT / "frames" / "f_")
        bpy.ops.render.render(animation=True)
    os.sync()


main()
