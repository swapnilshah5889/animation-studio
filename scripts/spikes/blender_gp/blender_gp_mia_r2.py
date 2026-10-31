#!/usr/bin/env python3
"""Spike, round 2: "Mia" drawn like an illustrator, as Blender Grease Pencil strokes (GPv3, Blender 5.x).

Round 1 built a character from spheres on rigid bones. Round 2 redraws the WHOLE character every frame from
pose parameters, the way the face was drawn per frame in earlier work:
  * a 3D stick skeleton is solved per frame in code (3-D two-bone IK, planted feet with heel/ball roll,
    key-pose walk, anticipation + overshoot on the wave, a turn made of a head lead, a body turn and two
    small foot steps);
  * every form is a Bezier/Catmull-Rom ribbon or hull, filled flat with ONE shadow shape, outlined with a
    variable-width stroke (thick on the shadow side, thin on the lit side, tapered at the ends);
  * limbs are ribbons through the joints, so the outline continues round every bend;
  * the head is a small 3-D model (cranium + cheek + jaw circles, features on a face sphere) projected each
    frame, so skin, hair and face turn as one form from front to side with no view swap;
  * hair locks, coat hem and hood lag behind the body (damped springs run before drawing).
Blender is only the stroke renderer (flat, unlit, EEVEE); all drawing and animation rules live in this file.

Run (headless, idempotent, wipes the output frame folder):
  Blender --background --python blender_gp_mia_r2.py -- --out DIR [--mode clip|sheet|both] [--frames 0,24,48]
  Blender --background --python blender_gp_mia_r2.py -- --check        (foot planting numbers, no rendering)
"""
import math
import os
import shutil
import subprocess
import sys
import time

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


OUT = arg("--out", "/Users/uchiha/ai-studio/scratch/blender-compare/grease-pencil-r2")
MODE = arg("--mode", "both")
ONLY = [int(x) for x in arg("--frames").split(",")] if arg("--frames") else None
TMP = os.path.join(OUT, "_frames")
FPS, NFRAMES, W, H = 24, 72, 1280, 720

D = dict(hair="#6a3a1d", hair_sh="#4b2713", hair_hl="#b98150", coat="#f5c518", coat_sh="#d9a20f",
         trs="#2f5fc4", trs_sh="#234a9c", boot="#d6312b", boot_sh="#a62320", sole="#4a2c20",
         skin="#f6c29b", skin_sh="#e3a47c", line="#3a2418", eye="#5a3620", pupil="#1d1209",
         cheek="#f08f86", mouth="#8c2f35", tongue="#e8736f", bg="#f3eedf")
R_LINE = 0.0056

# proportions (scene units, ground z = 0, character about 1.65 tall, head about 1/3 of the height)
RH = 0.265                      # head radius
HIP_W, SH_W = 0.07, 0.15
THIGH, SHIN, ANK = 0.29, 0.27, 0.10
UARM, FARM = 0.19, 0.17
SPINE = 0.41                    # pelvis to neck base
HEM = -0.14                     # coat hem below the pelvis
NECK_TOP = 0.43


# --------------------------------------------------------------------------- small maths
def sm(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def vadd(a, b):
    return tuple(x + y for x, y in zip(a, b))


def vsub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def vmul(a, k):
    return tuple(x * k for x in a)


def vdot(a, b):
    return sum(x * y for x, y in zip(a, b))


def vlen(a):
    return math.sqrt(vdot(a, a))


def vunit(a):
    n = vlen(a) or 1.0
    return tuple(x / n for x in a)


def mm(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mv(A, v):
    return tuple(sum(A[i][k] * v[k] for k in range(3)) for i in range(3))


def R_yaw(psi):
    c, s = math.cos(psi), math.sin(psi)
    return [[c, s, 0], [s, -c, 0], [0, 0, 1]]      # local (lat, fwd, up) -> world (x right, y away, z up)


def R_pitch(n):
    c, s = math.cos(n), math.sin(n)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]       # n > 0: face/top tilts back


def R_roll(r):
    c, s = math.cos(r), math.sin(r)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]       # r > 0: top tilts toward +lat


def body_rot(psi, lean, side):
    return mm(R_yaw(psi), mm(R_roll(side), R_pitch(-lean)))


def ch(t, keys):
    """Smooth channel through keys [(t, v)...] (cubic Hermite, Catmull-Rom tangents): ease in/out, overshoot where keyed."""
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    i = 0
    while keys[i + 1][0] < t:
        i += 1

    def tan(j):
        a, b = max(j - 1, 0), min(j + 1, len(keys) - 1)
        return (keys[b][1] - keys[a][1]) / (keys[b][0] - keys[a][0])
    t0, v0 = keys[i]
    t1, v1 = keys[i + 1]
    h = t1 - t0
    u = (t - t0) / h
    u2, u3 = u * u, u * u * u
    return ((2 * u3 - 3 * u2 + 1) * v0 + (u3 - 2 * u2 + u) * tan(i) * h
            + (-2 * u3 + 3 * u2) * v1 + (u3 - u2) * tan(i + 1) * h)


# --------------------------------------------------------------------------- 2-D drawing helpers
def catmull(pts, n=6, closed=False):
    P, N, out = pts, len(pts), []
    for i in range(N if closed else N - 1):
        p0 = P[(i - 1) % N] if (closed or i > 0) else P[0]
        p1, p2 = P[i], P[(i + 1) % N]
        p3 = P[(i + 2) % N] if (closed or i + 2 < N) else P[-1]
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in (0, 1)))
    if not closed:
        out.append(P[-1])
    return out


def area(P):
    return 0.5 * sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))


def ccw(P):
    return P if area(P) > 0 else P[::-1]


def ell(cx, cz, rx, rz, n=20, rot=0.0):
    c, s = math.cos(rot), math.sin(rot)
    return [(cx + rx * math.cos(2 * math.pi * i / n) * c - rz * math.sin(2 * math.pi * i / n) * s,
             cz + rx * math.cos(2 * math.pi * i / n) * s + rz * math.sin(2 * math.pi * i / n) * c) for i in range(n)]


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


def interp(s, keys):
    """Piecewise-smooth lookup of a profile [(s, value)...]."""
    if s <= keys[0][0]:
        return keys[0][1]
    for i in range(len(keys) - 1):
        if s <= keys[i + 1][0]:
            u = (s - keys[i][0]) / (keys[i + 1][0] - keys[i][0])
            return lerp(keys[i][1], keys[i + 1][1], sm(u))
    return keys[-1][1]


def edges(center, hw):
    L, R = [], []
    n = len(center)
    for i in range(n):
        a, b = center[max(i - 1, 0)], center[min(i + 1, n - 1)]
        tx, tz = b[0] - a[0], b[1] - a[1]
        d = math.hypot(tx, tz) or 1.0
        nx, nz = -tz / d, tx / d
        L.append((center[i][0] + nx * hw[i], center[i][1] + nz * hw[i]))
        R.append((center[i][0] - nx * hw[i], center[i][1] - nz * hw[i]))
    return L, R


def cap(c, ang, r, m=6):
    """Semicircle around c, starting at angle ang+90deg (left of travel) sweeping through ang (the tip direction)."""
    return [(c[0] + r * math.cos(ang + math.pi / 2 - math.pi * k / m), c[1] + r * math.sin(ang + math.pi / 2 - math.pi * k / m))
            for k in range(1, m)]


def ribbon(center, hw, round_end=True, round_start=True):
    """Closed tapered ribbon polygon around a dense centre line (left edge, end cap, right edge back, start cap)."""
    L, R = edges(center, hw)
    a1 = math.atan2(center[-1][1] - center[-2][1], center[-1][0] - center[-2][0])
    a0 = math.atan2(center[1][1] - center[0][1], center[1][0] - center[0][0])
    poly = L + (cap(center[-1], a1, hw[-1]) if round_end else []) + R[::-1]
    if round_start:
        poly += cap(center[0], a0 + math.pi, hw[0])
    return poly, L, R


def strip(edge, center, k, wave=0.0):
    """Shadow shape: the part of a ribbon between one edge and a line k of the way to its centre."""
    n = len(edge)
    inner = []
    for i, (e, c) in enumerate(zip(edge, center)):
        kk = k * (1 + wave * math.sin(i * 1.7))
        inner.append((e[0] + (c[0] - e[0]) * kk, e[1] + (c[1] - e[1]) * kk))
    return list(edge) + inner[::-1]


def crescent(poly, a0, a1, depth, centre=None):
    """Shadow crescent on the outline arc between angles a0..a1 (degrees, 0 = +x, ccw) pulled toward the centre."""
    P = ccw(poly)
    cx, cz = centre or (sum(p[0] for p in P) / len(P), sum(p[1] for p in P) / len(P))
    outer, inner = [], []
    angs = [math.degrees(math.atan2(p[1] - cz, p[0] - cx)) for p in P]
    out_i = [i for i, a in enumerate(angs) if not (a0 <= a <= a1)]
    if not out_i:
        return None
    k0 = out_i[0]
    P = P[k0:] + P[:k0]                 # start outside the arc so the arc points are contiguous
    for p in P:
        a = math.degrees(math.atan2(p[1] - cz, p[0] - cx))
        if a0 <= a <= a1:
            u = (a - a0) / (a1 - a0)
            k = depth * math.sin(math.pi * u) ** 0.8
            outer.append(p)
            inner.append((p[0] + (cx - p[0]) * k, p[1] + (cz - p[1]) * k))
    return outer + inner[::-1] if len(outer) > 3 else None


