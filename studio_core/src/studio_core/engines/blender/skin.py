"""Spike (D-093): one continuous skinned mesh per character, built from the cut parts.

The rest-pose parts are composited (draw order) into one image; a grid clipped to the alpha
silhouette is the mesh; each vertex is owned by the front-most part at that point, and near a joint
it is blended with the neighbouring bone (smoothstep along the child bone, limited to a band around
that bone's axis, so a torso strip beside an arm is not dragged along). `build_skin` writes
`skin.png` and `skin.json` (vertices in rest space, y up, uv, triangles, weights) for
`build_render.py`. Engine-neutral data: nothing here names Blender.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


def _smoothstep(a: float, b: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def build_skin(
    ch: dict, out_dir: Path, step: int = 8, blend: float = 0.6, band: float = 1.0
) -> dict:
    """Mesh + composite image for one baked character entry (`ch`). Returns the `skin` dict that
    goes into the bake (`ch["skin"]`)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rest, bones, scale = ch["rest"], ch["bones"], ch["scale"]
    rig_dir = Path(ch["rig_dir"])
    placed = []  # (part, left, top) in rest space, y up
    for p in ch["parts"]:
        jx, jy, _ = rest[p["bone"]]
        placed.append((p, (jx - p["pivot_px"][0]) * scale, (jy + p["pivot_px"][1]) * scale))
    left = math.floor(min(left for _, left, _ in placed))
    top = math.ceil(max(top for _, _, top in placed))
    right = math.ceil(max(left_ + p["size_px"][0] * scale for p, left_, _ in placed))
    bottom = math.floor(min(top_ - p["size_px"][1] * scale for p, _, top_ in placed))
    w, h = right - left, top - bottom

    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    owner = np.full((h, w), -1, dtype=np.int16)
    names = [p["bone"] for p, _, _ in placed]
    for i, (p, lx, ty) in enumerate(placed):  # draw order = list order
        im = Image.open(rig_dir / p["file"]).convert("RGBA")
        if scale != 1.0:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        ox, oy = round(lx - left), round(top - ty)
        canvas.alpha_composite(im, (ox, oy))
        a = np.asarray(im.getchannel("A")) > 128
        view = owner[oy : oy + a.shape[0], ox : ox + a.shape[1]]
        view[a[: view.shape[0], : view.shape[1]]] = i
    canvas.save(out_dir / "skin.png")

    # fill ownership into transparent margins so margin vertices get a sensible owner
    filled = owner.copy()
    for _ in range(3 * step):
        miss = filled < 0
        if not miss.any():
            break
        grown = filled.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(filled, (dy, dx), (0, 1))
            take = miss & (grown < 0) & (sh >= 0)
            grown[take] = sh[take]
        filled = grown

    alpha = np.asarray(canvas.getchannel("A"))
    nx, ny = math.ceil(w / step), math.ceil(h / step)
    pad = np.zeros((ny * step, nx * step), dtype=np.uint8)
    pad[:h, :w] = alpha
    cell = pad.reshape(ny, step, nx, step).max(axis=(1, 3)) > 8
    grown = cell.copy()  # one cell margin so the soft edge is covered
    grown[1:] |= cell[:-1]
    grown[:-1] |= cell[1:]
    grown[:, 1:] |= cell[:, :-1]
    grown[:, :-1] |= cell[:, 1:]

    vid, verts, uvs = {}, [], []

    def vertex(i: int, j: int) -> int:
        if (i, j) not in vid:
            px, py = min(i * step, w), min(j * step, h)
            vid[(i, j)] = len(verts)
            verts.append((left + px, top - py))
            uvs.append((px / w, 1 - py / h))
        return vid[(i, j)]

    tris = []
    for j in range(ny):
        for i in range(nx):
            if not grown[j, i]:
                continue
            a, b, c, d = vertex(i, j), vertex(i + 1, j), vertex(i + 1, j + 1), vertex(i, j + 1)
            tris += [(a, b, c), (a, c, d)] if (i + j) % 2 == 0 else [(a, b, d), (b, c, d)]

    # joint blend: for every bone with a parent, a band around its axis near its head
    joints = []
    for b, info in bones.items():
        if not info["parent"]:
            continue
        pi = next((k for k, p in enumerate(names) if p == info["parent"]), None)
        ci = next((k for k, p in enumerate(names) if p == b), None)
        if pi is None or ci is None:
            continue
        cpart = placed[ci][0]
        area = float((np.asarray(Image.open(rig_dir / cpart["file"]).getchannel("A")) > 128).sum())
        width = area / max(info["length_px"] or 1, 1) * 1.0
        x, y, d = rest[b]
        joints.append((b, info["parent"], np.array([x * scale, y * scale]), math.radians(d), width))

    weights: dict[str, list] = {}
    for vi, (vx, vy) in enumerate(verts):
        px = int(np.clip(round(vx - left), 0, w - 1))
        py = int(np.clip(round(top - vy), 0, h - 1))
        o = int(filled[py, px])
        own = names[o] if o >= 0 else ch["parts"][0]["bone"]
        best = None  # (strength, joint, t)
        for b, parent, jp, ang, width in joints:
            if own not in (b, parent):
                continue
            r = blend * width
            dx, dy = vx - jp[0], vy - jp[1]
            axis = (math.cos(ang), math.sin(ang))
            d_along = dx * axis[0] + dy * axis[1]
            d_perp = abs(-dx * axis[1] + dy * axis[0])
            inband = 1.0 - float(
                _smoothstep(0.45 * band * width, 0.9 * band * width, np.array(d_perp))
            )
            reach = 1.0 - float(_smoothstep(1.2 * r, 2.4 * r, np.array(abs(d_along))))
            t = float(_smoothstep(-r, r, np.array(d_along)))
            infl = inband * reach
            if best is None or infl > best[0]:
                best = (infl, b, parent, t)
        if best is None or best[0] <= 0.01:
            weights.setdefault(own, []).append([vi, 1.0])
            continue
        infl, b, parent, t = best
        # inside the influence zone: blend ownership-based weight with the smoothstep split
        w_child = (1 - infl) * (1.0 if own == b else 0.0) + infl * t
        for bone, wt in ((b, w_child), (parent, 1 - w_child)):
            if wt > 0.001:
                weights.setdefault(bone, []).append([vi, round(wt, 4)])

    mesh = {"verts": verts, "uvs": uvs, "tris": tris, "weights": weights, "size": [w, h]}
    (out_dir / "skin.json").write_text(json.dumps(mesh))
    return {
        "mesh": str(out_dir / "skin.json"),
        "png": str(out_dir / "skin.png"),
        "n_verts": len(verts),
        "n_tris": len(tris),
    }


