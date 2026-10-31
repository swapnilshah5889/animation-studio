"""Bake-off candidate: a real 3D character (Mia) rendered with a flat cel/toon look in Blender.

COMPARISON ONLY. The project rule is strict 2D unless the owner approves 2.5D (AGENTS.md).

Run (idempotent, headless):
  /Applications/Blender.app/Contents/MacOS/Blender --background --python mia_toon3d.py -- \
      --out /Users/uchiha/ai-studio/scratch/blender-compare/toon-3d [--only 1,30,60] [--no-render] \
      [--params '{"hair_color":[0.1,0.1,0.1],"head_scale":1.2}']

Everything is procedural: meshes (bmesh), armature, materials, keyframes. No downloaded assets.
Look: Emission shader driven by Diffuse -> Shader-to-RGB -> constant ColorRamp (flat bands), plus
an inverted-hull outline (Solidify, flipped normals, black, backface culled). EEVEE has no Freestyle.

Rig machinery: bones are posed by *world-space orientations* (legs: analytic two-bone IK with a
knee pole; arms: upper-arm direction + elbow flex + bend direction), converted to local pose
rotations through the rest/parent matrices, so poses are written by intent, not by guessing Euler signs.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

# --------------------------------------------------------------------------------------
# parameters (a director can change the design by changing these)
# --------------------------------------------------------------------------------------
DEFAULT_PARAMS = dict(
    hair_color=(0.30, 0.16, 0.07),
    coat_color=(1.00, 0.78, 0.05),
    trousers_color=(0.12, 0.30, 0.82),
    boots_color=(0.85, 0.10, 0.08),
    skin_color=(1.00, 0.74, 0.58),
    eye_color=(0.20, 0.11, 0.05),
    head_scale=1.0,  # 1.0 = big round child head
    height=1.0,  # overall body scale (not the head)
    curl_count=64,  # chunky hair curls
    seed=3,
)
FPS = 24
NFRAMES = 72  # 3.0 s
RES = (1280, 720)

DEG = math.pi / 180.0


def lin(c):
    """sRGB 0..1 -> linear (we render with the Standard view transform so colours stay as drawn)."""
    return tuple(max(0.0, min(1.0, v)) ** 2.2 for v in c) + (1.0,)


def clamp01(x):
    return max(0.0, min(1.0, x))


def ease(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def sm(a, b, t):
    return ease((t - a) / (b - a))


def ease_back(u, c1=0.9):
    """ease-out with a small overshoot (settles)."""
    u = clamp01(u)
    c3 = c1 + 1
    return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2


def Rz(a):
    return Matrix.Rotation(a, 3, "Z")


def Ry(a):
    return Matrix.Rotation(a, 3, "Y")


def rotate_about(v, axis, a):
    return Matrix.Rotation(a, 3, axis) @ v


def fwd(yaw):
    """world forward vector for a heading (0 = facing -Y toward the camera, 90deg = facing +X)."""
    return Vector((math.sin(yaw), -math.cos(yaw), 0.0))


def cols(x, y, z):
    return Matrix((x, y, z)).transposed()


# --------------------------------------------------------------------------------------
# dimensions
# --------------------------------------------------------------------------------------
def dims(P):
    k, hs = P["height"], P["head_scale"]
    D = dict(
        k=k,
        hs=hs,
        hip=0.555 * k,
        thigh=0.26 * k,
        shin=0.245 * k,
        ankle=0.05 * k,
        hipx=0.06 * k,
        heel=0.05 * k,
        ball=0.09 * k,
        shx=0.125 * k,
        shz=0.805 * k,
        up=0.17 * k,
        fo=0.15 * k,
        palm=0.07 * k,
        neck0=0.83 * k,
        neck1=0.875 * k,
    )
    D["R"] = Vector((0.165, 0.155, 0.17)) * hs
    D["hc"] = D["neck1"] + D["R"].z * 0.80
    D["top"] = D["hc"] + D["R"].z
    D["gap"] = D["hipx"]  # feet lateral == hip lateral so legs are vertical in the front view
    return D


# --------------------------------------------------------------------------------------
# mesh builder
# --------------------------------------------------------------------------------------
class MB:
    def __init__(self):
        self.bm = bmesh.new()

    def _mark(self, n0, mi):
        self.bm.faces.ensure_lookup_table()
        for f in list(self.bm.faces)[n0:]:
            f.material_index = mi

    def ell(self, c, r, mi=0, seg=18, ring=10):
        n0 = len(self.bm.faces)
        m = Matrix.Translation(Vector(c)) @ Matrix.Diagonal(Vector((r[0], r[1], r[2], 1.0)))
        bmesh.ops.create_uvsphere(self.bm, u_segments=seg, v_segments=ring, radius=1.0, matrix=m)
        self._mark(n0, mi)

    def cone(self, p0, p1, r0, r1, mi=0, seg=14):
        p0, p1 = Vector(p0), Vector(p1)
        d = p1 - p0
        if d.length < 1e-6:
            return
        n0 = len(self.bm.faces)
        rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
        m = Matrix.Translation((p0 + p1) / 2) @ rot
        bmesh.ops.create_cone(
            self.bm, cap_ends=False, cap_tris=False, segments=seg, radius1=r0, radius2=r1, depth=d.length, matrix=m
        )
        self._mark(n0, mi)

    def cap(self, p0, p1, r0, r1, mi=0, seg=14):
        """tapered capsule: cone with a sphere at each end."""
        self.cone(p0, p1, r0, r1, mi, seg)
        self.ell(p0, (r0, r0, r0), mi, seg, 8)
        self.ell(p1, (r1, r1, r1), mi, seg, 8)

    def loft(self, rings, mi=0, n=26):
        """rings: (z, rx, ry, cy) from bottom to top; closed with caps."""
        n0 = len(self.bm.faces)
        vs = []
        for z, rx, ry, cy in rings:
            vs.append(
                [
                    self.bm.verts.new((rx * math.cos(2 * math.pi * j / n), cy + ry * math.sin(2 * math.pi * j / n), z))
                    for j in range(n)
                ]
            )
        for i in range(len(vs) - 1):
            for j in range(n):
                self.bm.faces.new((vs[i][j], vs[i][(j + 1) % n], vs[i + 1][(j + 1) % n], vs[i + 1][j]))
        self.bm.faces.new(vs[0][::-1])
        self.bm.faces.new(vs[-1])
        self._mark(n0, mi)


# --------------------------------------------------------------------------------------
# materials
# --------------------------------------------------------------------------------------
_OUTLINE = None


def outline_mat():
    global _OUTLINE
    if _OUTLINE is None:
        m = bpy.data.materials.new("outline")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (0.04, 0.03, 0.05, 1)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs[0], out.inputs[0])
        m.use_backface_culling = True
        for attr in ("use_backface_culling_shadow",):
            try:
                setattr(m, attr, True)
            except Exception:
                pass
        _OUTLINE = m
    return _OUTLINE


def toon_mat(name, rgb, shade=0.60, bands=2):
    """Flat cel material: Diffuse -> ShaderToRGB -> constant ramp (shadow / lit / [highlight]) -> Emission."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    dif.inputs["Color"].default_value = (1, 1, 1, 1)
    s2r = nt.nodes.new("ShaderNodeShaderToRGB")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    base = Vector(lin(rgb)[:3])
    shadow = Vector((base.x * shade * 0.92, base.y * shade * 0.95, min(1.0, base.z * shade * 1.12 + 0.01)))
    el = ramp.color_ramp.elements
    el[0].position = 0.0
    el[0].color = (*shadow, 1)
    el[1].position = 0.30
    el[1].color = (*base, 1)
    if bands == 3:
        e = el.new(0.93)
        e.color = (*(Vector((min(1, base.x * 1.10 + 0.02), min(1, base.y * 1.10 + 0.02), min(1, base.z * 1.10 + 0.02)))), 1)
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(dif.outputs[0], s2r.inputs[0])
    nt.links.new(s2r.outputs[0], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs[0])
    return m