def inked_radii(P, base, light=(-0.55, 0.83), lo=0.42, hi=1.55):
    """Variable line weight: thick where the outline faces away from the light, thin where it faces it."""
    n = len(P)
    r = []
    for i in range(n):
        a, b = P[i - 1], P[(i + 1) % n]
        tx, tz = b[0] - a[0], b[1] - a[1]
        d = math.hypot(tx, tz) or 1.0
        nx, nz = tz / d, -tx / d                     # outward normal for a ccw polygon
        k = -(nx * light[0] + nz * light[1])         # +1 facing away from the light
        r.append(base * lerp(lo, hi, sm((k + 0.7) / 1.7)))
    return [(r[i - 1] + 2 * r[i] + r[(i + 1) % n]) / 4 for i in range(n)]


def resample(pts, n):
    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    out, j = [], 0
    for k in range(n):
        t = d[-1] * k / (n - 1)
        while j < len(pts) - 2 and d[j + 1] < t:
            j += 1
        u = (t - d[j]) / ((d[j + 1] - d[j]) or 1.0)
        out.append((lerp(pts[j][0], pts[j + 1][0], u), lerp(pts[j][1], pts[j + 1][1], u)))
    return out


def tapered(n, base, a=0.18, b=0.18, mid=1.0, floor=0.25):
    out = []
    for i in range(n):
        u = i / max(1, n - 1)
        k = min(1.0, u / a) if a > 0 else 1.0
        k2 = min(1.0, (1 - u) / b) if b > 0 else 1.0
        out.append(base * (floor + (mid - floor) * sm(min(k, k2)) ** 0.7))
    return out


# --------------------------------------------------------------------------- Grease Pencil writer
_MATS = {}
_FILLED = set()
bpy = None


def rgba(hexs, a=1.0):
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    h = hexs.lstrip("#")
    return tuple(lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)) + (a,)


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
    """Collects strokes in draw order (with a scale/offset transform), then writes them into one GP drawing."""

    def __init__(self, black=False):
        self.items, self.black = [], black
        self.S, self.ox, self.oz = 1.0, 0.0, 0.0

    def xf(self, S=1.0, ox=0.0, oz=0.0):
        self.S, self.ox, self.oz = S, ox, oz

    def _p(self, pts):
        return [(p[0] * self.S + self.ox, p[1] * self.S + self.oz) for p in pts]

    def fill(self, pts, color, alpha=1.0):
        if not pts or len(pts) < 3 or (self.black and alpha < 0.5):
            return
        self.items.append(("f", self._p(pts), "#000000" if self.black else color, alpha, 0.001, True))

    def ink(self, pts, color, radii, cyclic=False):
        if len(pts) < 2:
            return
        if not isinstance(radii, list):
            radii = [radii] * len(pts)
        self.items.append(("l", self._p(pts), "#000000" if self.black else color, 1.0, [r * self.S for r in radii], cyclic))

    def shape(self, pts, fill, line=None, shade=None, shade_col=None, w=1.0):
        P = ccw(pts)
        self.fill(P, fill)
        if shade:
            self.fill(shade, shade_col)
        self.ink(P, line or D["line"], inked_radii(P, R_LINE * w), True)

    def line(self, pts, color, w=1.0, a=0.2, b=0.2, floor=0.3):
        self.ink(pts, color, tapered(len(pts), R_LINE * w, a, b, 1.0, floor), False)

    def flush(self, gp, drawing):
        n = len(drawing.strokes)
        if n:
            drawing.remove_strokes(indices=list(range(n)))
        if not self.items:
            return
        mats = []
        for kind, pts, col, alpha, rad, cyc in self.items:
            m = get_mat(rgba(col, alpha), None, True) if kind == "f" else get_mat(None, rgba(col), False)
            if m not in gp.materials[:]:
                gp.materials.append(m)
            mats.append([x for x in gp.materials].index(m))
        drawing.add_strokes([len(it[1]) for it in self.items])
        for si, (kind, pts, col, alpha, rad, cyc) in enumerate(self.items):
            s = drawing.strokes[si]
            s.material_index = mats[si]
            s.cyclic = cyc
            s.fill_opacity = 1.0
            s.fill_id = (si + 1) if kind == "f" else 0
            for i, p in enumerate(pts):
                pt = s.points[i]
                pt.position = (p[0], 0.0, p[1])
                pt.radius = rad[i] if isinstance(rad, list) else rad
        drawing.tag_positions_changed()


# --------------------------------------------------------------------------- feet: planted, heel/ball roll
HEEL_F, BALL_F, TOE_F = -0.07, 0.11, 0.20
V_WALK, X0 = 1.0, -1.1
DEC = 0.34


def pelvis_x_walk(t):
    if t <= 0.8:
        return X0 + V_WALK * t
    u = min(1.0, (t - 0.8) / 0.4)
    h10, h01 = u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2
    return X0 + 0.8 * V_WALK + V_WALK * 0.4 * h10 + DEC * h01


A_R1, A_L0, A_L1 = X0 + 0.24 * V_WALK, X0 - 0.16 * V_WALK, X0 + 0.64 * V_WALK
A_R2 = pelvis_x_walk(1.04)
A_L2 = A_R2 + 0.09
X_END = pelvis_x_walk(1.2)
X_C = (A_R2 + A_L2) / 2
FOOT_Y = 0.075
SLOT = {"R": (X_C - 0.085, 0.0), "L": (X_C + 0.085, 0.0)}


def pelvis_x(t):
    return pelvis_x_walk(t) + (X_C - X_END) * sm((t - 1.35) / 0.55) if t > 1.2 else pelvis_x_walk(t)


def fdir(yaw):
    return (math.sin(yaw), -math.cos(yaw))


def ankle_min_z(th):
    c, s = math.cos(th), math.sin(th)
    return -min(f * s - ANK * c for f in (HEEL_F, BALL_F, TOE_F)) if False else max(
        -(f * s + z * c) for f, z in ((HEEL_F, -ANK), (BALL_F, -ANK), (TOE_F, -0.085)))


def st_pose(seg, t):
    """Ankle (x, y, z), yaw, pitch for a stance segment ('ST', t0, t1, (ax, ay), yaw, roll_in, roll_out)."""
    _, t0, t1, (ax, ay), yaw, rin, rout = seg
    u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    th, pivot = 0.0, None
    if rin and u < 0.17:
        th, pivot = 0.38 * (1 - sm(u / 0.17)), "heel"
    elif rout and u > 0.66:
        th, pivot = -0.55 * sm((u - 0.66) / 0.34), "ball"
    fd = fdir(yaw)
    c, s = math.cos(th), math.sin(th)
    if pivot == "heel":
        hx, hy = ax + HEEL_F * fd[0], ay + HEEL_F * fd[1]
        f = 0.07 * c - ANK * s
        return (hx + fd[0] * f, hy + fd[1] * f, 0.07 * s + ANK * c), yaw, th
    if pivot == "ball":
        bx, by = ax + BALL_F * fd[0], ay + BALL_F * fd[1]
        f = -BALL_F * c - ANK * s
        return (bx + fd[0] * f, by + fd[1] * f, -BALL_F * s + ANK * c), yaw, th
    return (ax, ay, ANK), yaw, 0.0


SEGS = {
    "R": [("ST", -9, 0.48, (A_R1, -FOOT_Y), math.pi / 2, True, True),    # t0 = -9 would break u; fixed below
          ("SW", 0.48, 0.80, 0.075), ("ST", 0.80, 1.40, (A_R2, -FOOT_Y), math.pi / 2, True, False),
          ("SW", 1.40, 1.68, 0.05), ("ST", 1.68, 99, (SLOT["R"][0], SLOT["R"][1]), 0.0, False, False)],
    "L": [("ST", -0.40, 0.08, (A_L0, FOOT_Y), math.pi / 2, True, True),
          ("SW", 0.08, 0.40, 0.075), ("ST", 0.40, 0.88, (A_L1, FOOT_Y), math.pi / 2, True, True),
          ("SW", 0.88, 1.20, 0.075), ("ST", 1.20, 1.62, (A_L2, FOOT_Y), math.pi / 2, True, False),
          ("SW", 1.62, 1.90, 0.05), ("ST", 1.90, 99, (SLOT["L"][0], SLOT["L"][1]), 0.0, False, False)],
}
SEGS["R"][0] = ("ST", 0.0 - 0.0, 0.48, (A_R1, -FOOT_Y), math.pi / 2, True, True)


def foot_at(side, t):
    segs = SEGS[side]
    for i, sg in enumerate(segs):
        if sg[0] == "ST" and sg[1] <= t <= sg[2]:
            return st_pose(sg, t)
        if sg[0] == "SW" and sg[1] <= t <= sg[2]:
            p0, y0, th0 = st_pose(segs[i - 1], segs[i - 1][2])
            p1, y1, th1 = st_pose(segs[i + 1], segs[i + 1][1])
            u = (t - sg[1]) / (sg[2] - sg[1])
            e = sm(u) * 0.7 + u * 0.3 if sg[3] > 0.06 else sm(u)
            th = lerp(th0, th1, sm(u)) - 0.22 * math.sin(math.pi * min(1, u * 1.2))
            x, y = lerp(p0[0], p1[0], e), lerp(p0[1], p1[1], e)
            z = lerp(p0[2], p1[2], u) + sg[3] * math.sin(math.pi * u) ** 0.9
            z = max(z, ankle_min_z(th))
            return (x, y, z), lerp(y0, y1, sm(u)), th
    return st_pose(segs[-1], t)


# --------------------------------------------------------------------------- the animation (everything is keyed here)
def walk_amp(t):
    return 1 - sm((t - 0.85) / 0.45)