def distortion(ch: dict, skin: dict, thresh: float = 1.6) -> list[dict]:
    """Per frame, how much of the mesh the pose stretches, squashes or folds over (linear blend
    skinning in numpy, the same maths the engine uses). The hole/seam count cannot see texture
    smear or a fold: this can. `bad` is the share of rest area whose triangles have a singular
    value above `thresh` or below 1/thresh, or a negative determinant (folded)."""
    sk = json.loads(Path(skin["mesh"]).read_text())
    v = np.array(sk["verts"], dtype=float)
    tris = np.array(sk["tris"])
    bones = list(ch["rest"])
    w = np.zeros((len(v), len(bones)))
    for b, ws in sk["weights"].items():
        for vi, wt in ws:
            w[vi, bones.index(b)] = wt
    w /= np.maximum(w.sum(1, keepdims=True), 1e-9)
    head = np.array([ch["rest"][b][:2] for b in bones]) * ch["scale"]
    rest_d = np.array([ch["rest"][b][2] for b in bones])
    e0 = v[tris[:, 1]] - v[tris[:, 0]]
    e1 = v[tris[:, 2]] - v[tris[:, 0]]
    rest_m = np.stack([e0, e1], axis=-1)  # (n,2,2) columns = edges
    inv = np.linalg.pinv(rest_m)
    area = 0.5 * np.abs(np.linalg.det(rest_m))
    out = []
    for fr in ch["frames"]:
        pos = np.array([fr["bones"][b][:2] for b in bones]) * ch["scale"]
        ang = np.radians(np.array([fr["bones"][b][2] for b in bones]) - rest_d)
        c, s = np.cos(ang), np.sin(ang)
        rel = v[:, None, :] - head[None]  # (nv,nb,2)
        rot = np.stack([c * rel[..., 0] - s * rel[..., 1], s * rel[..., 0] + c * rel[..., 1]], -1)
        p = (w[..., None] * (rot + pos[None])).sum(1)
        pm = np.stack([p[tris[:, 1]] - p[tris[:, 0]], p[tris[:, 2]] - p[tris[:, 0]]], axis=-1)
        f = pm @ inv  # deformation gradient
        sv = np.linalg.svd(f, compute_uv=False)
        det = np.linalg.det(f)
        bad = (sv[:, 0] > thresh) | (sv[:, 1] < 1 / thresh) | (det < 0)
        out.append(
            {
                "bad": float((area * bad).sum() / area.sum()),
                "folded": float((area * (det < 0)).sum() / area.sum()),
            }
        )
    return out