# --------------------------------------------------------------------------------------
# armature
# --------------------------------------------------------------------------------------
def build_bone_table(D):
    B = {}

    def add(n, h, t, p=None):
        B[n] = dict(head=Vector(h), tail=Vector(t), parent=p)

    k = D["k"]
    add("root", (0, 0, 0), (0, 0, 0.08 * k))
    add("pelvis", (0, 0, D["hip"]), (0, 0, D["hip"] + 0.05 * k), "root")
    add("spine", (0, 0, 0.605 * k), (0, 0, 0.70 * k), "pelvis")
    add("chest", (0, 0, 0.70 * k), (0, 0, D["neck0"]), "spine")
    add("neck", (0, 0, D["neck0"]), (0, 0, D["neck1"]), "chest")
    add("head", (0, 0, D["neck1"]), (0, 0, D["top"]), "neck")
    add("hair_back", (0, 0.04 * D["hs"], D["hc"]), (0, 0.04 * D["hs"], D["top"]), "head")
    R, hc, hs = D["R"], D["hc"], D["hs"]

    def surf(x, zr, off=0.0):
        t = 1 - (x / R.x) ** 2 - (zr / R.z) ** 2
        return Vector((x, -R.y * math.sqrt(max(t, 0.0)) - off, hc + zr))

    D["surf"] = surf
    D["eye_x"], D["eye_z"] = 0.062 * hs, 0.015 * hs
    D["brow_z"], D["mouth_z"], D["nose_z"] = 0.078 * hs, -0.078 * hs, -0.032 * hs
    for s, sx in (("L", 1), ("R", -1)):
        p = surf(sx * D["eye_x"], D["eye_z"])
        add(f"eye.{s}", p, p + Vector((0, -0.02, 0)), "head")
        p = surf(sx * D["eye_x"], D["brow_z"])
        add(f"brow.{s}", p, p + Vector((0, -0.02, 0)), "head")
        hx = sx * D["hipx"]
        kz = D["hip"] - D["thigh"]
        add(f"thigh.{s}", (hx, 0, D["hip"]), (hx, 0, kz), "pelvis")
        add(f"shin.{s}", (hx, 0, kz), (hx, 0, D["ankle"]), f"thigh.{s}")
        add(f"foot.{s}", (hx, 0, D["ankle"]), (hx, -0.14 * k, D["ankle"]), f"shin.{s}")
        sh = Vector((sx * D["shx"], 0, D["shz"]))
        el = sh - Vector((0, 0, D["up"]))
        wr = el - Vector((0, 0, D["fo"]))
        add(f"upper_arm.{s}", sh, el, "chest")
        add(f"forearm.{s}", el, wr, f"upper_arm.{s}")
        add(f"hand.{s}", wr, wr - Vector((0, 0, D["palm"])), f"forearm.{s}")
        base = wr - Vector((0, 0, D["palm"]))
        for i, (fy, fl) in enumerate(zip((-0.026, -0.009, 0.009, 0.026), (0.92, 1.0, 0.95, 0.75))):
            a, b = 0.034 * k * fl, 0.028 * k * fl
            h1 = base + Vector((0, fy * k, 0))
            add(f"f{i}a.{s}", h1, h1 - Vector((0, 0, a)), f"hand.{s}")
            add(f"f{i}b.{s}", h1 - Vector((0, 0, a)), h1 - Vector((0, 0, a + b)), f"f{i}a.{s}")
        t0 = wr - Vector((0, 0.03 * k, 0.025 * k))
        td = Vector((0, -0.40, -0.92)).normalized()
        add(f"th_a.{s}", t0, t0 + td * 0.03 * k, f"hand.{s}")
        add(f"th_b.{s}", t0 + td * 0.03 * k, t0 + td * 0.055 * k, f"th_a.{s}")
    p = surf(0, D["mouth_z"])
    add("mouth", p, p + Vector((0, -0.02, 0)), "head")
    return B


def make_armature(B):
    ad = bpy.data.armatures.new("MiaRig")
    ob = bpy.data.objects.new("MiaRig", ad)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for n, b in B.items():
        eb = ad.edit_bones.new(n)
        eb.head, eb.tail = b["head"], b["tail"]
    for n, b in B.items():
        eb = ad.edit_bones[n]
        if b["parent"]:
            eb.parent = ad.edit_bones[b["parent"]]
        eb.use_connect = False
        y = (b["tail"] - b["head"]).normalized()
        z = Vector((1, 0, 0)).cross(y)
        eb.align_roll(z)
    bpy.ops.object.mode_set(mode="OBJECT")
    ob.show_in_front = True
    return ob


