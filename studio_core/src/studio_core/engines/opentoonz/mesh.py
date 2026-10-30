"""A Plastic mesh for a drawing: a triangulated grid clipped to the opaque pixels.

OpenToonz's Plastic deformer is "as rigid as possible", so a mesh that also covers transparent
space tilts the drawing almost rigidly instead of bending it; a mesh that follows the outline
bends. The GUI's Meshify command makes outline meshes; this is the same idea with a clipped grid.
Coordinates in the file: pixels at the mesh dpi, origin at the image centre, y up.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

DPI = 120


def limb_mesh(png: Path, step: int = 10, margin_cells: int = 1) -> tuple[str, int]:
    """(.mesh file text, triangle count)."""
    alpha = np.asarray(Image.open(png).convert("RGBA"))[..., 3] > 16
    h, w = alpha.shape
    xs = sorted({*range(0, w, step), w})
    ys = sorted({*range(0, h, step), h})
    nx, ny = len(xs) - 1, len(ys) - 1
    hit = np.zeros((ny, nx), bool)
    for j in range(ny):
        for i in range(nx):
            hit[j, i] = alpha[ys[j] : ys[j + 1], xs[i] : xs[i + 1]].any()
    grown = hit.copy()
    for _ in range(margin_cells):
        pad = np.pad(grown, 1)
        grown = np.zeros_like(grown)
        for dj in (-1, 0, 1):
            for di in (-1, 0, 1):
                grown |= pad[1 + dj : 1 + dj + ny, 1 + di : 1 + di + nx]
    index: dict[tuple[int, int], int] = {}
    verts: list[tuple[float, float]] = []

    def vid(i: int, j: int) -> int:
        if (i, j) not in index:
            index[(i, j)] = len(verts)
            verts.append((xs[i] - w / 2, h / 2 - ys[j]))
        return index[(i, j)]

    edges: dict[tuple[int, int], int] = {}

    def edge(a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in edges:
            edges[key] = len(edges)
        return edges[key]

    faces = []
    for j in range(ny):
        for i in range(nx):
            if not grown[j, i]:
                continue
            p00, p10 = vid(i, j), vid(i + 1, j)  # top-left, top-right (image y down)
            p01, p11 = vid(i, j + 1), vid(i + 1, j + 1)
            for a, b, c in ((p01, p11, p10), (p01, p10, p00)):  # counter-clockwise with y up
                faces.append((edge(a, b), edge(b, c), edge(c, a)))
    v = " ".join(f"{x:g} {y:g}" for x, y in verts)
    e = " ".join(f"{a} {b}" for a, b in edges)
    f = " ".join(f"{a} {b} {c}" for a, b, c in faces)
    text = (
        f"<header><version>1 19</version><dpi>{DPI} {DPI}</dpi></header>\n"
        f"<mesh><V>{len(verts)} {v}</V><E>{len(edges)} {e}</E><F>{len(faces)} {f}</F></mesh>\n"
    )
    return text, len(faces)