def state(t):
    st = {"t": t}
    wa = walk_amp(t)
    phi = 2 * math.pi * t / 0.8
    # --- body yaw: head leads, body follows, a small overshoot settles the turn
    psi_b = ch(t, [(0, 90), (0.6, 90), (1.22, 90), (1.45, 74), (1.72, 28), (1.95, -3), (2.12, 1.5), (2.3, 0), (4, 0)])
    psi_h = ch(t, [(0, 90), (0.6, 90), (1.02, 90), (1.16, 82), (1.38, 40), (1.60, 4), (1.74, -6), (1.95, 2), (2.2, 0), (4, 0)])
    st["psi"], st["psi_h"] = math.radians(psi_b), math.radians(psi_h)
    st["twist_p"] = 0.13 * math.cos(phi + 0.2) * wa
    st["twist_c"] = -0.20 * math.cos(phi + 0.2) * wa
    # --- pelvis: bob (high on passing, low just after contact), weight shifts, settle at the stop, crouch before the wave
    walk_pz = 0.612 + 0.026 * math.cos(2 * math.pi * (t - 0.24) / 0.4)
    stand_pz = 0.628
    pz = lerp(stand_pz, walk_pz, wa)
    pz += ch(t, [(1.18, 0), (1.24, -0.012), (1.38, 0.005), (1.55, 0), (4, 0)])           # settle at the stop
    pz += ch(t, [(1.9, 0), (2.02, -0.034), (2.16, 0.012), (2.36, 0), (4, 0)])             # crouch, then rebound
    pz += -0.012 * math.sin(math.pi * sm((t - 1.40) / 0.28)) - 0.012 * math.sin(math.pi * sm((t - 1.62) / 0.28))
    st["pelvis"] = (pelvis_x(t), pz)
    st["sway"] = ch(t, [(1.3, 0), (1.45, 0.022), (1.68, 0.018), (1.82, -0.02), (1.98, 0), (2.2, -0.012), (4, -0.012)])
    st["roll_p"] = ch(t, [(1.3, 0), (1.45, 0.05), (1.68, 0.04), (1.82, -0.05), (2.0, 0), (2.25, -0.04), (4, -0.04)])
    st["lean"] = (0.075 * wa + ch(t, [(1.2, 0), (1.32, -0.05), (1.5, 0.02), (1.8, 0.0), (2.0, 0.03), (2.1, -0.01), (2.3, -0.05), (4, -0.05)])
                  * (1 - wa) + 0.012 * math.sin(2 * math.pi * 0.7 * t) * (1 - wa))
    st["side"] = ch(t, [(1.4, 0), (1.55, 0.02), (1.85, -0.02), (2.2, 0.03), (4, 0.03)])
    st["roll_c"] = -0.8 * st["roll_p"]
    st["stretch"] = 0.012 * math.cos(2 * math.pi * (t - 0.24) / 0.4) * wa + ch(
        t, [(1.9, 0), (2.02, -0.03), (2.18, 0.03), (2.36, 0), (4, 0)])
    st["curv"] = 1.0
    # --- feet
    st["feet"] = {s: foot_at(s, t) for s in "RL"}
    # --- arms: swing opposite the legs, forearm lags, then the right arm waves (anticipation -> whip up -> overshoot -> wave)
    arms = {}
    for s, sg in (("L", 1), ("R", -1)):
        A = 0.52 * wa
        a1 = sg * 0.0 + (A * math.cos(phi) if s == "L" else -A * math.cos(phi)) + 0.06 * (1 - wa)
        a2 = 0.30 + 0.95 * (A / 0.52) * (math.cos(phi - 0.9) if s == "L" else -math.cos(phi - 0.9)) * 0.5 * 0.52 / 0.52 + a1 * 0.2
        a2 = max(a2, a1 * 0.9 + 0.14) if s == "L" else max(a2, a1 * 0.9 + 0.14)
        arms[s] = dict(a1=a1, b1=0.10 + 0.04 * (1 - wa), a2=a2 + 0.10 * (1 - wa), b2=0.10 + 0.04 * (1 - wa), wave=0.0)
    rr = arms["R"]
    b1 = ch(t, [(0, 0), (1.9, 0), (2.03, -0.18), (2.12, 0.5), (2.22, 1.72), (2.31, 1.98), (2.45, 1.80), (4, 1.80)])
    b2 = ch(t, [(0, 0), (1.9, 0), (2.03, -0.1), (2.14, 0.8), (2.26, 2.55), (2.34, 2.95), (2.46, 2.74), (4, 2.74)])
    ra = ch(t, [(1.9, 0), (2.03, -0.25), (2.2, 0.10), (2.4, 0.06), (4, 0.06)])
    wv = sm((t - 2.34) / 0.12)
    osc = math.sin(2 * math.pi * 2.7 * (t - 2.34))
    mix = sm((t - 2.0) / 0.28)
    rr["b1"] = lerp(rr["b1"], 0.10 + b1, mix) + 0.07 * osc * wv
    rr["b2"] = lerp(rr["b2"], 0.10 + b2, mix) + 0.46 * math.sin(2 * math.pi * 2.7 * (t - 2.34) - 0.7) * wv
    rr["a1"] = lerp(rr["a1"], ra, mix)
    rr["a2"] = lerp(rr["a2"], 0.10, mix)
    rr["wave"] = wv
    rr["wph"] = 2 * math.pi * 2.7 * (t - 2.34)
    arms["L"]["a1"] += ch(t, [(1.9, 0), (2.02, 0.12), (2.3, -0.06), (2.6, 0.03), (4, 0.03)])
    st["arms"] = arms
    st["hand_open"] = {"R": lerp(0.2, 1.0, sm((t - 2.12) / 0.16)), "L": 0.15}
    # --- head: nods with the steps, leads the turn, anticipation back, tilts with the wave
    nod = 0.035 * math.sin(2 * math.pi * (t - 0.1) / 0.4) * wa + ch(t, [(1.1, 0), (1.25, 0.05), (1.5, 0), (1.9, 0), (2.02, 0.07), (2.2, -0.05), (2.5, -0.02), (4, -0.02)])
    st["nod"] = nod
    st["tilt"] = ch(t, [(1.6, 0), (1.9, 0), (2.05, -0.05), (2.3, 0.14), (2.5, 0.19), (2.8, 0.16), (4, 0.16)]) + 0.02 * math.sin(2 * math.pi * 2.7 * (t - 2.4)) * sm((t - 2.4) / 0.2)
    # --- face
    bl = 0.0
    for b0 in (0.62, 2.62):
        bl = max(bl, 1 - abs(t - b0 - 0.06) / 0.07)
    st["blink"] = min(1.0, max(0.0, bl))
    st["gaze"] = (ch(t, [(0, 0.6), (0.9, 0.6), (1.02, 0.2), (1.1, -0.6), (1.7, -0.6), (1.95, 0), (4, 0)]),
                  ch(t, [(0, 0), (1.9, 0), (2.05, -0.3), (2.25, 0.3), (2.5, 0.1), (4, 0.1)]))
    st["smile"] = ch(t, [(0, 0.6), (1.9, 0.6), (2.1, 1.0), (4, 1.0)])
    st["open"] = ch(t, [(0, 0), (2.0, 0), (2.25, 0.8), (2.6, 0.55), (2.9, 0.7), (4, 0.7)])
    st["brow"] = ch(t, [(0, 0), (1.0, 0), (1.12, 0.35), (1.5, 0.2), (2.0, 0.05), (2.22, 0.6), (4, 0.4)])
    st["sec"] = dict(hair=(0, 0), hem=(0, 0), hair_yaw=st["psi_h"], hair_tilt=st["tilt"])
    return st


def static_state(yaw_deg, face=None):
    """A relaxed standing pose for the model sheet (contrapposto, feet planted)."""
    ps = math.radians(yaw_deg)
    st = {"t": 0.0, "psi": ps, "psi_h": ps, "twist_p": 0.0, "twist_c": 0.0, "pelvis": (0.0, 0.628), "sway": 0.0, "roll_p": 0.02,
          "lean": 0.01, "side": 0.0, "roll_c": -0.02, "stretch": 0.0, "curv": 1.0, "nod": 0.0, "tilt": 0.03, "blink": 0.0,
          "gaze": (0.0, 0.0), "smile": 0.8, "open": 0.0, "brow": 0.1}
    l = (math.cos(ps), math.sin(ps))
    f = fdir(ps)
    feet = {}
    for s, sg in (("R", -1), ("L", 1)):
        feet[s] = ((sg * 0.08 * l[0] + (0.02 if s == "L" else -0.01) * f[0], sg * 0.08 * l[1] + (0.02 if s == "L" else -0.01) * f[1], ANK),
                   ps + sg * 0.12, 0.0)
    st["feet"] = feet
    st["arms"] = {s: dict(a1=0.05, b1=0.13, a2=0.30, b2=0.13, wave=0.0) for s in "LR"}
    st["hand_open"] = {"R": 0.25, "L": 0.25}
    st["sec"] = dict(hair=(0, 0), hem=(0, 0), hair_yaw=ps, hair_tilt=0.03)
    st.update(face or {})
    return st


# --------------------------------------------------------------------------- skeleton solve (3-D, orthographic)
def ik3(a, c, l1, l2, pole):
    d = vsub(c, a)
    dist = max(abs(l1 - l2) + 1e-4, min(vlen(d), l1 + l2 - 1e-4))
    dn = vunit(d)
    x = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    h = math.sqrt(max(l1 * l1 - x * x, 0.0))
    perp = vunit(vsub(pole, vmul(dn, vdot(pole, dn))))
    return vadd(a, vadd(vmul(dn, x), vmul(perp, h))), vadd(a, vmul(dn, dist))