class Rig:
    """Pose bones by world-space intent. Keeps its own copy of the pose maths (verified against Blender)."""

    def __init__(self, obj, B):
        self.obj = obj
        self.par = {n: b["parent"] for n, b in B.items()}
        self.rest = {n: obj.data.bones[n].matrix_local.to_3x3() for n in B}
        self.reset()
        self.prev_e = {}

    def reset(self):
        self.basis = {n: Matrix.Identity(3) for n in self.par}
        self.loc = {}
        self.scl = {}

    def frame_m(self, n):
        p = self.par[n]
        if p is None:
            return self.rest[n]
        return self.prot(p) @ self.rest[p].inverted() @ self.rest[n]

    def prot(self, n):
        return self.frame_m(n) @ self.basis[n]

    def set_world(self, n, Rd):
        self.basis[n] = self.frame_m(n).inverted() @ Rd

    def set_euler(self, n, x=0.0, y=0.0, z=0.0):
        self.basis[n] = Euler((x, y, z), "XYZ").to_matrix()

    def set_offset(self, n, v):
        self.loc[n] = self.frame_m(n).inverted() @ Vector(v)

    def apply(self, f):
        for n, pb in self.obj.pose.bones.items():
            e = self.basis[n].to_euler("XYZ", self.prev_e.get(n, Euler((0, 0, 0), "XYZ")))
            self.prev_e[n] = e
            pb.rotation_euler = e
            pb.location = self.loc.get(n, Vector((0, 0, 0)))
            pb.scale = self.scl.get(n, Vector((1, 1, 1)))
            pb.keyframe_insert("rotation_euler", frame=f)
            if n in self.loc or n in ("root", "pelvis"):
                pb.keyframe_insert("location", frame=f)
            if n in self.scl or n.startswith("eye") or n == "mouth":
                pb.keyframe_insert("scale", frame=f)


def orient(Nref, Y):
    Y = Y.normalized()
    X = (Nref - Y * Nref.dot(Y))
    if X.length < 1e-6:
        X = Vector((1, 0, 0))
    X.normalize()
    return cols(X, Y, X.cross(Y))


