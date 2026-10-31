#!/usr/bin/env python3
"""Spike: "Mia" as Blender Grease Pencil (GPv3, Blender 5.x) strokes driven by an armature.

Bake-off candidate: strictly 2D look (flat fills + outlines, unlit), every body part is built by code
from a parametric DESIGN dict, deformed by Armature modifiers (weights painted by code).

Run (headless, idempotent; wipes and rebuilds the scene and the output frames):
    /Applications/Blender.app/Contents/MacOS/Blender --background --python blender_gp_mia.py -- \
        --out /Users/uchiha/ai-studio/scratch/blender-compare/grease-pencil [--frames 0,20,40] [--scale 1.0]

How it works (see notes.md for the honest write-up):
 * one rig per body yaw (90 side, 60, 30, 0 front): same code, projected from a 3D rest skeleton, so
   a turn is a swap between four per-view rigs (allowed by the brief), the head is redrawn every frame
   at its own yaw (hair, face, features rotate on a sphere = the head turns as a whole);
 * the walk is solved with 2-bone IK in code (feet planted, no sliding), then written to pose bones;
 * rules (timing, foot planting) live in code; the LLM would pick parameters / motions.
"""
import math
import os
import shutil
import subprocess
import sys
import time

import bpy

# --------------------------------------------------------------------------- args / design
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


OUT = arg("--out", "/Users/uchiha/ai-studio/scratch/blender-compare/grease-pencil")
ONLY = [int(x) for x in arg("--frames").split(",")] if arg("--frames") else None
SCALE = float(arg("--scale", "1.0"))
TMP = os.path.join(OUT, "_frames")

# A director could change these (and head_scale) to restyle Mia without touching any drawing code.
DESIGN = dict(
    hair="#6b3a1e", coat="#f5c518", trousers="#2f5fc4", boots="#d6312b", skin="#f4bf96",
    outline="#3a2418", eye="#3b2a1c", cheek="#f29a8c", bg="#f3eedf",
    head_scale=1.0,
)
FPS, NFRAMES, W, H = 24, 72, 1280, 720
R_LINE = 0.0062          # outline radius in scene units (~3 px)

# body proportions (scene units, ground z=0, character about 2.0 tall)
HIP_Z, ANK_Z0 = 0.775, 0.08
THIGH, SHIN = 0.36, 0.34
SH_Z, UARM, FARM = 1.04, 0.27, 0.24
NECK_Z = 1.12
HEAD_R = 0.38 * DESIGN["head_scale"]
HEAD_Z = NECK_Z + HEAD_R * 0.93     # head centre; chin overlaps the collar a little
HIP_X, SH_X = 0.095, 0.225
VIEWS = [90, 60, 30, 0]             # body yaw per rig, degrees (90 = side view facing right)
FING_L = 0.095
FAN = [-0.40, -0.14, 0.10, 0.32]    # finger fan angles at rest (rad), thumb handled separately


def lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgba(hexs, a=1.0):
    h = hexs.lstrip("#")
    return tuple(lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)) + (a,)