def solve(st):
    P = {}
    psi = st["psi"]
    psp, psc = psi + st["twist_p"], psi - st["twist_p"] * 0 + st["twist_c"]
    px, pz = st["pelvis"]
    lat = (math.cos(psp), math.sin(psp), 0.0)
    pel = (px + st["sway"] * lat[0], st["sway"] * lat[1], pz)
    P["pel"], P["psp"], P["psc"] = pel, psp, psc
    k = 1 + st["stretch"]
    rot_p = body_rot(psp, 0.0, st["roll_p"])
    rot_c = body_rot(psc, st["lean"], st["side"])
    P["rot_p"], P["rot_c"] = rot_p, rot_c
    # spine: pelvis -> neck base (quadratic curve through a forward-bowed midpoint)
    top_local = (0.0, 0.0, SPINE * k)
    neck = vadd(pel, mv(rot_c, top_local))
    mid = vadd(vadd(pel, vmul(vsub(neck, pel), 0.5)), mv(rot_c, (0.0, 0.02 * st["curv"], 0.0)))
    P["neck"], P["spine_mid"] = neck, mid
    # legs
    for s, sg in (("R", -1), ("L", 1)):
        hip = vadd(pel, mv(rot_p, (sg * HIP_W, 0.0, 0.0)))
        ank, fyaw, fpitch = st["feet"][s]
        fw = (math.sin(psp), -math.cos(psp), 0.0)
        knee, ank2 = ik3(hip, ank, THIGH, SHIN, vadd(fw, (sg * 0.15 * math.cos(psp), sg * 0.15 * math.sin(psp), 0.0)))
        P["hip" + s], P["knee" + s], P["ank" + s], P["fyaw" + s], P["fpitch" + s] = hip, knee, ank2, fyaw, fpitch
    # arms
    for s, sg in (("R", -1), ("L", 1)):
        shoulder = vadd(vadd(pel, vmul(vsub(neck, pel), 0.9)), mv(rot_c, (sg * SH_W, 0.0, 0.0)))
        a = st["arms"][s]

        def dr(an, bn):
            return mv(rot_c, vunit((sg * math.sin(bn) * math.cos(an), math.sin(an) * math.cos(bn), -math.cos(an) * math.cos(bn))))
        e = vadd(shoulder, vmul(dr(a["a1"], a["b1"]), UARM))
        wr = vadd(e, vmul(dr(a["a2"], a["b2"]), FARM))
        P["sh" + s], P["el" + s], P["wr" + s], P["hd" + s] = shoulder, e, wr, dr(a["a2"], a["b2"])
    # head
    pitch = -(st["lean"] + st["nod"])
    roll = st["side"] + st["tilt"]
    Mh = mm(R_yaw(st["psi_h"]), mm(R_roll(roll), R_pitch(pitch)))
    P["Mh"] = Mh
    P["head"] = vadd(neck, mv(Mh, (0.0, 0.0, 0.84 * RH)))
    P["hroll"], P["hpitch"] = roll, pitch
    return P


# --------------------------------------------------------------------------- drawing the body
def sx(p):
    return (p[0], p[2])


def depth(p):
    return -p[1]


def draw_leg(sb, P, s):
    hip, knee, ank = P["hip" + s], P["knee" + s], P["ank" + s]
    pts = [sx(hip), sx(knee), sx(ank)]
    c = catmull(pts, 9)
    n = len(c)
    hw = [interp(i / (n - 1), [(0, 0.070), (0.3, 0.064), (0.5, 0.054), (0.7, 0.056), (1, 0.040)]) for i in range(n)]
    poly, L, R = ribbon(c, hw)
    sh = strip(R if True else L, c, 0.5)
    sb.shape(poly, D["trs"], shade=sh, shade_col=D["trs_sh"])
    draw_boot(sb, P, s)


def boot_points(yaw, th, ank, z_lo, z_hi, grow=0.0):
    st_f = [(-0.07, 0.04, 0.074), (-0.04, 0.047, 0.078), (0.03, 0.052, 0.076), (0.075, 0.053, 0.012), (0.115, 0.051, -0.028),
            (0.16, 0.041, -0.058), (0.185, 0.024, -0.07)]
    c, s = math.cos(th), math.sin(th)
    fd = (math.sin(yaw), -math.cos(yaw), 0.0)
    ld = (math.cos(yaw), math.sin(yaw), 0.0)
    pts = []
    for f, w, ztop in st_f:
        for lat in (-w - grow, w + grow):
            for z in (z_lo, min(z_hi, ztop) if z_hi is not None else ztop):
                ff, zz = f * c - z * s, f * s + z * c
                wp = vadd(ank, vadd(vmul(fd, ff), vmul(ld, lat)))
                pts.append((wp[0], wp[2] + zz))
    return hull(pts)


def draw_boot(sb, P, s):
    ank, yaw, th = P["ank" + s], P["fyaw" + s], P["fpitch" + s]
    sole = boot_points(yaw, th, ank, -0.115, -0.085, 0.004)
    sb.shape(sole, D["sole"], w=0.9)
    up = boot_points(yaw, th, ank, -0.094, None)
    sh = crescent(up, -110, 20, 0.34)
    sb.shape(up, D["boot"], shade=sh, shade_col=D["boot_sh"])
    # toe-cap shine
    ctr = (sum(p[0] for p in up) / len(up), sum(p[1] for p in up) / len(up))
    tip = max(up, key=lambda p: p[0] * math.sin(yaw) * 0 + p[0] * (1 if math.sin(yaw) > 0 else -1) * abs(math.sin(yaw)) + 0.0 * p[1])
    if abs(math.sin(yaw)) > 0.5:
        d = 1 if math.sin(yaw) > 0 else -1
        sb.line([(tip[0] - d * 0.05, tip[1] + 0.012), (tip[0] - d * 0.03, tip[1] + 0.03), (tip[0] - d * 0.012, tip[1] + 0.034)],
                "#ffd9c9", 0.7)


def coat_section(P, st, h):
    """Centre, half-width and roll of the coat cross-section at height h above the pelvis."""
    pel, neck, mid = P["pel"], P["neck"], P["spine_mid"]
    if h < 0:
        c = (pel[0], pel[2] + h)
        u = 0.0
    else:
        u = min(1.0, h / SPINE)
        a = vadd(vmul(pel, (1 - u) ** 2), vadd(vmul(mid, 2 * u * (1 - u)), vmul(neck, u * u)))
        c = (a[0], a[2])
        if h > SPINE:
            c = (c[0] + (neck[0] - mid[0]) * (h - SPINE) * 0.6, c[1] + (h - SPINE) * 0.95)
    ps = lerp(P["psp"], P["psc"], u)
    aL = interp(h, [(-0.14, 0.205), (0.0, 0.185), (0.16, 0.165), (0.30, 0.157), (0.38, 0.15), (0.41, 0.115), (0.44, 0.07)])
    aF = interp(h, [(-0.14, 0.150), (0.0, 0.135), (0.16, 0.120), (0.30, 0.112), (0.38, 0.104), (0.41, 0.09), (0.44, 0.07)])
    w = math.sqrt((aL * math.cos(ps)) ** 2 + (aF * math.sin(ps)) ** 2) * (1 - 0.5 * st["stretch"])
    roll = lerp(st["roll_p"], st["roll_c"], u)
    return c, w, roll, ps, aF


def draw_torso(sb, P, st):
    hem_dx = st["sec"]["hem"][0]
    hs = [HEM + i * (NECK_TOP - HEM + 0.02) / 13 for i in range(14)]
    secs = [coat_section(P, st, h) for h in hs]
    left, right = [], []
    for h, (c, w, roll, ps, aF) in zip(hs, secs):
        off = hem_dx * ((NECK_TOP - h) / (NECK_TOP - HEM)) ** 2.0
        left.append((c[0] - w + off, c[1] + w * math.sin(roll)))
        right.append((c[0] + w + off, c[1] - w * math.sin(roll)))
    # hem: shallow curve, swings with the lag
    hem = []
    for k in range(1, 6):
        u = k / 6
        hx = lerp(left[0][0], right[0][0], u)
        hz = lerp(left[0][1], right[0][1], u) - 0.016 * math.sin(math.pi * u)
        hem.append((hx, hz))
    top = [(lerp(left[-1][0], right[-1][0], u), lerp(left[-1][1], right[-1][1], u) + 0.02 * math.sin(math.pi * u)) for u in (0.25, 0.5, 0.75)]
    ctrl = left[::-1] + hem + right + top[::-1]
    # draw order: left list is bottom->top; build ccw: left top->bottom, hem, right bottom->top, top
    ctrl = left[::-1][::-1][::-1] if False else (left[::-1] + hem + right + top[::-1])
    poly = catmull(ctrl, 3, True)
    # shadow on the side away from the light (right), wavy inner edge
    inner = [(r[0] - (r[0] - l[0]) * (0.30 + 0.04 * math.sin(i * 0.5)), r[1]) for i, (l, r) in enumerate(zip(left, right))]
    shade = right + [(inner[i][0], inner[i][1]) for i in range(len(inner) - 1, -1, -1)]
    sb.shape(poly, D["coat"], shade=shade, shade_col=D["coat_sh"])
    # details placed on the coat surface in 3-D (visible only when facing us)
    c0, w0, r0, ps0, aF0 = secs[5]

    def surf(h, beta):
        c, w, roll, ps, aF = coat_section(P, st, h)
        aL = interp(h, [(-0.14, 0.205), (0.0, 0.185), (0.16, 0.165), (0.30, 0.157), (0.38, 0.15)])
        lat_, fwd_ = aL * math.sin(beta), aF * math.cos(beta)
        off = hem_dx * ((NECK_TOP - h) / (NECK_TOP - HEM)) ** 2.0
        return (c[0] + lat_ * math.cos(ps) + fwd_ * math.sin(ps) + off, c[1]), fwd_ * math.cos(ps) - lat_ * math.sin(ps)
    # placket line and buttons
    if math.cos(P["psc"]) > 0.25:
        pl = [surf(h, 0.0)[0] for h in (0.40, 0.30, 0.20, 0.10, 0.0, -0.10)]
        sb.line(pl, D["line"], 0.7, 0.1, 0.25)
        for h in (0.30, 0.18, 0.06):
            c, _ = surf(h, 0.0)
            sb.shape(ell(c[0], c[1], 0.014 * max(0.5, math.cos(P["psc"])), 0.014, 10), "#fff3c2", w=0.55)
    # pockets on both flanks (flap = 4 corners on the surface), only when that flank faces us
    for sgn in (-1, 1):
        beta = sgn * 0.95
        corners = [surf(-0.01, beta - 0.30 * sgn * 0), surf(-0.01, beta + 0.34), surf(-0.11, beta + 0.34), surf(-0.11, beta - 0.30)]
        if all(c[1] > 0.0 for c in corners):
            pts = catmull([c[0] for c in corners], 4, True)
            sb.shape(pts, D["coat_sh"], w=0.65)
    # side seam / sleeve line is implied by the arm; add hem trim
    sb.line(hem[::-1] if False else [left[0]] + hem + [right[0]], D["coat_sh"], 1.4, 0.0, 0.0, 0.9)