# --------------------------------------------------------------------------------------
# character meshes
# --------------------------------------------------------------------------------------
def build_character(P, D, arm):
    rnd = __import__("random").Random(P["seed"])
    M = {
        "skin": toon_mat("skin", P["skin_color"], 0.80),
        "skin_d": toon_mat("skin_d", [c * 0.86 for c in P["skin_color"]], 0.80),
        "cheek": toon_mat("cheek", (1.0, 0.55, 0.52), 0.85),
        "coat": toon_mat("coat", P["coat_color"], 0.62, bands=3),
        "coat_d": toon_mat("coat_d", [c * 0.80 for c in P["coat_color"]], 0.62),
        "trou": toon_mat("trousers", P["trousers_color"], 0.58, bands=3),
        "boot": toon_mat("boots", P["boots_color"], 0.58, bands=3),
        "sole": toon_mat("sole", (0.97, 0.95, 0.88), 0.7),
        "hair": toon_mat("hair", P["hair_color"], 0.55, bands=3),
        "white": toon_mat("white", (1, 1, 1), 0.85),
        "pupil": toon_mat("pupil", P["eye_color"], 0.9),
        "dark": toon_mat("dark", (0.16, 0.08, 0.07), 0.9),
        "mouth": toon_mat("mouth", (0.62, 0.13, 0.15), 0.9),
        "button": toon_mat("button", (0.30, 0.18, 0.05), 0.8),
    }
    ol = outline_mat()
    coll = bpy.context.scene.collection

    def add_part(name, mb, mats, bones, outline=0.0065):
        """bones: str (rigid) or list[(bone, z)] for height-blended weights."""
        me = bpy.data.meshes.new(name)
        bmesh.ops.recalc_face_normals(mb.bm, faces=mb.bm.faces)
        mb.bm.to_mesh(me)
        mb.bm.free()
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        ob = bpy.data.objects.new(name, me)
        coll.objects.link(ob)
        for m in mats:
            me.materials.append(M[m])
        for _ in mats:
            me.materials.append(ol)
        if isinstance(bones, str):
            vg = ob.vertex_groups.new(name=bones)
            vg.add(list(range(len(me.vertices))), 1.0, "REPLACE")
        else:
            groups = {b: ob.vertex_groups.new(name=b) for b, _ in bones}
            for v in me.vertices:
                z = v.co.z
                if z <= bones[0][1]:
                    groups[bones[0][0]].add([v.index], 1.0, "REPLACE")
                elif z >= bones[-1][1]:
                    groups[bones[-1][0]].add([v.index], 1.0, "REPLACE")
                else:
                    for (b0, z0), (b1, z1) in zip(bones, bones[1:]):
                        if z0 <= z <= z1:
                            t = (z - z0) / (z1 - z0)
                            groups[b0].add([v.index], 1 - t, "REPLACE")
                            groups[b1].add([v.index], t, "REPLACE")
                            break
        am = ob.modifiers.new("Armature", "ARMATURE")
        am.object = arm
        so = ob.modifiers.new("Outline", "SOLIDIFY")
        so.thickness = outline
        so.offset = 1.0
        so.use_flip_normals = True
        so.use_rim = False
        so.material_offset = len(mats)
        return ob

    k, hs, R, hc = D["k"], D["hs"], D["R"], D["hc"]
    sk = D["surf"]

    # ---- coat torso (blended weights pelvis/spine/chest) -------------------------------------
    mb = MB()
    mb.loft(
        [
            (0.40 * k, 0.175 * k, 0.135 * k, 0),
            (0.50 * k, 0.150 * k, 0.120 * k, 0),
            (0.60 * k, 0.130 * k, 0.108 * k, 0),
            (0.70 * k, 0.128 * k, 0.105 * k, 0),
            (0.79 * k, 0.125 * k, 0.100 * k, 0),
            (0.835 * k, 0.092 * k, 0.082 * k, 0),
            (0.865 * k, 0.062 * k, 0.060 * k, 0),
        ]
    )
    add_part("coat_torso", mb, ["coat"], [("pelvis", 0.52 * k), ("spine", 0.64 * k), ("chest", 0.78 * k)])
    mb = MB()
    mb.ell((0, 0.06 * k, D["neck0"] + 0.005), (0.105 * k, 0.05 * k, 0.065 * k), 0)
    mb.ell((0, 0.07 * k, 0.785 * k), (0.10 * k, 0.04 * k, 0.05 * k), 0)
    add_part("hood", mb, ["coat_d"], "chest", 0.005)
    mb = MB()
    for z in (0.77, 0.69, 0.61):
        mb.ell((0, -0.1085 * k, z * k), (0.014 * k, 0.008 * k, 0.014 * k), 0)
    add_part("buttons", mb, ["button"], "chest", 0.0025)
    mb = MB()
    mb.ell((0, 0, D["hip"] - 0.02 * k), (0.115 * k, 0.095 * k, 0.085 * k), 0)
    add_part("pelvis_trousers", mb, ["trou"], "pelvis", 0.006)

    # ---- neck + head ------------------------------------------------------------------------
    mb = MB()
    mb.cap((0, 0, D["neck0"] - 0.02 * k), (0, 0, D["neck1"] + 0.02 * hs), 0.034 * k, 0.034 * k, 0)
    add_part("neck", mb, ["skin"], "neck", 0.005)

    mb = MB()
    mb.ell((0, 0, hc), tuple(R), 0, 28, 18)  # skull
    mb.ell((0, -0.012 * hs, hc - 0.46 * R.z), (0.80 * R.x, 0.82 * R.y, 0.58 * R.z), 0, 24, 14)  # jaw/cheeks
    for sx in (1, -1):
        mb.ell((sx * R.x * 0.97, 0.012 * hs, hc - 0.01 * hs), (0.014 * hs, 0.02 * hs, 0.03 * hs), 0)  # ears
    add_part("head", mb, ["skin"], "head", 0.007)

    mb = MB()
    mb.ell(sk(0, D["nose_z"], 0.002 * hs), (0.016 * hs, 0.016 * hs, 0.013 * hs), 0)
    add_part("nose", mb, ["skin_d"], "head", 0.0035)
    mb = MB()
    for sx in (1, -1):
        mb.ell(sk(sx * 0.098 * hs, -0.036 * hs, -0.004 * hs), (0.022 * hs, 0.01 * hs, 0.015 * hs), 0)
    add_part("cheeks", mb, ["cheek"], "head", 0.0)

    # eyes (own bones so they can blink), brows, mouth
    for s, sx in (("L", 1), ("R", -1)):
        c = sk(sx * D["eye_x"], D["eye_z"])
        mb = MB()
        mb.ell(c, (0.036 * hs, 0.014 * hs, 0.046 * hs), 0, 18, 12)
        mb.ell(c + Vector((sx * 0.0, -0.010 * hs, -0.002 * hs)), (0.023 * hs, 0.010 * hs, 0.031 * hs), 1, 16, 10)
        mb.ell(c + Vector((sx * -0.007 * hs, -0.0185 * hs, 0.012 * hs)), (0.0075 * hs,) * 3, 0, 10, 6)
        add_part(f"eye.{s}", mb, ["white", "pupil"], f"eye.{s}", 0.0035)
        b = sk(sx * D["eye_x"], D["brow_z"])
        mb = MB()
        tilt = 0.006 * hs
        mb.cap(
            b + Vector((-0.028 * hs, 0, -tilt * sx * 0)),
            b + Vector((0.028 * hs, 0, 0.004 * hs)),
            0.0065 * hs,
            0.0065 * hs,
            0,
            10,
        )
        add_part(f"brow.{s}", mb, ["hair"], f"brow.{s}", 0.003)
    mb = MB()
    pts = []
    for i in range(9):
        x = (-0.042 + 0.084 * i / 8) * hs
        z = D["mouth_z"] + hs * (0.014 * ((x / hs) / 0.042) ** 2 - 0.013)
        pts.append(sk(x, z, 0.0))
    for a, b2 in zip(pts, pts[1:]):
        mb.cap(a, b2, 0.0062 * hs, 0.0062 * hs, 0, 10)
    add_part("mouth", mb, ["mouth"], "mouth", 0.0025)

    # ---- hair: scalp cap + chunky curls ------------------------------------------------------
    mb = MB()
    mb.ell((0, 0.004 * hs, hc + 0.004 * hs), tuple(R * 1.045), 0, 28, 16)
    bm = mb.bm
    kill = []
    for v in bm.verts:
        d = Vector(((v.co.x) / (R.x * 1.045), (v.co.y - 0.004 * hs) / (R.y * 1.045), (v.co.z - hc) / (R.z * 1.045)))
        if (d.y < -0.25 and d.z < 0.58) or d.z < -0.55:
            kill.append(v)
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    add_part("hair_cap", mb, ["hair"], "head", 0.006)

    front, back = MB(), MB()
    n = int(P["curl_count"])
    ga = math.pi * (3 - math.sqrt(5))
    for i in range(n * 2):
        zc = 1 - 2 * (i + 0.5) / (n * 2)
        r = math.sqrt(max(0, 1 - zc * zc))
        th = ga * i
        d = Vector((r * math.cos(th), r * math.sin(th), zc))
        if d.z < -0.15:
            continue
        if d.y < -0.35 and d.z < 0.52:
            continue  # face window
        rad = hs * rnd.uniform(0.040, 0.056)
        isf = d.y < -0.1
        if isf and d.z > 0.45:
            rad *= 0.85
        pos = Vector((d.x * R.x, d.y * R.y, hc + d.z * R.z)) * 1.0
        pos = Vector((pos.x * 1.03, pos.y * 1.03, hc + (pos.z - hc) * 1.03))
        tgt = back if d.y > 0.15 else front
        tgt.ell(pos, (rad * 1.05, rad, rad * 0.95), 0, 12, 8)
    # curly lock bangs over the forehead
    for i, x in enumerate((-0.10, -0.05, 0.0, 0.05, 0.10)):
        zr = 0.62 + 0.03 * ((i % 2) - 0.5)
        p = sk(x * hs * 1.1, zr * R.z, -0.012 * hs)
        front.ell(p, (0.034 * hs, 0.03 * hs, 0.036 * hs), 0, 12, 8)
    add_part("hair_front", front, ["hair"], "head", 0.005)
    add_part("hair_back", back, ["hair"], "hair_back", 0.005)

    # ---- legs, boots -------------------------------------------------------------------------
    for s, sx in (("L", 1), ("R", -1)):
        hx = sx * D["hipx"]
        kz = D["hip"] - D["thigh"]
        mb = MB()
        mb.cap((hx, 0, D["hip"] - 0.01 * k), (hx, 0, kz), 0.057 * k, 0.046 * k, 0, 14)
        add_part(f"thigh.{s}", mb, ["trou"], f"thigh.{s}", 0.006)
        mb = MB()
        mb.cap((hx, 0, kz), (hx, 0, D["ankle"] + 0.07 * k), 0.046 * k, 0.043 * k, 0, 14)
        mb.cone((hx, 0, D["ankle"] + 0.04 * k), (hx, 0, D["ankle"] + 0.15 * k), 0.052 * k, 0.050 * k, 2, 14)
        add_part(f"shin.{s}", mb, ["trou", "boot", "boot"], f"shin.{s}", 0.006)
        mb = MB()
        mb.ell((hx, -0.032 * k, D["ankle"] - 0.004 * k), (0.038 * k, 0.092 * k, 0.047 * k), 0, 18, 12)
        mb.ell((hx, 0.0, D["ankle"] + 0.03 * k), (0.045 * k, 0.05 * k, 0.05 * k), 0, 14, 8)
        mb.ell((hx, -0.035 * k, D["ankle"] - 0.044 * k), (0.037 * k, 0.092 * k, 0.012 * k), 1, 16, 6)
        add_part(f"boot.{s}", mb, ["boot", "sole"], f"foot.{s}", 0.006)

        # ---- arms ----
        sh = Vector((sx * D["shx"], 0, D["shz"]))
        el = sh - Vector((0, 0, D["up"]))
        wr = el - Vector((0, 0, D["fo"]))
        mb = MB()
        mb.ell(sh, (0.052 * k,) * 3, 0)
        mb.cap(sh, el, 0.046 * k, 0.040 * k, 0, 14)
        add_part(f"sleeve_up.{s}", mb, ["coat"], f"upper_arm.{s}", 0.006)
        mb = MB()
        mb.cap(el, wr + Vector((0, 0, 0.02 * k)), 0.040 * k, 0.034 * k, 0, 14)
        mb.cone(wr + Vector((0, 0, 0.035 * k)), wr + Vector((0, 0, -0.005 * k)), 0.036 * k, 0.040 * k, 1, 14)
        add_part(f"sleeve_lo.{s}", mb, ["coat", "coat_d"], f"forearm.{s}", 0.006)
        # hand: palm + fingers + thumb, each on its bone
        base = wr - Vector((0, 0, D["palm"]))
        mb = MB()
        mb.ell(wr - Vector((0, 0, 0.035 * k)), (0.016 * k, 0.034 * k, 0.040 * k), 0, 14, 10)
        add_part(f"palm.{s}", mb, ["skin"], f"hand.{s}", 0.0035)
        for i, (fy, fl) in enumerate(zip((-0.026, -0.009, 0.009, 0.026), (0.92, 1.0, 0.95, 0.75))):
            a, b = 0.034 * k * fl, 0.028 * k * fl
            h1 = base + Vector((0, fy * k, 0))
            h2 = h1 - Vector((0, 0, a))
            h3 = h2 - Vector((0, 0, b))
            for nm, p0, p1, r0, r1 in ((f"f{i}a.{s}", h1, h2, 0.0105 * k, 0.0095 * k), (f"f{i}b.{s}", h2, h3, 0.0095 * k, 0.0082 * k)):
                mb = MB()
                mb.cap(p0, p1, r0, r1, 0, 8)
                add_part(nm.replace(".", "_mesh."), mb, ["skin"], nm, 0.003)
        t0 = wr - Vector((0, 0.03 * k, 0.025 * k))
        td = Vector((0, -0.40, -0.92)).normalized()
        for nm, p0, p1, r0, r1 in (
            (f"th_a.{s}", t0, t0 + td * 0.03 * k, 0.0125 * k, 0.0108 * k),
            (f"th_b.{s}", t0 + td * 0.03 * k, t0 + td * 0.055 * k, 0.0108 * k, 0.0092 * k),
        ):
            mb = MB()
            mb.cap(p0, p1, r0, r1, 0, 8)
            add_part(nm.replace(".", "_mesh."), mb, ["skin"], nm, 0.003)
    return M