def sm(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return a + (b - a) * t


# --------------------------------------------------------------------------- stroke plumbing
_MATS = {}
_FILLED = set()   # materials that fill (GPv3 needs a non-zero per-stroke fill_id to draw the fill)


def get_mat(fill, line, filled=True):
    key = (fill, line, filled)
    if key not in _MATS:
        m = bpy.data.materials.new("m%d" % len(_MATS))
        bpy.data.materials.create_gpencil_data(m)
        g = m.grease_pencil
        g.color = line if line else (0, 0, 0, 1)
        g.fill_color = fill if fill else (0, 0, 0, 0)
        g.show_stroke = line is not None
        g.show_fill = bool(filled and fill)
        _MATS[key] = m
        if filled and fill:
            _FILLED.add(m)
    return _MATS[key]


class SB:
    """Collects strokes for one drawing, then writes them (points, material, cyclic, weights)."""

    def __init__(self, gp):
        self.gp, self.items = gp, []

    def slot(self, m):
        for i, x in enumerate(self.gp.materials):
            if x == m:
                return i
        self.gp.materials.append(m)
        return len(self.gp.materials) - 1

    def add(self, pts, m, cyclic=True, radius=R_LINE, w=None):
        self.items.append((pts, self.slot(m), cyclic, radius, w, m in _FILLED and cyclic))

    def flush(self, drawing):
        n = len(drawing.strokes)
        if n:
            drawing.remove_strokes(indices=list(range(n)))
        if not self.items:
            return
        drawing.add_strokes([len(it[0]) for it in self.items])
        wmap, gi = {}, 0
        for si, (pts, slot, cyc, rad, w, filled) in enumerate(self.items):
            s = drawing.strokes[si]
            s.material_index, s.cyclic = slot, cyc
            s.fill_opacity = 1.0
            s.fill_id = (si + 1) if filled else 0
            for i, p in enumerate(pts):
                pt = s.points[i]
                pt.position = (p[0], 0.0, p[1])
                pt.radius = rad
                ww = w[i] if isinstance(w, list) else w
                for b, val in (ww or {}).items():
                    idx, vals = wmap.setdefault(b, ([], []))
                    idx.append(gi)
                    vals.append(val)
                gi += 1
        for b, (idx, vals) in wmap.items():
            drawing.set_vertex_weights(vertex_group_name=b, indices=idx, weights=vals, assign_mode="REPLACE")
        drawing.tag_positions_changed()


def ell(cx, cz, rx, rz, n=20, rot=0.0):
    c, s = math.cos(rot), math.sin(rot)
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        x, z = rx * math.cos(a), rz * math.sin(a)
        out.append((cx + x * c - z * s, cz + x * s + z * c))
    return out


def hull(pts):
    pts = sorted(set(pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def tube(x, ztop, length, r0, r1, n=9, cap=6):
    """Rest-pose capsule hanging down from ztop. Returns [(x, z, u)] with u = 0..1 along the length."""
    pts = []
    for i in range(n + 1):
        u = i / n
        pts.append((x - (r0 + (r1 - r0) * u), ztop - u * length, u))
    for k in range(1, cap):
        a = math.pi + math.pi * k / cap
        pts.append((x + r1 * math.cos(a), ztop - length + r1 * math.sin(a), 1.0))
    for i in range(n, -1, -1):
        u = i / n
        pts.append((x + (r0 + (r1 - r0) * u), ztop - u * length, u))
    for k in range(1, cap):
        a = math.pi * k / cap
        pts.append((x + r0 * math.cos(a), ztop + r0 * math.sin(a), 0.0))
    return pts


def place_down(pf, hx, hz, ang):
    """Rotate a capsule built hanging down from (0,0) so that it points along (sin ang, -cos ang) from (hx, hz)."""
    c, s = math.cos(ang), math.sin(ang)
    return [(hx + x * c - z * s, hz + x * s + z * c) for x, z, u in pf]


def chain(bones, breaks, bw):
    """Weight function u -> {bone: w}: smooth blend across each break (linear blend skinning)."""
    def f(u):
        s = [sm((u - (k - bw)) / (2 * bw)) for k in breaks]
        ws = [1 - s[0]] + [s[i] - s[i + 1] for i in range(len(s) - 1)] + [s[-1]]
        return {b: w for b, w in zip(bones, ws) if w > 1e-4}
    return f


# --------------------------------------------------------------------------- the rigs (one per body yaw)
def side_name(s):
    return "L" if s > 0 else "R"


def bone_table(psi):
    c = math.cos(math.radians(psi))
    t = {}   # name -> (parent, head(x,z), tail(x,z), rest 'up'|'down'|angle)
    t["hips"] = (None, (0, HIP_Z), (0, HIP_Z - 0.08))
    t["torso"] = ("hips", (0, HIP_Z), (0, NECK_Z))
    t["head"] = ("torso", (0, NECK_Z), (0, HEAD_Z))
    for s in (-1, 1):
        n = side_name(s)
        hx, sx = s * HIP_X * c, s * SH_X * c
        t["thigh_" + n] = ("hips", (hx, HIP_Z), (hx, HIP_Z - THIGH))
        t["shin_" + n] = ("thigh_" + n, (hx, HIP_Z - THIGH), (hx, ANK_Z0))
        t["foot_" + n] = ("shin_" + n, (hx, ANK_Z0), (hx, ANK_Z0 - 0.08))
        t["uarm_" + n] = ("torso", (sx, SH_Z), (sx, SH_Z - UARM))
        t["farm_" + n] = ("uarm_" + n, (sx, SH_Z - UARM), (sx, SH_Z - UARM - FARM))
        wz = SH_Z - UARM - FARM
        t["hand_" + n] = ("farm_" + n, (sx, wz), (sx, wz - 0.11))
        fan_k = 0.25 + 0.75 * c
        for k, fa in enumerate(FAN):
            a = fa * fan_k * s * -1
            bx = sx + (k - 1.5) * 0.026 * fan_k * 1.0
            t["f%d_%s" % (k, n)] = ("hand_" + n, (bx, wz - 0.085),
                                    (bx + FING_L * math.sin(a), wz - 0.085 - FING_L * math.cos(a)))
        a = s * 1.0 * fan_k + 0.0   # thumb: outward
        tx = sx + s * 0.04 * fan_k
        t["thumb_" + n] = ("hand_" + n, (tx, wz - 0.06), (tx + 0.066 * math.sin(a), wz - 0.06 - 0.066 * math.cos(a)))
    return t


def make_armature(name, table):
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    eb = {}
    for n, (par, h, tl) in table.items():
        b = arm.edit_bones.new(n)
        b.head, b.tail = (h[0], 0, h[1]), (tl[0], 0, tl[1])
        b.align_roll((0, 1, 0))
        eb[n] = b
    for n, (par, h, tl) in table.items():
        if par:
            eb[n].parent = eb[par]
            eb[n].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in ob.pose.bones:
        pb.rotation_mode = "XYZ"
    return ob


def rest_angle(table, n):
    _, h, t = table[n]
    return math.atan2(-(t[0] - h[0]), -(t[1] - h[1]))   # same convention as the pose angles (rest down = 0)


def build_body(gp, psi, D):
    """All body strokes at rest for yaw psi, in draw order (far side first), weighted to this view's bones."""
    c, s_ = math.cos(math.radians(psi)), math.sin(math.radians(psi))
    line = rgba(D["outline"])
    m_coat = get_mat(rgba(D["coat"]), line)
    m_coat2 = get_mat(rgba(D["coat"], 1), None)
    m_trs = get_mat(rgba(D["trousers"]), line)
    m_boot = get_mat(rgba(D["boots"]), line)
    m_skin = get_mat(rgba(D["skin"]), line)
    m_dark = get_mat(None, line, filled=False)
    sb = SB(gp)
    table = bone_table(psi)

    def leg(s):
        n = side_name(s)
        hx = s * HIP_X * c
        pts = tube(hx, HIP_Z, THIGH + SHIN, 0.088, 0.066, n=14)
        wf = chain(["thigh_" + n, "shin_" + n], [THIGH / (THIGH + SHIN)], 0.085)
        sb.add([(p[0], p[1]) for p in pts], m_trs, True, R_LINE, [wf(p[2]) for p in pts])
        # boot: convex hull of the profile projected at this yaw (width sheared in), ankle at (hx, ANK_Z0)
        prof = [(-0.075, 0.14), (0.075, 0.14), (0.09, 0.02), (0.17, 0.0), (0.2, -0.04), (0.18, -0.08),
                (-0.06, -0.08), (-0.085, -0.04)]
        pts2 = []
        for f, z in prof:
            for sg in (-1, 1):
                pts2.append((hx + f * s_ + sg * 0.068 * c, ANK_Z0 + z))
        hp = hull(pts2)
        wts = []
        for x, z in hp:
            ws = sm((z - ANK_Z0 - 0.0) / 0.12)
            wts.append({"shin_" + n: ws, "foot_" + n: 1 - ws} if ws > 1e-3 else {"foot_" + n: 1.0})
        sb.add(hp, m_boot, True, R_LINE, wts)

    def arm(s):
        n = side_name(s)
        sx = s * SH_X * c
        L = UARM + FARM
        pts = tube(sx, SH_Z, L, 0.064, 0.052, n=14)
        wf = chain(["uarm_" + n, "farm_" + n], [UARM / L], 0.10)
        sb.add([(p[0], p[1]) for p in pts], m_coat, True, R_LINE, [wf(p[2]) for p in pts])
        wz = SH_Z - L
        fk = 0.25 + 0.75 * c
        for k, fa in enumerate(FAN):                  # fingers first, palm over their roots
            fb = "f%d_%s" % (k, n)
            tb = table[fb]
            hx, hz = tb[1]
            tx, tz = tb[2]
            ang = math.atan2(tx - hx, -(tz - hz))
            pp = place_down(tube(0, 0, FING_L, 0.021, 0.016, n=5, cap=5), hx, hz, ang)
            sb.add(pp, m_skin, True, R_LINE * 0.9, {fb: 1.0})
        # thumb
        tb = table["thumb_" + n]
        hx, hz = tb[1]
        tx, tz = tb[2]
        ang = math.atan2(tx - hx, -(tz - hz))
        pp = place_down(tube(0, 0, 0.066, 0.023, 0.018, n=4, cap=5), hx, hz, ang)
        sb.add(pp, m_skin, True, R_LINE * 0.9, {"thumb_" + n: 1.0})
        palm = ell(sx, wz - 0.05, 0.062 * (0.55 + 0.45 * c) + 0.012, 0.062, 16)
        sb.add(palm, m_skin, True, R_LINE * 0.9, {"hand_" + n: 1.0})
        # cuff band so the sleeve ends cleanly
        sb.add(ell(sx, wz + 0.004, 0.056 * (0.7 + 0.3 * c) + 0.01, 0.022, 12), m_coat, True, R_LINE,
               {"farm_" + n: 1.0})

    # hood bunched at the back of the neck (behind everything of the torso)
    sb.add(ell(-0.13 * s_, NECK_Z - 0.02, 0.10, 0.085, 14), m_coat, True, R_LINE, {"torso": 1.0})
    arm(+1)          # far arm (character's left)
    leg(+1)          # far leg
    leg(-1)          # near leg
    # torso: A-line raincoat, cross-section ellipse projected at this yaw
    ztop, zhem = NECK_Z - 0.03, 0.66
    pts = []

    def halfw(z):
        u = (ztop - z) / (ztop - zhem)
        al, af = lerp(0.20, 0.255, u), lerp(0.125, 0.17, u)
        return math.sqrt((al * c) ** 2 + (af * s_) ** 2) + 0.012
    zs = [ztop - (ztop - zhem) * i / 12 for i in range(13)]
    left = [(-halfw(z), z) for z in zs]
    right = [(halfw(z), z) for z in reversed(zs)]
    hemw = halfw(zhem)
    bottom = [(hemw * math.cos(a), zhem - 0.02 * math.sin(a)) for a in [math.pi * (1 + k / 6) for k in range(1, 6)]]
    top = [(halfw(ztop) * math.cos(a), ztop + 0.05 * math.sin(a)) for a in [math.pi * k / 6 for k in range(1, 6)]]
    pts = left + bottom + right + top
    sb.add(pts, m_coat, True, R_LINE, {"torso": 1.0})
    # zipper line + buttons on the front centre line
    fx = 0.15 * s_
    zl = [(fx + 0.0, ztop - 0.02 - i * 0.06) for i in range(8)]
    zl = [(halfw(z) * 0 + 0.0 + 0.17 * s_ * 0.9, z) for _, z in zl]
    sb.add(zl, m_dark, False, R_LINE * 0.8, {"torso": 1.0})
    for z in (0.95, 0.82, 0.70):
        sb.add(ell(0.17 * s_ * 0.9, z, 0.014, 0.014, 8), get_mat(rgba(D["outline"]), None), True, R_LINE, {"torso": 1.0})
    arm(-1)          # near arm (character's right)
    return sb, table


# --------------------------------------------------------------------------- the head (redrawn every frame)
def curl_grid(R):
    out = []
    for ti, th_deg in enumerate((6, 30, 54, 78, 102, 126, 148)):
        th = math.radians(th_deg)
        n = max(1, int(round(2 * math.pi * math.sin(th) * R / (0.40 * R))))
        for k in range(n):
            al = 2 * math.pi * (k + 0.5 * (ti % 2)) / n - math.pi
            out.append((th_deg, math.degrees(al), 0.21 * R * (1 + 0.12 * math.sin(3 * k + ti))))
    return out


def hairline_deg(ad):
    ad = abs(ad)
    return 56 + (ad / 90) ** 2 * 34 if ad <= 90 else 90 + (ad - 90) / 90 * 45


def draw_head(gp, phi_deg, D, expr="smile", blink=0.0, gaze=(0.0, 0.0)):
    R = HEAD_R
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    W_ = {"head": 1.0}
    line = rgba(D["outline"])
    m_hair = get_mat(rgba(D["hair"]), line)
    m_skin = get_mat(rgba(D["skin"]), line)
    m_white = get_mat(rgba("#ffffff"), line)
    m_eye = get_mat(rgba(D["eye"]), None)
    m_hl = get_mat(rgba("#ffffff"), None)
    m_cheek = get_mat(rgba(D["cheek"]), None)
    m_nose = get_mat(rgba(D["skin"]), line)
    m_brow = get_mat(None, rgba(D["eye"]), filled=False)
    m_mouth = get_mat(None, rgba("#7a2e2e"), filled=False)
    m_open = get_mat(rgba("#8c2f35"), line)
    sb = SB(gp)

    def P(l, f, z):
        return (l * cp + f * sp, HEAD_Z + z), f * cp - l * sp

    def surf(l, z, push=0.0):
        # the face is flatter than the skull: features sit at most 0.74R forward, so in profile they stay inside the outline
        f = min(math.sqrt(max(R * R - l * l - z * z, 0.0)), 0.74 * R) + push
        return P(l, f, z)

    # curls, farthest first
    curls = []
    for th_deg, al_deg, cr in curl_grid(R):
        if th_deg > hairline_deg(al_deg) + 12:
            continue
        th, al = math.radians(th_deg), math.radians(al_deg)
        l, f, z = R * 1.0 * math.sin(th) * math.sin(al), R * 1.0 * math.sin(th) * math.cos(al), R * math.cos(th)
        (sx, sz), dep = P(l, f, z)
        front = dep > 0.25 * R and th_deg < hairline_deg(al_deg) - 14
        curls.append((dep, sx, sz, cr, front))
    curls.sort(key=lambda c: c[0])
    for dep, sx, sz, cr, front in curls:
        if not front:
            sb.add(ell(sx, sz, cr, cr, 14), m_hair, True, R_LINE, W_)
    sb.add(ell(0, HEAD_Z, R, R * 0.985, 40), m_skin, True, R_LINE, W_)
    # hair cap: visible hairline arc + silhouette arc over the top
    ring = []
    for k in range(0, 361, 8):
        al = math.radians(k - 180)
        th = math.radians(hairline_deg(k - 180))
        (sx, sz), dep = P(R * math.sin(th) * math.sin(al), R * math.sin(th) * math.cos(al), R * math.cos(th))
        ring.append((sx, sz - HEAD_Z, dep))
    n = len(ring) - 1
    ring = ring[:n]
    vis = [r[2] > 0 for r in ring]
    if any(vis) and not all(vis):
        i0 = next(i for i in range(n) if vis[i] and not vis[i - 1])
        arc = []
        i = i0
        while vis[i % n]:
            arc.append(ring[i % n])
            i += 1
        a_first = math.atan2(arc[0][1], arc[0][0])
        a_last = math.atan2(arc[-1][1], arc[-1][0])
        ccw = (a_first - a_last) % (2 * math.pi)
        use_ccw = ((math.pi / 2 - a_last) % (2 * math.pi)) <= ccw
        sweep = ccw if use_ccw else -((a_last - a_first) % (2 * math.pi))
        poly = [(p[0], HEAD_Z + p[1]) for p in arc]
        for k in range(1, 24):
            a = a_last + sweep * k / 24
            poly.append((R * math.cos(a), HEAD_Z + R * math.sin(a) * 0.985))
        sb.add(poly, m_hair, True, R_LINE, W_)
    # face features
    eyes_vis = []
    for sg in (-1, 1):
        l0, z0 = sg * 0.36 * R, 0.02 * R
        _, dep = surf(l0, z0)
        if dep < 0.10 * R:
            continue
        eyes_vis.append((sg, l0, z0))
    for sg, l0, z0 in eyes_vis:
        bh = 0.22 * R * (1 - 0.88 * blink)
        pts = [surf(l0 + 0.15 * R * math.cos(a), z0 + bh * math.sin(a))[0] for a in [2 * math.pi * i / 20 for i in range(20)]]
        sb.add(pts, m_white, True, R_LINE * 0.9, W_)
        if blink < 0.5:
            gl, gz = gaze
            pc = (l0 + gl * 0.05 * R, z0 - 0.015 * R + gz * 0.04 * R)
            pts = [surf(pc[0] + 0.10 * R * math.cos(a), pc[1] + 0.13 * R * math.sin(a), 0.004)[0]
                   for a in [2 * math.pi * i / 16 for i in range(16)]]
            sb.add(pts, m_eye, True, R_LINE, W_)
            hl = surf(pc[0] - 0.03 * R, pc[1] + 0.05 * R, 0.01)[0]
            sb.add(ell(hl[0], hl[1], 0.022 * R, 0.022 * R, 8), m_hl, True, R_LINE, W_)
        # brow
        arch = 0.05 * R + (0.03 * R if expr == "open" else 0.0)
        bp = []
        for i in range(9):
            u = i / 8
            l = l0 + (u - 0.5) * 0.30 * R
            z = z0 + 0.29 * R + arch * (1 - (2 * u - 1) ** 2) + sg * 0
            bp.append(surf(l, z, 0.01)[0])
        sb.add(bp, m_brow, False, 0.012, W_)
        # cheek
        cc = surf(sg * 0.56 * R, -0.22 * R)
        if cc[1] > 0.15 * R:
            pts = [surf(sg * 0.56 * R + 0.11 * R * math.cos(a), -0.22 * R + 0.075 * R * math.sin(a))[0]
                   for a in [2 * math.pi * i / 12 for i in range(12)]]
            sb.add(pts, m_cheek, True, R_LINE, W_)
    # nose (sticks out of the profile)
    _, dnose = surf(0, -0.12 * R, 0.29 * R)
    if dnose > 0.05 * R:
        pts = [surf(0.075 * R * math.cos(a), -0.12 * R + 0.06 * R * math.sin(a), 0.27 * R)[0]
               for a in [2 * math.pi * i / 12 for i in range(12)]]
        sb.add(pts, m_nose, True, R_LINE * 0.9, W_)
    # mouth
    _, dm = surf(0, -0.38 * R)
    if dm > 0.12 * R:
        if expr == "open":
            top = [surf(l, -0.30 * R, 0.01)[0] for l in [(-0.24 + 0.48 * i / 8) * R for i in range(9)]]
            bot = [surf(l, -0.30 * R - 0.20 * R * (1 - (l / (0.24 * R)) ** 2) - 0.02 * R, 0.01)[0]
                   for l in [(0.24 - 0.48 * i / 8) * R for i in range(1, 8)]]
            sb.add(top + bot, m_open, True, R_LINE * 0.9, W_)
        else:
            mp = [surf(l, -0.40 * R + 0.10 * R * (l / (0.22 * R)) ** 2, 0.01)[0]
                  for l in [(-0.22 + 0.44 * i / 10) * R for i in range(11)]]
            sb.add(mp, m_mouth, False, 0.012, W_)
    # front curls (fringe and crown)
    for dep, sx, sz, cr, front in curls:
        if front:
            sb.add(ell(sx, sz, cr, cr, 14), m_hair, True, R_LINE, W_)
    return sb


# --------------------------------------------------------------------------- motion (all the rules are plain code)
S_STEP = 0.42
V = S_STEP / 0.6
T_CYC = 1.2
X0 = -1.09
HIP_STAND = 0.766
BOOT_PROFILE = [(-0.075, 0.14), (0.075, 0.14), (0.09, 0.02), (0.17, 0.0), (0.2, -0.04), (0.18, -0.08),
                (-0.06, -0.08), (-0.085, -0.04)]


def pelvis_x_lin(t):
    return X0 + V * t


def pelvis_x(t):
    if t <= 1.2:
        return pelvis_x_lin(t)
    u = min(1.0, (t - 1.2) / 0.45)
    return pelvis_x_lin(1.2) + 0.6 * S_STEP * (1 - (1 - u) ** 1.25)


def ankle_z_for(pitch):
    """Ankle height so that the lowest boot point touches the ground at this foot pitch (rad, toe down +)."""
    c, s = math.cos(pitch), math.sin(pitch)
    return -min(-x * s + z * c for x, z in BOOT_PROFILE)


def stance_vals(p):
    pitch = -0.25 * (1 - sm(p / 0.1)) + 0.5 * sm((p - 0.4) / 0.2)
    return 0.6 * S_STEP - V * p * T_CYC, 0.0, pitch


def swing_vals(u):
    pitch = 0.5 * (1 - sm(u * 1.6)) - 0.25 * sm((u - 0.5) / 0.5)
    return -0.6 * S_STEP + 1.2 * S_STEP * sm(u), 0.085 * math.sin(math.pi * u), pitch


def foot_world(side, t):
    """Returns (X world, swing lift, pitch). side 'R' leads at t=0. Planted feet keep a constant X."""
    xr_plant = pelvis_x_lin(1.2) + 0.6 * S_STEP
    if side == "R":
        if t >= 1.2:
            return xr_plant, 0.0, -0.25 * (1 - sm((t - 1.2) / 0.12))
        p = t / T_CYC
        rel, lift, pitch = stance_vals(p) if p < 0.6 else swing_vals((p - 0.6) / 0.4)
        return pelvis_x_lin(t) + rel, lift, pitch
    # left foot
    if t < 1.32:
        p = (t / T_CYC + 0.5) % 1.0
        rel, lift, pitch = stance_vals(p) if p < 0.6 else swing_vals((p - 0.6) / 0.4)
        return pelvis_x_lin(t) + rel, lift, pitch
    xs = pelvis_x_lin(1.32) - 0.6 * S_STEP
    u = (t - 1.32) / 0.30
    if u >= 1:
        return xr_plant, 0.0, -0.25 * (1 - sm((t - 1.62) / 0.12))
    _, _, pit = swing_vals(u)
    return lerp(xs, xr_plant, sm(u)), 0.075 * math.sin(math.pi * u), 0.5 * (1 - sm(u * 1.6)) - 0.25 * sm((u - 0.5) / 0.5)


def pelvis_z(t):
    walk = 0.738 - 0.022 * math.cos(2 * math.pi * (min(t, 1.2) / 0.6 - 0.05))
    return lerp(walk, HIP_STAND, sm((t - 1.2) / 0.35))


def leg_ik(hip_z, dx, az):
    """Planar 2-bone IK in (forward, up). Returns thigh and shin forward-swing angles (rad)."""
    dz = az - hip_z
    d = min(math.hypot(dx, dz), THIGH + SHIN - 1e-3)
    d = max(d, abs(THIGH - SHIN) + 1e-3)
    delta = math.atan2(dx, -dz)
    ang = math.acos(max(-1, min(1, (THIGH ** 2 + d ** 2 - SHIN ** 2) / (2 * THIGH * d))))
    bt = delta + ang                                   # knee forward of the hip-ankle line
    kx, kz = THIGH * math.sin(bt), -THIGH * math.cos(bt)
    ax, az2 = d * math.sin(delta), -d * math.cos(delta)
    bs = math.atan2(ax - kx, -(az2 - kz))
    return bt, bs


def seg_theta(v, psi, rest="down"):
    """Pose angle (rad, about +Y) of a 3D direction v=(lateral, forward, up) seen at body yaw psi."""
    c, s = math.cos(math.radians(psi)), math.sin(math.radians(psi))
    px, pz = v[0] * c + v[1] * s, v[2]
    return math.atan2(-px, -pz) if rest == "down" else math.atan2(px, pz)


def arm_dir(side, a, b):
    v = (side * math.sin(a), math.sin(b), -math.cos(a) * math.cos(b))
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


def state(t):
    """Everything the pose needs at time t (seconds)."""
    st = {}
    walkamp = 1 - sm((t - 1.2) / 0.35)
    st["psi"] = 90 if t < 1.62 else 60 if t < 1.74 else 30 if t < 1.86 else 0
    st["phi"] = 90 * (1 - sm((t - 1.30) / 0.45))
    st["pelvis"] = (pelvis_x(t), pelvis_z(t))
    # feet
    px = pelvis_x(t)
    hz = pelvis_z(t)
    st["legs"] = {}
    for side, sg in (("R", -1), ("L", 1)):
        X, lift, pitch = foot_world(side, t)
        az = ankle_z_for(pitch) + lift
        bt, bs = leg_ik(hz, X - px, az)
        st["legs"][side] = (bt, bs, pitch)
    # torso / head
    st["lean"] = 0.07 * walkamp + 0.02 * math.sin(t * 2.1) * (1 - walkamp)
    st["sway"] = 0.025 * math.sin(2 * math.pi * 1.1 * t) * sm((t - 2.0) / 0.2)
    tilt = -0.22 * sm((t - 2.05) / 0.35)
    if t > 2.4:
        tilt += 0.025 * math.sin(2 * math.pi * 1.1 * (t - 2.4))
    st["tilt"] = tilt
    st["nod"] = 0.04 * math.sin(2 * math.pi * t / 0.6) * walkamp - 0.03 * sm((t - 1.25) / 0.1) * (1 - sm((t - 1.5) / 0.2))
    # arms
    swing = 0.45 * math.cos(2 * math.pi * min(t, 1.2) / T_CYC) * walkamp
    r = sm((t - 2.0) / 0.28)
    w_t = t - 2.28
    wv = math.sin(2 * math.pi * 2.2 * w_t) * sm(w_t / 0.1) if t > 2.28 else 0.0
    arms = {}
    for side, sg in (("L", 1), ("R", -1)):
        b1 = swing * sg
        a1, a2 = 0.10, 0.12
        b2 = b1 + 0.30 + 0.25 * max(0.0, b1) * 2
        hand_rel, openf, wig = 0.0, 0.35, 0.0
        if side == "R":
            a1 = lerp(0.10, 1.52, r)
            a2 = lerp(0.12, 2.80, r) + 0.32 * wv * r
            b1, b2 = lerp(b1, 0.0, r), lerp(b2, 0.0, r)
            hand_rel = sg * -0.30 * math.sin(2 * math.pi * 2.2 * w_t - 0.9) * r * (1 if t > 2.28 else 0)
            openf = lerp(0.35, 1.0, r)
            wig = r
        arms[side] = (arm_dir(sg, a1, b1), arm_dir(sg, a2, b2), hand_rel, openf, wig)
    st["arms"] = arms
    st["t"] = t
    st["expr"] = "open" if t > 2.02 else "smile"
    blink = 0.0
    for bt0 in (0.9, 2.55):
        d = abs(t - bt0 - 0.04)
        blink = max(blink, max(0.0, 1 - d / 0.055))
    st["blink"] = min(1.0, blink)
    pulse = sm((t - 1.25) / 0.2) * (1 - sm((t - 1.55) / 0.3))
    st["gaze"] = (-0.9 * pulse, 0.0)
    return st


def apply_pose(view, st):
    psi = view["psi"]
    table, ob = view["table"], view["arm"]
    sp = math.sin(math.radians(psi))
    cps = math.cos(math.radians(psi))
    ab = {}                                   # absolute bone angle relative to rest
    ab["hips"] = 0.0
    ab["torso"] = st["lean"] * sp + st["sway"] * cps
    phi = math.radians(st["phi"])
    ab["head"] = ab["torso"] + st["tilt"] * math.cos(phi) + st["nod"] * math.sin(phi)
    for side in ("L", "R"):
        bt, bs, pitch = st["legs"][side]
        ab["thigh_" + side] = seg_theta((0, math.sin(bt), -math.cos(bt)), psi) - rest_angle(table, "thigh_" + side)
        ab["shin_" + side] = seg_theta((0, math.sin(bs), -math.cos(bs)), psi) - rest_angle(table, "shin_" + side)
        ab["foot_" + side] = pitch * sp
        v1, v2, hrel, openf, wig = st["arms"][side]
        ab["uarm_" + side] = seg_theta(v1, psi) - rest_angle(table, "uarm_" + side)
        ab["farm_" + side] = seg_theta(v2, psi) - rest_angle(table, "farm_" + side)
        ab["hand_" + side] = ab["farm_" + side] + hrel
        t = st["t"]
        for k, fa in enumerate(FAN):
            rest_fan = rest_angle(table, "f%d_%s" % (k, side))
            rel = -rest_fan * (1 - openf) + 0.14 * wig * math.sin(2 * math.pi * 4.4 * (t - 2.28) + k * 0.8)
            ab["f%d_%s" % (k, side)] = ab["hand_" + side] + rel
        ab["thumb_" + side] = ab["hand_" + side] - rest_angle(table, "thumb_" + side) * (1 - openf) * 0.6
    for n, (par, h, tl) in table.items():
        pb = ob.pose.bones[n]
        pb.rotation_euler = (0.0, 0.0, ab[n] - (ab[par] if par else 0.0))
        pb.location = (0.0, 0.0, 0.0)
    px, pz = st["pelvis"]
    root = ob.pose.bones["hips"]
    off = root.bone.matrix_local.to_3x3().inverted() @ __import__("mathutils").Vector((px, 0.0, pz - HIP_Z))
    root.location = off


# --------------------------------------------------------------------------- scene build + render
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    return sc


def build_scene():
    sc = reset_scene()
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = int(W * SCALE), int(H * SCALE)
    sc.render.fps = FPS
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"
    try:
        sc.view_settings.look = "None"
    except Exception:
        pass
    try:
        sc.eevee.taa_render_samples = 24
    except Exception:
        pass
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = rgba(DESIGN["bg"])
    bg.inputs[1].default_value = 1.0
    sc.world = world
    cam = bpy.data.cameras.new("cam")
    cam.type = "ORTHO"
    cam.ortho_scale = 2.9 * 16 / 9
    co = bpy.data.objects.new("cam", cam)
    sc.collection.objects.link(co)
    co.location = (0.0, -10.0, 1.25)
    co.rotation_euler = (math.pi / 2, 0, 0)
    sc.camera = co

    views = []
    for psi in VIEWS:
        table = bone_table(psi)
        arm = make_armature("rig%d" % psi, table)
        gp = bpy.data.grease_pencils.new("body%d" % psi)
        gob = bpy.data.objects.new("body%d" % psi, gp)
        sc.collection.objects.link(gob)
        lay = gp.layers.new("body")
        lay.use_lights = False
        for n in table:
            gob.vertex_groups.new(name=n)
        sb, _ = build_body(gp, psi, DESIGN)
        sb.flush(lay.frames.new(1).drawing)
        mod = gob.modifiers.new("arm", "GREASE_PENCIL_ARMATURE")
        mod.object = arm
        views.append(dict(psi=psi, arm=arm, gp=gob, table=table))
    # head: one object, redrawn per frame, deformed by whichever view rig is active
    hgp = bpy.data.grease_pencils.new("head")
    hob = bpy.data.objects.new("head", hgp)
    hob.location = (0, -0.1, 0)
    sc.collection.objects.link(hob)
    hl = hgp.layers.new("head")
    hl.use_lights = False
    hl.frames.new(1)
    for n in views[0]["table"]:
        hob.vertex_groups.new(name=n)
    hmod = hob.modifiers.new("arm", "GREASE_PENCIL_ARMATURE")
    hmod.object = views[0]["arm"]
    # soft ground shadow: stacked translucent ellipses (flat 2D, no lighting)
    sgp = bpy.data.grease_pencils.new("shadow")
    sob = bpy.data.objects.new("shadow", sgp)
    sob.location = (0, 0.3, 0)
    sc.collection.objects.link(sob)
    sl = sgp.layers.new("s")
    sl.use_lights = False
    ssb = SB(sgp)
    for i in range(7):
        k = 1 - i / 7
        ssb.add(ell(0, 0.0, 0.30 + 0.22 * k, 0.035 + 0.035 * k, 28), get_mat((0.25 * 0.1, 0.2 * 0.1, 0.15 * 0.1, 0.07), None), True, 0.001)
    ssb.flush(sl.frames.new(1).drawing)
    return sc, views, hob, hmod, hgp, sob


def encode_and_sheet(out):
    clip = os.path.join(out, "clip.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(TMP, "f_%03d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", "-preset", "slow", clip], check=True)
    picks = [round(i * (NFRAMES - 1) / 7) for i in range(8)]
    sel = "+".join("eq(n,%d)" % p for p in picks)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf",
                    "select='%s',scale=640:360,tile=4x2:padding=4:color=white" % sel, "-frames:v", "1", "-fps_mode", "passthrough",
                    os.path.join(out, "sheet.png")], check=True)
    return picks


def check():
    # planted-foot test: world X of a foot must not change while it is in stance
    import itertools
    for side in "RL":
        xs = [(f, foot_world(side, f / FPS)) for f in range(0, 50)]
        runs, cur = [], [xs[0]]
        for a, b in zip(xs, xs[1:]):
            if abs(b[1][0] - a[1][0]) < 1e-6:
                cur.append(b)
            else:
                if len(cur) > 2:
                    runs.append((cur[0][0], cur[-1][0]))
                cur = [b]
        runs.append((cur[0][0], cur[-1][0]))
        print("CHECK foot", side, "planted frame runs (start,end):", [r for r in runs if r[1] - r[0] > 1])
    for t in (0, 0.3, 0.6, 0.9, 1.2, 1.5, 2.0, 2.5):
        st = state(t)
        print("CHECK t=%.1f pelvis=(%.2f,%.2f) psi=%d phi=%.0f legs=%s" % (t, st["pelvis"][0], st["pelvis"][1], st["psi"], st["phi"],
              {k: tuple(round(x, 2) for x in v) for k, v in st["legs"].items()}))


def main():
    if "--check" in argv:
        return check()
    t_build = time.time()
    os.makedirs(OUT, exist_ok=True)
    if ONLY is None and os.path.isdir(TMP):
        shutil.rmtree(TMP)
    os.makedirs(TMP, exist_ok=True)
    sc, views, hob, hmod, hgp, sob = build_scene()
    print("scene built in %.1fs" % (time.time() - t_build))
    hd = hgp.layers[0].frames[0].drawing
    frames = ONLY if ONLY is not None else range(NFRAMES)
    t_r = time.time()
    n_done = 0
    for f in frames:
        t = f / FPS
        st = state(t)
        vi = VIEWS.index(st["psi"])
        for i, v in enumerate(views):
            v["gp"].hide_render = i != vi
        v = views[vi]
        apply_pose(v, st)
        hmod.object = v["arm"]
        sb = draw_head(hgp, st["phi"], DESIGN, st["expr"], st["blink"], st["gaze"])
        sb.flush(hd)
        sob.location.x = sum(foot_world(s, t)[0] for s in "LR") / 2
        sc.render.filepath = os.path.join(TMP, "f_%03d.png" % (f + 1))
        bpy.context.view_layer.update()
        bpy.ops.render.render(write_still=True)
        n_done += 1
    dt = time.time() - t_r
    print("RENDER %d frames in %.1fs = %.2f s/frame" % (n_done, dt, dt / max(1, n_done)))
    if ONLY is None:
        picks = encode_and_sheet(OUT)
        print("sheet frames", picks)
        with open(os.path.join(OUT, "_timing.txt"), "w") as fh:
            fh.write("render_total_s=%.1f frames=%d s_per_frame=%.3f\n" % (dt, n_done, dt / n_done))


main()