def draw_collar_and_neck(sb, P, st):
    psi = P["psc"]
    cn = (P["neck"][0], P["neck"][2])
    # skin neck
    hd = (P["head"][0], P["head"][2])
    sb.shape(ribbon([(cn[0], cn[1] - 0.02), (hd[0], hd[1] - 0.18)], [0.052, 0.050])[0], D["skin_sh"], w=0.7)
    ring = []
    for k in range(0, 13):
        beta = -math.pi / 2 + math.pi * k / 12
        for hh, rl, rf in ((NECK_TOP + 0.015, 0.108, 0.086), (NECK_TOP - 0.065, 0.12, 0.095)):
            pass
    top, bot = [], []
    for b in range(-9, 10):
        beta = math.pi * b / 9.0                                   # all around; keep the half that faces us
        for arr, (hh, rl, rf, dz) in ((top, (NECK_TOP + 0.02, 0.105, 0.088, 0.0)), (bot, (NECK_TOP - 0.07, 0.125, 0.105, 0.0))):
            c, w, roll, ps, aF = coat_section(P, st, hh)
            lat_, fwd_ = rl * math.sin(beta), rf * math.cos(beta)
            arr.append(((c[0] + lat_ * math.cos(ps) + fwd_ * math.sin(ps), c[1] + 0.012 * math.cos(beta)), fwd_ * math.cos(ps) - lat_ * math.sin(ps)))
    vis = [i for i in range(len(top)) if top[i][1] >= -0.01]
    if len(vis) > 3:
        a, b = vis[0], vis[-1]
        poly = [top[i][0] for i in range(a, b + 1)] + [bot[i][0] for i in range(b, a - 1, -1)]
        sb.shape(catmull(poly, 2, True), D["coat"], shade=None, w=0.9)
        sb.line([bot[i][0] for i in range(a, b + 1)], D["coat_sh"], 1.6, 0.0, 0.0, 0.9)


def draw_hood(sb, P, st):
    c, w, roll, ps, aF = coat_section(P, st, NECK_TOP - 0.01)
    cx = c[0] + (-0.075) * math.sin(ps)
    rx = math.sqrt((0.15 * math.cos(ps)) ** 2 + (0.085 * math.sin(ps)) ** 2) + 0.01
    pts = ell(cx, c[1] + 0.005, rx, 0.075, 24)
    sb.shape(pts, D["coat"], shade=crescent(pts, -130, 10, 0.4), shade_col=D["coat_sh"], w=0.9)


def draw_arm(sb, P, st, s):
    sh, el, wr = sx(P["sh" + s]), sx(P["el" + s]), sx(P["wr" + s])
    a = st["arms"][s]
    wave = a["wave"]
    pts = [(sh[0], sh[1] + 0.005), el, wr]
    c = catmull(pts, 9)
    n = len(c)
    hw = [interp(i / (n - 1), [(0, 0.058), (0.45, 0.050), (0.55, 0.048), (1, 0.040)]) for i in range(n)]
    poly, L, R = ribbon(c, hw, True, True)
    sb.shape(poly, D["coat"], shade=strip(R, c, 0.5), shade_col=D["coat_sh"])
    # cuff
    cuff_c = [c[int(n * 0.86)], c[-1]]
    cw = hw[-1] + 0.005
    poly2, _, _ = ribbon([cuff_c[0], (cuff_c[1][0], cuff_c[1][1])], [cw, cw], False, False)
    sb.shape(poly2, D["coat_sh"], w=0.8)
    d = vunit((wr[0] - el[0], wr[1] - el[1]))
    ang = math.atan2(d[1], d[0])
    # which way the thumb points on screen
    inward = (-1 if s == "R" else 1)
    thumb3 = vunit(vadd(vmul((math.sin(P["psc"]), -math.cos(P["psc"]), 0.0), 0.7), vmul((math.cos(P["psc"]), math.sin(P["psc"]), 0.0), -inward * 0.8)))
    side = max(-1.0, min(1.0, thumb3[0] * 2.0))
    if abs(side) < 0.35:
        side = 0.35 if side >= 0 else -0.35
    draw_hand(sb, wr, ang, st["hand_open"][s], a.get("wph", 0.0) if wave > 0.01 else 0.0, wave, side)


def draw_hand(sb, wrist, ang, op, wph, wave, thumb_side):
    d = (math.cos(ang), math.sin(ang))
    nrm = (-d[1], d[0])

    hs = 1.32

    def Q(u, v):
        u, v = u * hs, v * hs
        return (wrist[0] + d[0] * u + nrm[0] * v, wrist[1] + d[1] * u + nrm[1] * v)
    # fingers: base positions on the palm edge, fan with openness, flutter with the wave
    lens = [0.044, 0.056, 0.053, 0.040]
    vb = [-0.030, -0.010, 0.010, 0.030]
    if thumb_side < 0:
        vb = vb[::-1]
    fingers = []
    for k in range(4):
        fan = (k - 1.5) * 0.30 * op
        ln = lens[k] * (0.62 + 0.38 * op) * hs
        flut = 0.20 * math.sin(wph * 1.0 + k * 0.9) * wave
        pts = [Q(0.062, vb[k])]
        a = fan * (-1 if thumb_side < 0 else 1) * 1.0
        pos = pts[0]
        for j in range(3):
            a += flut * (j + 1) * 0.45 + (0.18 * (1 - op)) * (-thumb_side if False else 0)
            seg = ln / 3.0
            pos = (pos[0] + (d[0] * math.cos(a) + nrm[0] * math.sin(a)) * seg, pos[1] + (d[1] * math.cos(a) + nrm[1] * math.sin(a)) * seg)
            pts.append(pos)
        fingers.append(pts)
    # one outline for the whole hand: palm side -> thumb -> fingers -> far side
    hwf = lambda n: [(0.0128 - 0.003 * i / max(1, n - 1)) * hs for i in range(n)]
    outline = [Q(0.0, -0.030 * thumb_side if False else -0.032), Q(0.012, -0.040), Q(0.04, -0.042)]
    if thumb_side < 0:
        outline = [Q(0.0, 0.032), Q(0.012, 0.040), Q(0.04, 0.042)]
    # thumb
    ta = thumb_side * (0.55 + 0.75 * op)
    tpos0 = Q(0.030, 0.034 * thumb_side)
    tl = 0.052 * hs
    tpts = [tpos0]
    p = tpos0
    for j in range(3):
        aa = ta - 0.12 * j * thumb_side
        p = (p[0] + (d[0] * math.cos(aa) + nrm[0] * math.sin(aa)) * tl / 3, p[1] + (d[1] * math.cos(aa) + nrm[1] * math.sin(aa)) * tl / 3)
        tpts.append(p)
    # assemble: side A (opposite the thumb) up to the fingers, across the fingers, thumb side down with the thumb detour
    sideA = [Q(0.0, -0.034 * thumb_side), Q(0.016, -0.042 * thumb_side), Q(0.045, -0.043 * thumb_side)]
    outl = list(sideA)
    for k in range(4):
        cpts = catmull(fingers[k], 3)
        hw = hwf(len(cpts))
        poly, L, R = ribbon(cpts, hw)
        # order along the hand's width: vb ascending in thumb_side direction -> fingers go from side A to thumb side
        if k == 0:
            outl += [Q(0.060, vb[k] - 0.0128 * (1 if thumb_side > 0 else -1))]
        Ls, Rs = (L, R) if thumb_side > 0 else (R, L)
        # edges of this finger from side A to the thumb side
        outl += (Ls if True else []) + cap(cpts[-1], math.atan2(cpts[-1][1] - cpts[-2][1], cpts[-1][0] - cpts[-2][0]), hw[-1], 5)[::-1 if False else 1] + Rs[::-1]
    # (the cap above runs from the left edge round to the right edge; for thumb_side<0 the roles are swapped)
    tpc = catmull(tpts, 3)
    thw = [(0.0145 - 0.004 * i / max(1, len(tpc) - 1)) * hs for i in range(len(tpc))]
    tpoly, tL, tR = ribbon(tpc, thw)
    outl += [Q(0.062, vb[3] + 0.0128 * (1 if thumb_side > 0 else -1))]
    outl += [Q(0.05, 0.043 * thumb_side)]
    # fill + outline: palm blob + thumb + fingers as separate fills under one combined outline
    palm = [Q(0.0, -0.033), Q(0.02, -0.043), Q(0.055, -0.042), Q(0.072, -0.030), Q(0.074, 0.0), Q(0.072, 0.030), Q(0.055, 0.042), Q(0.02, 0.043), Q(0.0, 0.033)]
    for k in range(4):
        cpts = catmull(fingers[k], 3)
        hw = hwf(len(cpts))
        poly, L, R = ribbon(cpts, hw)
        sb.shape(poly, D["skin"], w=0.75)
    sb.shape(tpoly, D["skin"], w=0.75)
    sb.shape(catmull(palm, 3, True), D["skin"], shade=None, w=0.8)
    # finger-root creases
    if op > 0.5:
        for k in (1, 2):
            sb.line([Q(0.056, (vb[k - 1] + vb[k]) / 2), Q(0.075, (vb[k - 1] + vb[k]) / 2)], D["line"], 0.45, 0.0, 0.5, 0.5)