# --------------------------------------------------------------------------------------
# scene: world, light, camera, shadow blob
# --------------------------------------------------------------------------------------
def build_scene(D):
    sc = bpy.context.scene
    r = sc.render
    r.resolution_x, r.resolution_y = RES
    r.resolution_percentage = 100
    r.fps = FPS
    sc.frame_start, sc.frame_end = 1, NFRAMES
    for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            r.engine = eng
            break
        except Exception:
            continue
    try:
        sc.eevee.taa_render_samples = 32
    except Exception:
        pass
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.display_settings.display_device = "sRGB"
    r.image_settings.file_format = "PNG"
    r.film_transparent = False

    # world: pale background for camera rays, black for lighting (so only the sun lights the bands)
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    lp = nt.nodes.new("ShaderNodeLightPath")
    bgc = nt.nodes.new("ShaderNodeBackground")
    bgc.inputs["Color"].default_value = lin((0.93, 0.93, 0.89))
    bgl = nt.nodes.new("ShaderNodeBackground")
    bgl.inputs["Color"].default_value = (0, 0, 0, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bgl.outputs[0], mix.inputs[1])
    nt.links.new(bgc.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])

    ld = bpy.data.lights.new("sun", "SUN")
    ld.energy = math.pi
    ld.angle = 0.03
    try:
        ld.use_shadow = True
    except Exception:
        pass
    lo = bpy.data.objects.new("sun", ld)
    sc.collection.objects.link(lo)
    lo.rotation_euler = (55 * DEG, 0, -35 * DEG)

    cam = bpy.data.cameras.new("cam")
    cam.type = "ORTHO"
    height = D["top"] + 0.04  # hair top
    frame_h = height / 0.70
    cam.ortho_scale = frame_h * 16 / 9 / math.cos(10 * DEG)
    cam.clip_start, cam.clip_end = 0.1, 40
    co = bpy.data.objects.new("cam", cam)
    sc.collection.objects.link(co)
    elev = 10 * DEG
    target = Vector((-0.12, 0.0, frame_h * 0.5 - 0.5 * (frame_h - height) + 0.0))
    target.z = height * 0.5 + 0.01
    d = Vector((0, math.cos(elev), -math.sin(elev)))
    co.location = target - d * 12
    co.rotation_euler = (math.radians(90) - elev, 0, 0)
    sc.camera = co

    # soft ground shadow blob
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 0, 0.002))
    blob = bpy.context.active_object
    blob.name = "shadow_blob"
    m = bpy.data.materials.new("shadow")
    m.use_nodes = True
    m.surface_render_method = "BLENDED"
    nt = m.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    vm = nt.nodes.new("ShaderNodeVectorMath")
    vm.operation = "SUBTRACT"
    vm.inputs[1].default_value = (0.5, 0.5, 0)
    gr = nt.nodes.new("ShaderNodeTexGradient")
    gr.gradient_type = "SPHERICAL"
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.46
    ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    ramp.color_ramp.elements[1].position = 0.92
    ramp.color_ramp.elements[1].color = (0.5, 0.5, 0.5, 1)
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = lin((0.30, 0.30, 0.40))
    mx = nt.nodes.new("ShaderNodeMixShader")
    outm = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tc.outputs["UV"], vm.inputs[0])
    nt.links.new(vm.outputs[0], gr.inputs[0])
    nt.links.new(gr.outputs["Fac"], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], mx.inputs[0])
    nt.links.new(tr.outputs[0], mx.inputs[1])
    nt.links.new(em.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], outm.inputs[0])
    blob.data.materials.append(m)
    blob.scale = (0.46 * D["k"], 0.32 * D["k"], 1)
    try:
        blob.visible_shadow = False
    except Exception:
        pass
    return blob


# --------------------------------------------------------------------------------------
# animation: foot plan (gait), body, arms, face
# --------------------------------------------------------------------------------------
X0, LS, TST = -0.43, 0.26, 0.40
XL3 = X0 + 3 * LS
V = LS / TST
THETA_HS, THETA_TO = 12 * DEG, -35 * DEG


