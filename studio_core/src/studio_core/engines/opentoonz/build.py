# ruff: noqa: B023, E741
"""Bake JSON -> OpenToonz project (levels, meshes, `.tnz`). See tnz.py for the file format."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

from studio_core.engines.opentoonz.mesh import limb_mesh
from studio_core.engines.opentoonz.tnz import (
    DPI,
    Column,
    Peg,
    build_tnz,
    plastic_sd,
    write_project,
)

INCH = 1.0 / DPI  # stage px -> inches


def _peg_track(
    frames: list[dict],
    bone: str,
    rest_dir: float,
    size: tuple[float, float],
    pivot: tuple[float, float],
    stage: tuple[int, int],
    scale: float = 1.0,
) -> Peg:
    """Position and rotation keys that put the drawing's pivot on the bone's joint."""
    w, h = size
    cx, cy = (pivot[0] - w / 2) * INCH, -(pivot[1] - h / 2) * INCH
    xs, ys, rot = [], [], []
    for fr in frames:
        x, y, d = fr["bones"][bone]
        xs.append((x - stage[0] / 2) * INCH - cx)
        ys.append((y - stage[1] / 2) * INCH - cy)
        rot.append(d - rest_dir)
    return Peg("", center=(cx, cy), channels={"x": xs, "y": ys, "rot": rot, "sc": scale})


def build_project(bake: dict[str, Any], root: Path, *, rigid: bool = False) -> tuple[Path, dict]:
    if root.exists():
        shutil.rmtree(root)
    scenes = write_project(root)
    inputs = root / "inputs"
    n = bake["n_frames"]
    stage = tuple(bake["size"])
    levels: dict[str, str] = {}
    columns: list[Column] = []
    info = {"triangles": 0, "meshes": 0}

    def add_level(name: str, files: list[Path]) -> None:
        for i, f in enumerate(files, start=1):
            shutil.copyfile(f, inputs / f"{name}.{i:04d}.png")
        levels[name] = f"+inputs/{name}..png"

    if not bake.get("transparent"):  # a transparent shot is composited by the caller
        add_level("bg", [Path(bake["background"])])
        columns.append(Column("bg", [(0, n, 1)], Peg("")))

    for ch in bake["characters"]:
        cid, rig_dir, rest = ch["id"], Path(ch["rig_dir"]), ch["rest"]
        frames = ch["frames"]
        limbs = [] if rigid else ch["limbs"]
        owned = {
            p["name"]: l["name"] for l in limbs for p in ch["parts"] if p["bone"] in l["bones"]
        }
        placed: set[str] = set()
        for part in ch["parts"]:
            name = part["name"]
            if name in owned:
                limb = next(l for l in limbs if l["name"] == owned[name])
                if limb["name"] in placed:
                    continue
                placed.add(limb["name"])
                up, lo = limb["bones"]
                lvl = f"{cid}_{limb['name']}"
                add_level(lvl, [rig_dir / limb["file"]])
                text, tris = limb_mesh(rig_dir / limb["file"])
                (inputs / f"{lvl}_mesh.0001.mesh").write_text(text)
                levels[f"{lvl}_mesh"] = f"+inputs/{lvl}_mesh..mesh"
                info["triangles"] += tris
                info["meshes"] += 1
                w, h = limb["size_px"]
                px, py = limb["pivot_px"]
                jx, jy = limb["joint_px"]
                peg = _peg_track(frames, up, rest[up][2], (w, h), (px, py), stage, ch["scale"])
                length = ch["bones"][lo]["length_px"]
                ld = math.radians(rest[lo][2])
                to_xy = lambda ix, iy: (ix - w / 2 + 0.37, h / 2 - iy + 0.29)  # noqa: E731
                joints = [
                    to_xy(px, py),
                    to_xy(jx, jy),
                    (
                        to_xy(jx, jy)[0] + length * math.cos(ld),
                        to_xy(jx, jy)[1] + length * math.sin(ld),
                    ),
                ]
                bend = [
                    ((fr["bones"][lo][2] - rest[lo][2]) - (fr["bones"][up][2] - rest[up][2]))
                    for fr in frames
                ]
                peg.plastic = plastic_sd(joints, bend)
                tex_idx = len(columns) + 1
                columns.append(Column(lvl, [(0, n, 1)], Peg("", parent=f"Col{tex_idx + 1}")))
                columns.append(Column(f"{lvl}_mesh", [(0, n, 1)], peg, mesh=True))
                continue
            lvl = f"{cid}_{name}"
            bone = part["bone"]
            peg = _peg_track(
                frames,
                bone,
                rest[bone][2],
                tuple(part["size_px"]),
                tuple(part["pivot_px"]),
                stage,
                ch["scale"],
            )
            if ch.get("face") and name == ch["face"]["part"]:
                variants = sorted({fr["head"] for fr in frames})
                add_level(lvl, [Path(v) for v in variants])
                cells = [(f, 1, variants.index(fr["head"]) + 1) for f, fr in enumerate(frames)]
                columns.append(Column(lvl, cells, peg))
            elif any(name in fr.get("part_images", {}) for fr in frames):
                # drawn variants of one part (a bent leg, an expression head): same canvas and
                # pivot, so the xsheet only swaps the drawing per frame
                files = [rig_dir / part["file"]] + sorted(
                    {
                        Path(fr["part_images"][name])
                        for fr in frames
                        if name in fr.get("part_images", {})
                    }
                )
                add_level(lvl, files)
                cells = [
                    (
                        f,
                        1,
                        1
                        if name not in fr.get("part_images", {})
                        else files.index(Path(fr["part_images"][name])) + 1,
                    )
                    for f, fr in enumerate(frames)
                ]
                columns.append(Column(lvl, cells, peg))
            else:
                add_level(lvl, [rig_dir / part["file"]])
                columns.append(Column(lvl, [(0, n, 1)], peg))
    channels: dict[str, Any] = {"sc": 1.0 / bake["zoom"]}
    if bake.get("camera_track"):  # a keyed push-in / pan (zoom, cx, cy in stage px, y down)
        w_, h_ = stage
        track = bake["camera_track"]
        channels = {
            "sc": [1.0 / z for z, _, _ in track],
            "x": [(cx - w_ / 2) * INCH for _, cx, _ in track],
            "y": [-(cy - h_ / 2) * INCH for _, _, cy in track],
        }
    camera = Peg("Camera1", "None", channels=channels, camera=_camera())
    scene = scenes / f"{bake['shot']}.tnz"
    scene.write_text(
        build_tnz(levels, columns, camera, n, "+outputs/f.png", bool(bake.get("transparent")))
    )
    info["columns"] = len(columns)
    return scene, info


def _camera() -> str:
    from studio_core.engines.opentoonz.tnz import CAMERA_XML

    return CAMERA_XML


if __name__ == "__main__":
    import sys

    b = json.loads(Path(sys.argv[1]).read_text())
    print(build_project(b, Path(sys.argv[2])))