# --------------------------------------------------------------------------- the head
class Head:
    def __init__(self, P, st, lag=True):
        self.c = P["head"]
        self.M = P["Mh"]
        self.psi_h = st["psi_h"]
        psf = st["psi_h"] * 0.80                       # features turn a little less, so the profile eye is not on the edge
        self.Mf = mm(R_yaw(psf), mm(R_roll(P["hroll"]), R_pitch(P["hpitch"])))
        sec = st["sec"]
        self.Mhair = mm(R_yaw(sec["hair_yaw"]), mm(R_roll(P["hroll"] + (sec["hair_tilt"] - st["tilt"]) * 0.8), R_pitch(P["hpitch"])))
        self.lag = sec["hair"]

    def p(self, q, M=None, scale=RH):
        w = mv(M or self.M, q)
        return (self.c[0] + w[0] * scale, self.c[2] + w[2] * scale), -w[1]

    def surf(self, alpha_deg, z, push=0.0, face=True, rs=0.93):
        a = math.radians(alpha_deg)
        r = math.sqrt(max(rs * rs - z * z * 0.85, 0.0)) + push
        return self.p((r * math.sin(a), r * math.cos(a), z), self.Mf if face else self.M)


def draw_head(sb, P, st, front_locks=True, back_only=False):
    Hd = Head(P, st)
    M, R = Hd.M, RH
    # ---- back locks (hair that hangs behind), farthest first; drawn before the head when they are behind it
    locks = []
    lat0s = [-0.90, -0.34, 0.34, 0.90]
    tips = [-0.86, -1.02, -0.98, -0.84]
    for lat0, tz in zip(lat0s, tips):
        fw = -0.30 - 0.36 * (1 - abs(lat0))
        path = [(lat0 * 0.86, -0.16, 0.62), (lat0 * 1.10, fw * 0.8, 0.10), (lat0 * 1.10, fw, -0.46),
                (lat0 * 1.02, fw * 0.92, tz)]
        pts, deps = [], []
        for q in path:
            xz, dp = Hd.p(q, Hd.Mhair)
            pts.append(xz)
            deps.append(dp)
        locks.append((sum(deps) / len(deps), pts, abs(lat0)))
    lag = Hd.lag
    drawn_after = []

    def lock_draw(pts, wmax):
        ps2 = []
        for i, p in enumerate(pts):
            u = i / (len(pts) - 1)
            ps2.append((p[0] + lag[0] * u ** 1.7, p[1] + lag[1] * u ** 1.7))
        c = catmull(ps2, 8)
        n = len(c)
        hw = [interp(i / (n - 1), [(0, 0.2), (0.35, 0.38), (0.75, 0.33), (0.93, 0.18), (1, 0.06)]) * R * wmax for i in range(n)]
        poly, L, Rr = ribbon(c, hw, True, True)
        return poly, strip(Rr, c, 0.55), c

    for dep, pts, al in sorted(locks, key=lambda x: x[0]):
        if dep < -0.12:
            poly, sh, c = lock_draw(pts, 1.0)
            sb.shape(poly, D["hair"], shade=sh, shade_col=D["hair_sh"], w=0.8)
        else:
            drawn_after.append((dep, pts))
    if back_only:
        return
    # ---- skull + jaw + cheeks silhouette (hull of 4 circles), projected so it turns as one form
    circ = [((0, -0.03, 0.0), 1.0), ((0, 0.12, -0.42), 0.68), ((-0.50, 0.28, -0.28), 0.48), ((0.50, 0.28, -0.28), 0.48)]
    pts = []
    for q, r in circ:
        (cx, cz), _ = Hd.p(q)
        for i in range(28):
            a = 2 * math.pi * i / 28
            pts.append((cx + r * R * math.cos(a), cz + r * R * math.sin(a)))
    skin = hull(pts)
    skin = catmull(skin[::2], 3, True)
    sh = crescent(skin, -120, 25, 0.22, centre=Hd.p((0, 0, -0.1))[0])
    sb.shape(skin, D["skin"], shade=sh, shade_col=D["skin_sh"], w=1.0)
    # ---- hair cap: visible hairline + the limb of the shell above the hairline, sorted around the crown
    RHs = 1.08

    def zh(a):
        a = abs(((a + 180) % 360) - 180)
        return interp(a, [(0, 0.80), (30, 0.72), (55, 0.46), (78, 0.14), (95, -0.12), (130, -0.30), (180, -0.52)])

    loop = []
    for ad in range(-180, 180, 5):
        a_ = math.radians(ad)
        z = zh(ad)
        r = math.sqrt(max(RHs * RHs - z * z, 0.0))
        xz, dp = Hd.p((r * math.sin(a_), r * math.cos(a_), z))
        loop.append((xz, dp >= -0.02))
    nl = len(loop)
    cap_pts = []
    capq = None
    if any(v for _, v in loop) and not all(v for _, v in loop):
        i0 = next(i for i in range(nl) if loop[i][1] and not loop[i - 1][1])
        run = []
        i = i0
        while loop[i % nl][1]:
            run.append(loop[i % nl][0])
            i += 1
        cc = Hd.p((0, 0, 0))[0]
        ang = lambda p: (math.degrees(math.atan2(p[1] - cc[1], p[0] - cc[0])) + 90) % 360 - 90    # [-90, 270)
        a1, a2 = ang(run[0]), ang(run[-1])
        lo, hi = min(a1, a2), max(a1, a2)
        top_inside = lo <= 90 <= hi
        arc = [(ang(q), q) for q in skin if (lo <= ang(q) <= hi) == top_inside]
        arc.sort(key=lambda x: x[0])
        if not top_inside:                       # wrap: order from hi upward through 270 -> -90 up to lo
            arc.sort(key=lambda x: (x[0] - hi) % 360)
        pts_arc = [(cc[0] + (q[0] - cc[0]) * 1.035, cc[1] + (q[1] - cc[1]) * 1.035) for _, q in arc]
        # orient the arc so it starts next to run[-1]
        d_fwd = math.hypot(pts_arc[0][0] - run[-1][0], pts_arc[0][1] - run[-1][1]) if pts_arc else 0
        d_bwd = math.hypot(pts_arc[-1][0] - run[-1][0], pts_arc[-1][1] - run[-1][1]) if pts_arc else 0
        if d_bwd < d_fwd:
            pts_arc = pts_arc[::-1]
        cap_pts = run + pts_arc
        capq = (run, pts_arc)
        if os.environ.get('MIA_DBG'):
            print('DBG run', len(run), 'a1,a2', round(a1), round(a2), 'arc', len(pts_arc), [tuple(round(v,2) for v in q) for q in run[::4]], 'cc', cc)
    crown = Hd.p((0, -0.1, 0.55))[0]
    if len(cap_pts) > 6:
        cap = catmull(cap_pts, 2, True)
        csh = crescent(cap, -150, 20, 0.3, centre=crown)
        # ears first (under the hair), then cap
        for sgn in (-1, 1):
            nrm = mv(M, (sgn, 0.0, 0.0))
            if -nrm[1] > 0.30:
                pe = [Hd.p((sgn * 0.97, -0.02 + 0.12 * math.cos(a), -0.14 + 0.19 * math.sin(a)))[0] for a in [2 * math.pi * i / 14 for i in range(14)]]
                sb.shape(pe, D["skin"], w=0.7)
        if "cap" not in os.environ.get("MIA_SKIP", ""):
            if capq and len(capq[1]) > 3:
                n_q = 26
                r_r, a_r = resample(capq[0], n_q), resample(capq[1], n_q)[::-1]
                def ext(P_, i, f):                    # extend a point along the sweep so neighbouring quads overlap (no seams)
                    j = min(max(i + (1 if f > 0 else -1), 0), n_q - 1)
                    return (lerp(P_[i][0], P_[j][0], abs(f)), lerp(P_[i][1], P_[j][1], abs(f)))
                for i in range(n_q - 1):          # fill the arch in convex quads (GP fills one concave arch badly)
                    sb.fill([ext(r_r, i, -0.3), ext(r_r, i + 1, 0.3), ext(a_r, i + 1, 0.3), ext(a_r, i, -0.3)], D["hair"])
                    # shadow shape: the lower-right third of the cap, toward the hairline
                    if i > n_q * 0.45:
                        k = 0.5
                        q0, q1, q2, q3 = ext(r_r, i, -0.3), ext(r_r, i + 1, 0.3), ext(a_r, i + 1, 0.3), ext(a_r, i, -0.3)
                        sb.fill([q0, q1, (lerp(q1[0], q2[0], k), lerp(q1[1], q2[1], k)), (lerp(q0[0], q3[0], k), lerp(q0[1], q3[1], k))], D["hair_sh"])
                sb.ink(ccw(cap), D["line"], inked_radii(ccw(cap), R_LINE * 1.0), True)
            else:
                sb.shape(cap, D["hair"], w=1.0)
        # hair shine
        hl = []
        for k in range(8):
            ad = lerp(-62, -8, k / 7)
            z = 0.86 + 0.07 * math.sin(math.pi * k / 7)
            r = math.sqrt(max((RHs + 0.01) ** 2 - z * z, 0.0))
            xz, dp = Hd.p((r * math.sin(math.radians(ad)), r * math.cos(math.radians(ad)), z))
            if dp > 0.05:
                hl.append(xz)
        if len(hl) > 3:
            sb.line(catmull(hl, 3), D["hair_hl"], 1.2, 0.3, 0.3, 0.2)
    # locks that hang in front of the head (near side), then face, then bangs
    for dep, pts in drawn_after:
        poly, sh, c = lock_draw(pts, 0.9)
        sb.shape(poly, D["hair"], shade=sh, shade_col=D["hair_sh"], w=0.95)
    draw_face(sb, Hd, st)
    # ---- bangs: three swept locks that meet at a side parting
    bangs = [[(-14, 0.94), (-32, 0.80), (-54, 0.58), (-74, 0.28), (-88, -0.02)],
             [(-14, 0.94), (8, 0.90), (30, 0.74), (52, 0.55), (70, 0.30), (84, 0.02)]]
    for bpath in ([] if "bangs" in os.environ.get("MIA_SKIP", "") else bangs):
        pts = []
        for ad, z in bpath:
            r = math.sqrt(max((RHs - 0.01) ** 2 - z * z, 0.0))
            xz, dp = Hd.p((r * math.sin(math.radians(ad)), r * math.cos(math.radians(ad)), z))
            if dp < 0.0:
                break
            pts.append(xz)
        if len(pts) >= 3:
            c = catmull(pts, 7)
            n = len(c)
            hw = [interp(i / (n - 1), [(0, 0.10), (0.3, 0.30), (0.75, 0.22), (1, 0.06)]) * R for i in range(n)]
            poly, L, Rr = ribbon(c, hw, True, False)
            sb.shape(poly, D["hair"], shade=strip(Rr, c, 0.5), shade_col=D["hair_sh"], w=0.7)
    # parting line
    pp = []
    for z in (1.02, 0.95, 0.88):
        r = math.sqrt(max((RHs + 0.03) ** 2 - z * z, 0.0))
        xz, dp = Hd.p((r * math.sin(math.radians(-14)), r * math.cos(math.radians(-14)), z))
        if dp > 0.05:
            pp.append(xz)
    if len(pp) == 3:
        sb.line(pp, D["hair_sh"], 0.8, 0.0, 0.4, 0.4)