def foot_offset(th, D):
    """ankle offset (along forward, up) from the flat-foot ankle when the foot pitched by th about its pivot."""
    az, hd, bd = D["ankle"], D["heel"], D["ball"]
    c, s = math.cos(th), math.sin(th)
    if th >= 0:  # heel pivot
        return (-hd + hd * c - az * s, -az + hd * s + az * c)
    return (bd - bd * c - az * s, -bd * s + az * c - az)  # ball pivot


def build_plan(D):
    g = D["gap"]
    R = [
        dict(k="st", t0=-1.0, t1=0.48, p=(X0, -g), yaw=lambda t: 90 * DEG),
        dict(k="sw", t0=0.48, t1=0.80, a=(X0, -g), b=(X0 + 2 * LS, -g), c=0.065, ya=90 * DEG, yb=90 * DEG),
        dict(k="st", t0=0.80, t1=1.25, p=(X0 + 2 * LS, -g), yaw=lambda t: 90 * DEG),
        dict(k="sw", t0=1.25, t1=1.50, a=(X0 + 2 * LS, -g), b=(XL3, -g), c=0.045, ya=90 * DEG, yb=90 * DEG),
        dict(k="st", t0=1.50, t1=1.70, p=(XL3, -g), yaw=lambda t: 90 * DEG),
        dict(k="arc", t0=1.70, t1=2.00, ctr=(XL3, g), r=2 * g, a0=-90 * DEG, a1=-180 * DEG, c=0.05, ya=90 * DEG, yb=0.0),
        dict(k="st", t0=2.00, t1=99, p=(XL3 - 2 * g, g), yaw=lambda t: 0.0),
    ]
    L = [
        dict(k="st", t0=-1.0, t1=0.08, p=(X0 - LS, g), yaw=lambda t: 90 * DEG),
        dict(k="sw", t0=0.08, t1=0.40, a=(X0 - LS, g), b=(X0 + LS, g), c=0.065, ya=90 * DEG, yb=90 * DEG),
        dict(k="st", t0=0.40, t1=0.88, p=(X0 + LS, g), yaw=lambda t: 90 * DEG),
        dict(k="sw", t0=0.88, t1=1.20, a=(X0 + LS, g), b=(XL3, g), c=0.065, ya=90 * DEG, yb=90 * DEG),
        dict(k="st", t0=1.20, t1=99, p=(XL3, g), yaw=lambda t: pivot_yaw(t)),
    ]
    return dict(L=L, R=R)


def pivot_yaw(t):
    """root / pelvis heading during the turn: 90deg (facing +X) -> 0 (facing the camera), with a little settle."""
    u = (t - 1.60) / 0.40
    if u <= 0:
        return 90 * DEG
    return 90 * DEG * (1 - min(ease_back(u, 0.55), 1.06))


def foot_yaw_pivot(t):
    return 90 * DEG * (1 - ease((t - 1.60) / 0.40))


def foot_state(plan, t, D):
    """-> (ankle world Vector, yaw, pitch, mode). Stance feet are fixed in world; swing feet follow a path."""
    az = D["ankle"]

    def ankle_from(flat, yaw, th, lift=0.0):
        so, zo = foot_offset(th, D)
        f = fwd(yaw)
        return Vector((flat[0], flat[1], 0)) + f * so + Vector((0, 0, az + zo + lift))

    for i, s in enumerate(plan):
        if s["t0"] <= t < s["t1"]:
            break
    else:
        s = plan[-1]
    if s["k"] == "st":
        has_prev = s["t0"] > -0.5
        has_next = s["t1"] < 50
        th = 0.0
        mode = "flat"
        if has_prev:
            tau = (t - s["t0"]) / 0.07
            if tau < 1:
                th += THETA_HS * (1 - ease(tau))
                mode = "heel"
        if has_next:
            tau = (t - (s["t1"] - 0.11)) / 0.11
            if tau > 0:
                th += THETA_TO * ease(tau)
                mode = "toe"
        yaw = s["yaw"](t)
        return ankle_from(s["p"], yaw, th), yaw, th, mode
    u = (t - s["t0"]) / (s["t1"] - s["t0"])
    sp = 0.5 - 0.5 * math.cos(math.pi * u)
    if s["k"] == "sw":
        flat = (s["a"][0] + (s["b"][0] - s["a"][0]) * sp, s["a"][1] + (s["b"][1] - s["a"][1]) * sp)
    else:
        a = s["a0"] + (s["a1"] - s["a0"]) * sp
        flat = (s["ctr"][0] + s["r"] * math.cos(a), s["ctr"][1] + s["r"] * math.sin(a))
    yaw = s["ya"] + (s["yb"] - s["ya"]) * sp
    th = THETA_TO + (THETA_HS - THETA_TO) * ease(u / 0.9)
    lift = s["c"] * (math.sin(math.pi * u) ** 0.85)
    return ankle_from(flat, yaw, th, lift), yaw, th, "swing"


def leg_ik(H, A, pole, L1, L2):
    d = A - H
    dist = d.length
    clamped = 0.0
    mx = (L1 + L2) * 0.9995
    if dist > mx:
        clamped = dist - mx
        A = H + d * (mx / dist)
        d = A - H
        dist = mx
    e = d / dist
    a = (L1 * L1 - L2 * L2 + dist * dist) / (2 * dist)
    h = math.sqrt(max(L1 * L1 - a * a, 0.0))
    pp = pole - e * pole.dot(e)
    pp.normalize()
    K = H + e * a + pp * h
    N = pp.cross(e).normalized()
    return K, A, N, clamped


def pelvis_state(t, D, plan):
    """pelvis ground xy, height, root yaw, pelvis twist."""
    k = D["k"]
    # heading
    yaw = pivot_yaw(t)
    anticip = 5 * DEG * math.sin(math.pi * clamp01((t - 1.40) / 0.20))
    walk_env = 1 - sm(1.2, 1.6, t)
    twist = 6 * DEG * math.cos(2 * math.pi * t / (2 * TST)) * walk_env
    # ground position
    if t <= 1.2:
        x = X0 - LS / 2 + V * t
        y = 0.0
    elif t < 1.6:
        tau = t - 1.2
        x = X0 - LS / 2 + V * 1.2 + V * tau * (1 - tau / 0.8)
        y = 0.0
    else:
        g = D["gap"]
        left = Vector((math.cos(yaw), math.sin(yaw)))  # character-left in the ground plane
        x = XL3 - g * left.x
        y = g - g * left.y
    # height with a walking bob (lowest at contact), then standing
    zmid = (0.5325 + (0.555 - 0.5325) * sm(1.2, 1.7, t)) * k
    amp = 0.0125 * k * (1 - sm(1.1, 1.5, t))
    z = zmid - amp * math.cos(2 * math.pi * t / TST)
    # wave bounce
    z += 0.005 * k * math.sin(2 * math.pi * 1.3 * (t - 2.2)) * sm(2.1, 2.3, t)
    return x, y, z, yaw + anticip, twist


