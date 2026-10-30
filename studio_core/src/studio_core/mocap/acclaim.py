"""Read CMU motion capture (Acclaim ASF skeleton + AMC motion) into joint positions.

Plain-text parsing and forward kinematics; nothing here executes the files.

An ASF bone has a `direction` and `length` (its rest segment, in the global frame), an `axis`
(the orientation of the bone's own coordinate system) and the `dof` it can rotate. An AMC frame
gives the root's position and the angles of each bone's dof. A bone's rotation in the global
frame is
`parent · C · M · C⁻¹` where C is the axis rotation and M the dof rotation in the listed order;
its end point is its start plus that rotation applied to `direction · length`.

Output: `Mocap.joints[name]` is a (frames, 3) array of positions (y up) for every bone's START,
plus `<bone>_end` for its end point, all in the file's length units (only ratios matter here).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

AMC_FPS = 120


@dataclass
class Bone:
    name: str
    direction: np.ndarray
    length: float
    axis: np.ndarray  # degrees, applied in `axis_order`
    axis_order: str
    dof: list[str]
    parent: str | None = None


@dataclass
class Skeleton:
    bones: dict[str, Bone]
    root_order: list[str]
    root_axis_order: str


@dataclass
class Mocap:
    fps: int
    joints: dict[str, np.ndarray]  # name → (frames, 3)

    @property
    def frames(self) -> int:
        return len(next(iter(self.joints.values())))


def _rot(axis: str, deg: float) -> np.ndarray:
    r = np.radians(deg)
    c, s = np.cos(r), np.sin(r)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def euler(angles_deg: list[float], order: list[str]) -> np.ndarray:
    """Rotation matrix for angles about the named axes, applied in the listed order."""
    m = np.eye(3)
    for a, ax in zip(angles_deg, order, strict=True):
        m = m @ _rot(ax, a)
    return m


def parse_asf(text: str) -> Skeleton:
    bones: dict[str, Bone] = {}
    root_order = ["tx", "ty", "tz", "rx", "ry", "rz"]
    root_axis = "xyz"
    lines = [ln.strip() for ln in text.splitlines()]
    section, cur = "", {}
    i = 0
    while i < len(lines):
        ln = lines[i]
        i += 1
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith(":"):
            section = ln.split()[0][1:]
            continue
        parts = ln.split()
        if section == "root":
            if parts[0] == "order":
                root_order = [p.lower() for p in parts[1:]]
            elif parts[0] == "axis":
                root_axis = parts[1].lower()
        elif section == "bonedata":
            if parts[0] == "begin":
                cur = {"dof": []}
            elif parts[0] == "end":
                bones[cur["name"]] = Bone(
                    cur["name"],
                    np.array(cur["direction"], float),
                    float(cur["length"]),
                    np.array(cur["axis"], float),
                    cur["axis_order"],
                    cur["dof"],
                )
            elif parts[0] == "name":
                cur["name"] = parts[1]
            elif parts[0] == "direction":
                cur["direction"] = [float(x) for x in parts[1:4]]
            elif parts[0] == "length":
                cur["length"] = float(parts[1])
            elif parts[0] == "axis":
                cur["axis"] = [float(x) for x in parts[1:4]]
                cur["axis_order"] = parts[4].lower()
            elif parts[0] == "dof":
                cur["dof"] = [p.lower() for p in parts[1:]]
        elif section == "hierarchy" and parts[0] not in ("begin", "end"):
            for child in parts[1:]:
                bones[child].parent = parts[0] if parts[0] != "root" else None
    return Skeleton(bones, root_order, root_axis)


def parse_amc(text: str) -> tuple[list[dict[str, list[float]]], int]:
    """(frames, fps): each frame maps a bone (or 'root') to its values in file order."""
    frames: list[dict[str, list[float]]] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("#", ":")):
            continue
        parts = ln.split()
        if len(parts) == 1 and parts[0].isdigit():
            frames.append({})
        elif frames:
            frames[-1][parts[0]] = [float(x) for x in parts[1:]]
    return frames, AMC_FPS


def joints_from(skel: Skeleton, frames: list[dict[str, list[float]]], fps: int) -> Mocap:
    n = len(frames)
    order = _topological(skel)
    out = {name: np.zeros((n, 3)) for name in order}
    out.update({f"{name}_end": np.zeros((n, 3)) for name in order})
    out["root"] = np.zeros((n, 3))
    for t, frame in enumerate(frames):
        root = frame["root"]
        rv = dict(zip(skel.root_order, root, strict=True))
        pos = np.array([rv.get("tx", 0.0), rv.get("ty", 0.0), rv.get("tz", 0.0)])
        rot_names = [k for k in skel.root_order if k.startswith("r")]
        r_root = euler([rv[k] for k in rot_names], [k[1] for k in rot_names])
        out["root"][t] = pos
        rots: dict[str | None, np.ndarray] = {None: r_root}
        starts: dict[str | None, np.ndarray] = {None: pos}
        ends: dict[str | None, np.ndarray] = {None: pos}
        for name in order:
            b = skel.bones[name]
            vals = frame.get(name, [])
            m = euler(vals, [d[1] for d in b.dof]) if b.dof else np.eye(3)
            c = euler(list(b.axis), list(b.axis_order))
            r = rots[b.parent] @ c @ m @ c.T
            start = ends[b.parent]
            end = start + r @ (b.direction * b.length)
            rots[name], starts[name], ends[name] = r, start, end
            out[name][t], out[f"{name}_end"][t] = start, end
    return Mocap(fps, out)


def _topological(skel: Skeleton) -> list[str]:
    done: list[str] = []
    todo = list(skel.bones)
    while todo:
        for name in list(todo):
            p = skel.bones[name].parent
            if p is None or p in done:
                done.append(name)
                todo.remove(name)
    return done


def load(asf: Path, amc: Path) -> Mocap:
    skel = parse_asf(asf.read_text())
    frames, fps = parse_amc(amc.read_text())
    return joints_from(skel, frames, fps)