def draw_face(sb, Hd, st):
    R = RH
    blink, gz, brow = st["blink"], st["gaze"], st["brow"]
    smile, op = st["smile"], st["open"]
    # cheeks
    for sgn in (-1, 1):
        c, dp = Hd.surf(sgn * 35, -0.30)
        if dp > 0.25:
            pts = [Hd.surf(sgn * 35 + 8.5 * math.cos(a), -0.30 + 0.10 * math.sin(a))[0] for a in [2 * math.pi * i / 14 for i in range(14)]]
            sb.fill(pts, D["cheek"], 0.55)
    # eyes
    for sgn in (1, -1):                       # far eye (left, +) first
        a0, z0 = sgn * 22.0, -0.07
        c, dp = Hd.surf(a0, z0)
        if dp < 0.10:
            continue
        op_e = 1 - blink
        outer = sgn                           # outer corner is further from the nose: alpha grows with |alpha|
        sc = [Hd.surf(a0 + 9.6 * math.cos(a), z0 + 0.20 * op_e * math.sin(a) * (1.0 if math.sin(a) < 0 else 0.92))[0]
              for a in [2 * math.pi * i / 22 for i in range(22)]]
        if blink < 0.7:
            sb.shape(sc, "#ffffff", w=0.55)
            gx_ = max(-1, min(1, gz[0])) * 1.8 * (1 if True else sgn)
            gzv = gz[1] * 0.04
            ir = [Hd.surf(a0 + gx_ + 7.4 * math.cos(a), z0 + gzv - 0.012 + min(0.175, 0.19 * op_e) * math.sin(a), 0.004)[0]
                  for a in [2 * math.pi * i / 20 for i in range(20)]]
            sb.fill(ir, D["eye"])
            pu = [Hd.surf(a0 + gx_ + 4.0 * math.cos(a), z0 + gzv - 0.012 + min(0.1, 0.11 * op_e) * math.sin(a), 0.008)[0]
                  for a in [2 * math.pi * i / 16 for i in range(16)]]
            sb.fill(pu, D["pupil"])
            h1 = Hd.surf(a0 + gx_ - 2.6, z0 + gzv + 0.07 * op_e, 0.012)[0]
            sb.fill(ell(h1[0], h1[1], 0.030 * R, 0.034 * R, 10), "#ffffff")
            h2 = Hd.surf(a0 + gx_ + 3.0, z0 + gzv - 0.07 * op_e, 0.012)[0]
            sb.fill(ell(h2[0], h2[1], 0.015 * R, 0.017 * R, 8), "#ffffff")
            # upper lid: heavy line over the top of the eye with a small lash flick at the outer corner
            lid = [Hd.surf(a0 + 9.8 * math.cos(math.radians(th)) * (1 if True else 1),
                           z0 + 0.20 * op_e * math.sin(math.radians(th)) * 0.96 + 0.006, 0.006)[0] for th in range(170, 9, -16)]
            fl = [Hd.surf(a0 + outer * 11.6, z0 + 0.20 * op_e * 0.35 + 0.02, 0.006)[0], Hd.surf(a0 + outer * 13.2, z0 + 0.20 * op_e * 0.35 + 0.075, 0.006)[0]]
            if outer > 0:
                lid = lid[::-1] if lid[0][0] > lid[-1][0] and False else lid
            # make the lid run from the inner corner to the outer corner then flick
            inner_first = sorted(lid, key=lambda p: 0)
            seq = lid if (lid[0][0] - lid[-1][0]) * 0 == 0 else lid
            line_pts = seq + [fl[0], fl[1]] if dp > 0.8 else seq
            sb.ink(catmull(line_pts, 2), D["line"], tapered(len(catmull(line_pts, 2)), R_LINE * 1.9, 0.25, 0.1, 1.0, 0.3))
        else:
            lid = [Hd.surf(a0 + 9.8 * math.cos(math.radians(th)), z0 - 0.04 - 0.05 * math.sin(math.radians(th)), 0.006)[0] for th in range(180, -1, -20)]
            sb.ink(catmull(lid, 3), D["line"], tapered(len(catmull(lid, 3)), R_LINE * 1.8, 0.3, 0.3, 1.0, 0.3))
        # brow (thick-thin, arched; lifts with surprise)
        bz = z0 + 0.33 + 0.10 * brow
        bpp = [Hd.surf(a0 + u * 10.5, bz + (0.045 + 0.02 * brow) * (1 - u * u) + 0.03 * u * outer, 0.01)
               for u in [-1 + 2 * i / 8 for i in range(9)]]
        bp = [q[0] for q in bpp if q[1] > 0.22]
        if len(bp) > 2:
            sb.ink(bp, D["hair_sh"], tapered(len(bp), R_LINE * 1.7, 0.2, 0.45, 1.0, 0.35))
    # nose: small rounded shape that sticks out of the face (visible as a bump in profile)
    npts = []
    for a in range(0, 360, 30):
        r = math.radians(a)
        npts.append(Hd.surf(0.0 + 5.4 * math.cos(r), -0.19 + 0.10 * math.sin(r), 0.20 * (0.5 - 0.5 * math.sin(r)) + 0.03)[0])
    dnose = Hd.surf(0, -0.2, 0.2)[1]
    if dnose > 0.0:
        sb.shape(npts, D["skin"], w=0.6)
    # mouth: smile line or open mouth (blended by 'open')
    c, dm = Hd.surf(0, -0.46)
    if dm > 0.12:
        top, bot = [], []
        for i in range(11):
            u = -1 + 2 * i / 10
            ta = u * (12.5 + 1.5 * smile)
            zt = -0.43 + (0.07 * u * u) * smile * 1.2 + 0.015 * (1 - u * u)
            top.append(Hd.surf(ta, zt, 0.01)[0])
            bot.append(Hd.surf(ta, zt - 0.015 - op * 0.25 * (1 - u * u) ** 0.9 - 0.025 * smile * (1 - u * u), 0.01)[0])
        if op > 0.12:
            mouth = top + bot[::-1]
            sb.shape(catmull(mouth, 2, True), D["mouth"], w=0.7)
            tg = [Hd.surf(u * 6.5, -0.43 - 0.015 - op * 0.25 * (1 - (u * 0.6) ** 2) * 0.6 + 0.02 * (1 - u * u), 0.012)[0] for u in [-1 + 2 * i / 8 for i in range(9)]]
            sb.fill(tg, D["tongue"])
        else:
            sb.ink(top, D["line"], tapered(11, R_LINE * 1.3, 0.3, 0.3, 1.0, 0.3))