def solve_frame(rig, t, D, plan, info):
    k, hs = D["k"], D["hs"]
    x, y, z, yaw, twist = pelvis_state(t, D, plan)
    walk_env = 1 - sm(1.2, 1.6, t)
    # root + pelvis
    rig.set_euler("root", 0, yaw, 0)
    rig.set_offset("root", (x, y, 0))
    rig.set_euler("pelvis", 0, twist, 0)
    rig.set_offset("pelvis", (0, 0, z - D["hip"]))
    pyaw = yaw + twist
    # legs
    feet = {}
    for s, sx, key in (("L", 1, "L"), ("R", -1, "R")):
        A, fyaw, th, mode = foot_state(plan[key], t, D)
        H = Vector((x, y, 0)) + Rz(pyaw) @ Vector((sx * D["hipx"], 0, 0)) + Vector((0, 0, z))
        kyaw = pyaw + 0.5 * (fyaw - pyaw)
        K, A2, N, cl = leg_ik(H, A, fwd(kyaw), D["thigh"], D["shin"])
        d1, d2 = (K - H).normalized(), (A2 - K).normalized()
        rig.set_world(f"thigh.{s}", orient(N, d1))
        rig.set_world(f"shin.{s}", orient(N, d2))
        fdir = fwd(fyaw) * math.cos(th) + Vector((0, 0, 1)) * math.sin(th)
        lat = Vector((0, 0, 1)).cross(fdir)
        rig.set_world(f"foot.{s}", orient(lat, fdir))
        feet[s] = dict(target=A, used=A2, clamp=cl, mode=mode, yaw=fyaw, th=th)
    info["feet"] = feet
    info["pelvis"] = (x, y, z)

    # spine / chest / head ------------------------------------------------------------------
    lean = (5 * DEG * walk_env) + 2 * DEG
    # absolute heading of head / chest during the turn (head leads, chest follows, pelvis last)
    def turn_abs(t0, dur, c1):
        u = (t - t0) / dur
        return 90 * DEG * (1 - (0 if u <= 0 else min(ease_back(u, c1), 1.08)))

    head_abs = turn_abs(1.34, 0.46, 0.7)
    chest_abs = turn_abs(1.50, 0.46, 0.6) - 0.8 * twist
    chest_rel = chest_abs - pyaw
    rig.set_euler("spine", lean * 0.5, 0.4 * chest_rel, 0)
    # wave-time body lean (weight over the left leg, shoulders tilt)
    wv = sm(2.0, 2.3, t)
    chest_roll = 3 * DEG * wv * math.sin(2 * math.pi * 0.9 * (t - 2.3) + 1.2)
    rig.set_euler("chest", lean * 0.5, 0.6 * chest_rel, -(-4 * DEG * wv + chest_roll))
    tilt = 11 * DEG * sm(2.15, 2.45, t) * (1 + 0.14 * math.sin(2 * math.pi * 1.1 * (t - 2.4)))
    nod = (3 * DEG * math.sin(2 * math.pi * t / TST) * walk_env) + 3 * DEG * wv * math.sin(2 * math.pi * 1.2 * (t - 2.3))
    head_total = head_abs - (pyaw + chest_rel)
    # extra look toward the waving hand
    head_total -= 5 * DEG * wv
    rig.set_euler("neck", 0.3 * nod, 0.35 * head_total, 0.3 * tilt)
    rig.set_euler("head", 0.7 * nod - 1.5 * DEG, 0.65 * head_total, 0.7 * tilt)
    info["head_e"] = (0.7 * nod - 1.5 * DEG, 0.65 * head_total + 0.35 * head_total, tilt)

    # arms -------------------------------------------------------------------------------------
    cyaw = chest_abs  # world yaw of the chest for arm directions
    Rc = Rz(cyaw - 0.0 * 0)
    # character-frame axes rotated by the chest's world yaw (forward = -Y at yaw 0)
    F = Rc @ Vector((0, -1, 0))
    LAT = Rc @ Vector((1, 0, 0))
    UP = Vector((0, 0, 1))
    ph = 2 * math.pi * t / (2 * TST)
    amp = 28 * DEG * walk_env
    for s, sx in (("L", 1), ("R", -1)):
        swing = amp * math.cos(ph) * (1 if s == "L" else -1)
        u0 = (-UP * math.cos(swing) + F * math.sin(swing) + LAT * sx * 0.10).normalized()
        flex0 = 16 * DEG + 24 * DEG * max(0.0, swing / (28 * DEG)) + 6 * DEG
        bend0 = F
        curl0 = 22 * DEG
        spread0 = 0.0
        th_open0 = 0.0
        if s == "L":
            # wave pose
            a = sm(1.95, 2.30, t)  # raise
            wave_env = sm(2.25, 2.4, t)
            wa = (12 * DEG + 18 * DEG * math.sin(2 * math.pi * 2.6 * (t - 2.3))) * wave_env
            u1 = (LAT * 0.95 + F * 0.22 + UP * 0.16).normalized()
            u = (u0 * (1 - a) + u1 * a).normalized()
            flex = flex0 * (1 - a) + 86 * DEG * a
            bend = (bend0 * (1 - a) + (UP + LAT * 0.45) * a).normalized()
            curl = curl0 * (1 - a) + (6 * DEG) * a
            spread0 = a
            th_open0 = a
        else:
            u, flex, bend, curl = u0, flex0, bend0, curl0
            # small settle swing once she has stopped
            settle = sm(1.6, 1.9, t) * math.sin(2 * math.pi * 1.4 * (t - 1.7)) * (1 - sm(1.9, 2.6, t)) * 4 * DEG
            if settle:
                u = (u + F * settle).normalized()
            wa = 0.0
        bend = (bend - u * bend.dot(u)).normalized()
        Nref = bend.cross(u).normalized()
        f = (u * math.cos(flex) + bend * math.sin(flex)).normalized()
        if s == "L" and wave_env > 0:
            f = rotate_about(f, "Y", wa)
        rig.set_world(f"upper_arm.{s}", orient(Nref, u))
        rig.set_world(f"forearm.{s}", orient(Nref, f))
        hd = f
        if s == "L" and wave_env > 0:
            hd = rotate_about(f, "Y", 0.9 * wa * 1.0 + 0.0)
            hd = rotate_about(hd, "Y", 12 * DEG * math.sin(2 * math.pi * 2.6 * (t - 2.3) - 0.9) * wave_env)
        else:
            hd = (f * math.cos(8 * DEG) + Nref.cross(f) * math.sin(8 * DEG))
        rig.set_world(f"hand.{s}", orient(Nref, hd))
        # fingers
        for i in range(4):
            sp = (-14, -5, 5, 14)[i] * DEG * spread0
            rip = 0.0
            if s == "L":
                rip = 10 * DEG * math.sin(2 * math.pi * 2.6 * (t - 2.3) - 0.7 * i) * wave_env
            c1 = curl * (1.0 + 0.15 * i) + rip
            rig.set_euler(f"f{i}a.{s}", sp, 0, sx * c1)
            rig.set_euler(f"f{i}b.{s}", 0, 0, sx * (c1 * 1.25 + 4 * DEG * (1 - spread0)))
        thumb_x = -28 * DEG * th_open0
        rig.set_euler(f"th_a.{s}", thumb_x, 0, sx * (10 * DEG - 6 * DEG * th_open0))
        rig.set_euler(f"th_b.{s}", 0, 0, sx * (14 * DEG * (1 - th_open0)))

    # face: blink, brows, mouth ----------------------------------------------------------------
    def blink(t0):
        u = (t - t0) / 0.14
        return math.sin(math.pi * u) if 0 <= u <= 1 else 0.0

    bl = max(blink(0.88), blink(1.86), blink(2.78))
    for s in ("L", "R"):
        rig.scl[f"eye.{s}"] = Vector((1, 1, max(0.08, 1 - 0.92 * bl)))
        rig.set_offset(f"brow.{s}", (0, 0, 0.012 * hs * (sm(1.7, 1.95, t) * 0.8 + wv)))
    rig.scl["mouth"] = Vector((1 + 0.22 * wv + 0.05 * math.sin(2 * math.pi * 1.2 * t), 1, 1 + 0.35 * wv))
    info["blink"] = bl
    # (hair secondary motion is added in a second pass)