# --------------------------------------------------------------------------- one character, one frame
def draw_character(sb, st, black=False):
    P = solve(st)
    # ground shadow (soft, flat, stacked translucent ellipses)
    fx = (P["ankR"][0] + P["ankL"][0]) / 2
    for i in range(7):
        k = 1 - i / 7
        sb.fill(ell(fx, 0.0, 0.34 + 0.20 * k, 0.034 + 0.034 * k, 28), "#40382c", 0.065)
    draw_hood(sb, P, st)
    legs = sorted("RL", key=lambda s: depth(P["hip" + s]))
    for s in legs:
        draw_leg(sb, P, s)
    arms = sorted("RL", key=lambda s: depth(P["sh" + s]))
    for s in arms:
        if depth(P["sh" + s]) < -0.02:
            draw_arm(sb, P, st, s)
    draw_torso(sb, P, st)
    draw_collar_and_neck(sb, P, st)
    for s in arms:
        if depth(P["sh" + s]) >= -0.02:
            draw_arm(sb, P, st, s)
    draw_head(sb, P, st)
    return P


# --------------------------------------------------------------------------- secondary motion (springs run before drawing)
def simulate_secondary(states):
    """Fills st['sec']: hair lag (screen offset), coat hem lag, lagged head yaw/tilt (follow-through and overlap)."""
    heads = [solve(s)["head"] for s in states]
    pels = [solve(s)["pel"] for s in states]
    dt, sub = 1.0 / FPS, 10

    def spring2(series, w, z, gain):
        q = [series[0][0], series[0][1]]
        v = [0.0, 0.0]
        out = []
        for i in range(len(series)):
            for k in range(sub):
                a = (series[min(i + 1, len(series) - 1)] if k >= sub // 2 else series[i])
                for j in range(2):
                    acc = -w * w * (q[j] - a[j]) - 2 * z * w * v[j]
                    v[j] += acc * dt / sub
                    q[j] += v[j] * dt / sub
            out.append(((q[0] - series[i][0]) * gain, (q[1] - series[i][1]) * gain))
        return out

    def spring1(series, w, z):
        q, v, out = series[0], 0.0, []
        for i in range(len(series)):
            for k in range(sub):
                a = series[i]
                acc = -w * w * (q - a) - 2 * z * w * v
                v += acc * dt / sub
                q += v * dt / sub
            out.append(q)
        return out
    hair = spring2([(h[0], h[2]) for h in heads], 15.0, 0.30, 1.6)
    hem = spring2([(p[0], p[2]) for p in pels], 11.0, 0.26, 1.9)
    hyaw = spring1([s["psi_h"] for s in states], 14.0, 0.45)
    htilt = spring1([s["tilt"] for s in states], 12.0, 0.4)
    for i, s in enumerate(states):
        s["sec"] = dict(hair=hair[i], hem=(hem[i][0], 0.0), hair_yaw=hyaw[i], hair_tilt=htilt[i])


# --------------------------------------------------------------------------- scene + render
def build_scene(width, height, ortho_h, cam_z):
    global bpy
    import bpy as _bpy
    bpy = _bpy
    _MATS.clear()
    _FILLED.clear()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.fps = FPS
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"
    try:
        sc.view_settings.look = "None"
    except Exception:
        pass
    try:
        sc.eevee.taa_render_samples = 32
    except Exception:
        pass
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    bgn = world.node_tree.nodes.get("Background")
    bgn.inputs[0].default_value = rgba(D["bg"])
    bgn.inputs[1].default_value = 1.0
    sc.world = world
    cam = bpy.data.cameras.new("cam")
    cam.type = "ORTHO"
    cam.ortho_scale = ortho_h * width / height
    co = bpy.data.objects.new("cam", cam)
    sc.collection.objects.link(co)
    co.location = (0.0, -10.0, cam_z)
    co.rotation_euler = (math.pi / 2, 0, 0)
    sc.camera = co
    gp = bpy.data.grease_pencils.new("mia")
    ob = bpy.data.objects.new("mia", gp)
    sc.collection.objects.link(ob)
    lay = gp.layers.new("art")
    lay.use_lights = False
    drawing = lay.frames.new(1).drawing
    return sc, gp, drawing


def render_png(sc, path):
    sc.render.filepath = path
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)


def sh(cmd):
    subprocess.run(cmd, check=True)


def run_clip():
    sc, gp, dr = build_scene(W, H, 2.6, 0.88)
    states = [state(f / FPS) for f in range(NFRAMES)]
    simulate_secondary(states)
    if ONLY is None and os.path.isdir(TMP):
        shutil.rmtree(TMP)
    os.makedirs(TMP, exist_ok=True)
    frames = ONLY if ONLY is not None else range(NFRAMES)
    t0 = time.time()
    for f in frames:
        sb = SB()
        draw_character(sb, states[f])
        sb.flush(gp, dr)
        render_png(sc, os.path.join(TMP, "f_%03d.png" % (f + 1)))
    dt = time.time() - t0
    print("RENDER %d frames in %.1fs = %.2f s/frame" % (len(list(frames)), dt, dt / max(1, len(list(frames)))))
    if ONLY is None:
        clip = os.path.join(OUT, "clip.mp4")
        sh(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(TMP, "f_%03d.png"), "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-crf", "14", "-preset", "slow", clip])
        picks = [round(i * (NFRAMES - 1) / 7) for i in range(8)]
        sel = "+".join("eq(n,%d)" % p for p in picks)
        sh(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", "select='%s',scale=640:360,tile=4x2:padding=4:color=white" % sel,
            "-frames:v", "1", "-fps_mode", "passthrough", os.path.join(OUT, "sheet.png")])
        print("sheet frames", picks)


def strip_png(frames, name, cols=None, scale=640):
    """Tile some rendered frames into one image (for looking at the motion)."""
    sel = "+".join("eq(n,%d)" % (f - 1) for f in frames)
    cols = cols or len(frames)
    rows = (len(frames) + cols - 1) // cols
    sh(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24", "-i", os.path.join(TMP, "f_%03d.png"), "-vf",
        "select='%s',crop=iw*0.62:ih:iw*0.19:0,scale=%d:-1,tile=%dx%d:padding=3:color=white" % (sel, scale, cols, rows),
        "-frames:v", "1", "-fps_mode", "passthrough", os.path.join(OUT, name)])


def run_sheet():
    sc, gp, dr = build_scene(1920, 1080, 3.0, 1.5)
    sb = SB()
    spots = [(0, -1.75), (45, -0.55), (90, 0.65)]
    for yaw, x in spots:                      # turnaround: front, three-quarter, side (same design in every view)
        sb.xf(1.0, x, 0.55)
        draw_character(sb, static_state(yaw))
    for k, (yaw, x) in enumerate([(0, 1.55), (45, 2.0), (90, 2.45)]):      # solid black silhouettes (readability test)
        b = SB(black=True)
        b.xf(0.45, x, 0.12)
        draw_character(b, static_state(yaw))
        sb.items += b.items
    pl = SB()                                  # shape language: circle head, triangle coat, rounded-rectangle limbs
    pl.xf(0.62, 2.0, 1.05)
    pl.shape(ell(0.0, 0.62, 0.30, 0.30, 40), D["skin"], w=1.0)
    pl.shape(catmull([(-0.33, 0.0), (-0.07, 0.44), (0.07, 0.44), (0.33, 0.0), (0.0, -0.03)], 6, True), D["coat"], w=1.0)
    pl.shape(catmull([(-0.15, -0.05), (-0.15, -0.34), (-0.05, -0.34), (-0.04, -0.05)], 5, True), D["trs"], w=0.9)
    pl.shape(catmull([(0.15, -0.05), (0.15, -0.34), (0.05, -0.34), (0.04, -0.05)], 5, True), D["trs"], w=0.9)
    sb.items += pl.items
    sb.xf()
    sb.flush(gp, dr)
    render_png(sc, os.path.join(OUT, "model_sheet.png"))


def check():
    import itertools
    for s in "RL":
        bad, prev = [], None
        for f in range(0, 52):
            t = f / FPS
            for sg in SEGS[s]:
                if sg[0] == "ST" and sg[1] <= t <= sg[2]:
                    (x, y, z), yaw, th = foot_at(s, t)
                    # contact point = lowest sole point
                    c, sn = math.cos(th), math.sin(th)
                    pts = [(HEEL_F, -ANK), (BALL_F, -ANK)]
                    zs = [(f_ * sn + zz * c, f_) for f_, zz in pts]
                    zmin, fmin = min(zs)
                    lowz = z + zmin
                    cx = x + fdir(yaw)[0] * (fmin * c + (-ANK) * -sn if False else (fmin * c - (-ANK) * sn))
                    if prev and prev[0] == s and prev[3] == id(sg) and abs(cx - prev[1]) > 0.004 and abs(th - prev[2]) < 1e-9:
                        bad.append((f, round(cx - prev[1], 4)))
                    prev = (s, cx, th, id(sg))
                    if abs(lowz) > 0.004:
                        bad.append((f, "z=%.3f" % lowz))
        print("CHECK foot", s, "slides/penetrations (frame, value):", bad[:12], "count", len(bad))
    for t in (0, 0.4, 0.8, 1.2, 1.8, 2.5):
        st = state(t)
        P = solve(st)
        print("CHECK t=%.1f pelvis=(%.2f,%.2f) psi=%.0f head_psi=%.0f ankR=%s ankL=%s" % (
            t, st["pelvis"][0], st["pelvis"][1], math.degrees(st["psi"]), math.degrees(st["psi_h"]),
            tuple(round(v, 2) for v in P["ankR"]), tuple(round(v, 2) for v in P["ankL"])))


def main():
    if "--check" in argv:
        return check()
    os.makedirs(OUT, exist_ok=True)
    if MODE in ("clip", "both"):
        run_clip()
    if MODE in ("sheet", "both"):
        run_sheet()
    if "--strips" in argv:
        strip_png([1, 4, 8, 12, 16, 20, 24, 28], "strip_walk.png", 4)
        strip_png([27, 31, 35, 39, 43, 47], "strip_turn.png", 3)
        strip_png([47, 51, 54, 57, 61, 65], "strip_wave.png", 3)


main()