# --------------------------------------------------------------------------------------
def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    out = "/Users/uchiha/ai-studio/scratch/blender-compare/toon-3d"
    only = None
    render = True
    P = dict(DEFAULT_PARAMS)
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--out":
            out = argv[i + 1]
            i += 1
        elif a == "--only":
            only = [int(v) for v in argv[i + 1].split(",")]
            i += 1
        elif a == "--no-render":
            render = False
        elif a == "--params":
            P.update(json.loads(argv[i + 1]))
            i += 1
        i += 1
    os.makedirs(out, exist_ok=True)
    frames_dir = os.path.join(out, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    t_build = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    D = dims(P)
    B = build_bone_table(D)
    arm = make_armature(B)
    build_character(P, D, arm)
    build_scene(D)
    blob = bpy.data.objects["shadow_blob"]
    rig = Rig(arm, B)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
    plan = build_plan(D)

    # pass 1: solve every frame, keyframe
    infos = []
    head_hist = []
    for f in range(1, NFRAMES + 1):
        t = (f - 1) / FPS
        rig.reset()
        info = {}
        solve_frame(rig, t, D, plan, info)
        head_hist.append(Vector(info["head_e"]))
        # hair secondary motion: lag of the head's rotation (drag + overshoot)
        lagf = max(0, len(head_hist) - 4)
        dv = head_hist[-1] - head_hist[lagf]
        rig.set_euler("hair_back", -0.9 * dv.x, -0.9 * dv.y, -0.9 * dv.z)
        rig.apply(f)
        # shadow blob follows the pelvis on the ground
        px, py, pz = info["pelvis"]
        blob.location = (px, py, 0.002)
        blob.scale = (0.46 * D["k"] * (1.0 - 0.1 * (pz / D["hip"] - 1)), 0.32 * D["k"], 1)
        blob.keyframe_insert("location", frame=f)
        blob.keyframe_insert("scale", frame=f)
        infos.append(info)
    bpy.ops.object.mode_set(mode="OBJECT")
    build_s = time.time() - t_build

    # verification: compare the intended ankle with Blender's evaluated bone, ground contact, planted slide
    sc = bpy.context.scene
    errs, pen, slide = [], 0.0, {"L": 0.0, "R": 0.0}
    clamp_max = 0.0
    last = {}
    flat_frames = {"L": [], "R": []}
    for f in range(1, NFRAMES + 1):
        sc.frame_set(f)
        for s in ("L", "R"):
            fi = infos[f - 1]["feet"][s]
            pb = arm.pose.bones[f"foot.{s}"]
            head = pb.head.copy()
            errs.append((head - fi["used"]).length)
            clamp_max = max(clamp_max, fi["clamp"])
            ball = pb.matrix @ Vector((0, D["ball"], D["ankle"]))
            heel = pb.matrix @ Vector((0, -D["heel"], D["ankle"]))
            if fi["mode"] in ("flat",):
                pen = max(pen, -min(ball.z, heel.z))
                flat_frames[s].append((f, head.copy()))
    # sliding: for runs of consecutive flat frames, max ankle xy movement while the yaw is constant (no pivot)
    for s in ("L", "R"):
        runs = []
        for (f, p) in flat_frames[s]:
            if runs and f == runs[-1][-1][0] + 1:
                runs[-1].append((f, p))
            else:
                runs.append([(f, p)])
        for r in runs:
            xy0 = Vector((r[0][1].x, r[0][1].y))
            slide[s] = max(slide[s], max((Vector((p.x, p.y)) - xy0).length for _, p in r))
    metrics = dict(
        build_seconds=round(build_s, 1),
        ik_target_vs_blender_bone_max_err_m=round(max(errs), 5),
        ik_unreachable_max_m=round(clamp_max, 5),
        flat_foot_ground_penetration_max_m=round(pen, 5),
        flat_stance_ankle_drift_max_m=slide,
        params={k: (list(v) if isinstance(v, tuple) else v) for k, v in P.items()},
    )
    sc.frame_set(62)
    hp = arm.pose.bones["hand.L"]
    metrics["wave_hand_f62_head_tail"] = [[round(v, 3) for v in hp.head], [round(v, 3) for v in hp.tail]]
    metrics["hair_half_width_m"] = round(D["R"].x + 0.06, 3)
    print("METRICS", json.dumps(metrics))
    with open(os.path.join(out, "metrics.json"), "w") as fh:
        json.dump(metrics, fh, indent=1)

    if not render:
        return
    todo = only or list(range(1, NFRAMES + 1))
    t0 = time.time()
    for f in todo:
        sc.frame_set(f)
        sc.render.filepath = os.path.join(frames_dir, f"{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    secs = (time.time() - t0) / len(todo)
    print(f"RENDER_SECONDS_PER_FRAME {secs:.2f}")
    with open(os.path.join(out, "render_time.txt"), "w") as fh:
        fh.write(f"{secs:.3f}\n")


if __name__ == "__main__":
    main()
