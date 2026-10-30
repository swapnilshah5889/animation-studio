"""Bake a shot spec into per-frame world transforms (engine-neutral, D-030).

    bake = bake_shot(film_dir, shot)      # plain dict, JSON-serialisable

Same inputs as `shot.build_shot` (a shot spec plus the film folder) and the same motion code, so
every engine plays exactly the motion the Synfig back end plays. Coordinates are **stage pixels**
at the 1920x1080 design size: x right, y UP, origin bottom-left. Per character and frame the bake
holds every bone's joint position and world direction (degrees, counter-clockwise), the face
state (eyes, mouth) and the character's placement. An engine reads parts, limbs and bones from
`characters[].rig`, and the transforms from `frames`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from studio_core import placement
from studio_core.config import REPO_ROOT  # noqa: F401  (kept for callers that resolve paths)
from studio_core.mocap import metrics
from studio_core.motions import animate, smooth
from studio_core.motions.timeline import compose, sample
from studio_core.rig import (
    _parents_first,
    ground_offset_px,
    joint_vector_px,
    load_rig,
    rotate,
    world_pose,
)
from studio_core.scene import DESIGN
from studio_core.shot import dialogue_mouth
from studio_core.sif import Vec

FPS = 24


def _track_value(track: Any, f: int, default: str) -> str:
    """The string a constant switch track (Animated) holds at frame f."""
    if isinstance(track, str):
        return track
    if track is None:
        return default
    value = default
    for w in track.waypoints:
        if w.frame <= f:
            value = w.value
    return value


def _fk(
    view: dict[str, Any],
    offsets: dict[str, float],
    shifts: dict[str, Vec],
    root: Vec,
    scale: float,
) -> dict[str, tuple[float, float, float]]:
    """{bone: (x, y, world direction)} in stage px: `rig.world_pose` plus joint shifts (in the
    parent part's frame; on the root bone they move the whole character) and the placement."""
    out: dict[str, tuple[Vec, float]] = {}
    for bone in _parents_first(view):
        spec = view["bones"][bone]
        parent = spec["parent"]
        rot = 0.0 if parent is None else out[parent][1] - view["bones"][parent]["direction_deg"]
        direction = spec["direction_deg"] + rot + offsets.get(bone, 0.0)
        shift = shifts.get(bone, Vec(0, 0))
        if parent is None:
            out[bone] = (Vec(root.x + shift.x * scale, root.y + shift.y * scale), direction)
            continue
        jv = joint_vector_px(view, bone)
        v = rotate(Vec(jv.x + shift.x, jv.y + shift.y), rot)
        p = out[parent][0]
        out[bone] = (Vec(p.x + v.x * scale, p.y + v.y * scale), direction)
    return {b: (round(p.x, 3), round(p.y, 3), round(d, 4)) for b, (p, d) in out.items()}


def bake_shot(film_dir: Path, shot: dict[str, Any], *, fps: int = FPS) -> dict[str, Any]:
    n = round(shot["duration_s"] * fps)
    W, H = DESIGN.width, DESIGN.height
    dialogue = shot.get("dialogue", [])
    chars = []
    for ch in shot["characters"]:
        cid = ch["id"]
        rig = load_rig(film_dir / "characters" / cid / "rig.json")
        view = rig.view(ch.get("view"))
        view_name = ch.get("view") or rig.data["default_view"]
        scale = float(ch.get("scale", 1.0))
        ground = ground_offset_px(view)
        track = placement.frame_positions(ch["position"], ch.get("path", []), fps, n)
        travel = None
        if ch.get("path"):
            walking = placement.walking_frames(ch.get("actions", []), fps, n)
            facings = placement.facing_frames(ch.get("facing", "right"), track, walking)
            travel = placement.forward_travel(track, facings, width_px=W, height_px=H, scale=scale)
        anim = animate(
            view,
            ch.get("actions", []),
            fps=fps,
            n_frames=n,
            root_px=Vec(ch["position"][0] * W, ch["position"][1] * H - ground * scale),
            scale=scale,
            seed=f"{shot['id']}:{cid}",
            poses=ch.get("poses"),
            travel=travel,
        )
        offsets = metrics.frame_offsets(view, anim.clips, n)
        smooth_cfg = shot.get("smooth")  # opt-in (D-093); None = off, {} = on with defaults
        if smooth_cfg is not None:
            offsets = smooth.smooth_offsets(
                offsets,
                fps,
                max_dps=smooth_cfg.get("max_dps")
                or smooth.speed_caps(anim.clips)
                or smooth.DEFAULT_MAX_DPS,
                pop_deg=smooth_cfg.get("pop_deg", smooth.DEFAULT_POP_DEG),
                sigma=smooth_cfg.get("sigma", smooth.DEFAULT_SIGMA),
            )
        channels = compose(anim.clips)
        mouth = dialogue_mouth(film_dir, [d for d in dialogue if d["character"] == cid], fps)
        frames = []
        face_track = None
        if smooth_cfg is not None:
            face_track = smooth.face_series(
                [_track_value(anim.eyes, f, "open") for f in range(n)],
                [_track_value(mouth, f, "X") for f in range(n)],
                ch.get("expressions", []),
                [(k["time_s"], k["yaw"]) for k in ch.get("look", [])],
                fps,
            )
        for f in range(n):
            shifts = {
                b: v
                for (kind, b), keys in channels.items()
                if kind == "shift" and isinstance(v := sample(keys, f), Vec)
            }
            fx, fy = track[f][0] * W, track[f][1] * H  # feet, screen px y down
            root = Vec(fx, H - fy + ground * scale)  # root joint, stage px y up
            frames.append(
                {
                    "bones": _fk(view, offsets[f], shifts, root, scale),
                    "eyes": _track_value(anim.eyes, f, "open"),
                    "mouth": _track_value(mouth, f, "X"),
                    **({"face": face_track[f]} if face_track else {}),
                }
            )
        chars.append(
            {
                "id": cid,
                "rig_dir": str(film_dir / "characters" / cid),
                "view": view_name,
                "scale": scale,
                "parts": [{"name": p, **view["parts"][p]} for p in view["draw_order"]],
                "limbs": view.get("bendable_limbs", []),
                "bones": {
                    b: {
                        k: s.get(k)
                        for k in ("parent", "role", "side", "direction_deg", "length_px")
                    }
                    for b, s in view["bones"].items()
                },
                "face": view.get("face"),
                "rest": {
                    b: [round(p.x, 3), round(p.y, 3), d] for b, (p, d) in world_pose(view).items()
                },
                "frames": frames,
            }
        )
    cam = shot.get("camera") or {"move": "static"}
    track = None
    if (
        cam["move"] == "track"
    ):  # eased zoom/pan keys (D-093): [{time_s, zoom, cx, cy}], cx/cy stage px
        keys = cam["keys"]
        cols = {
            name: smooth.eased_track([(k["time_s"], k.get(name, d)) for k in keys], fps, n)
            for name, d in (("zoom", 1.0), ("cx", W / 2), ("cy", H / 2))
        }
        track = [
            [round(cols["zoom"][f], 4), round(cols["cx"][f], 2), round(cols["cy"][f], 2)]
            for f in range(n)
        ]
    elif cam["move"] != "static":
        raise ValueError("bake: only a static or keyed ('track') camera is baked")
    return {
        **({"camera_track": track} if track else {}),
        **({"transparent": True} if shot.get("transparent") else {}),
        "shot": shot["id"],
        "fps": fps,
        "n_frames": n,
        "size": [W, H],
        "zoom": float(cam.get("zoom", 1.0)),
        "background": str(film_dir / "backgrounds" / shot["background"] / "plate.png"),
        "characters": chars,
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Bake a shot spec into per-frame transforms (JSON)")
    ap.add_argument("film_dir", type=Path)
    ap.add_argument("shot_id")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args(argv)
    shot = json.loads((args.film_dir / "shots" / args.shot_id / "shot.json").read_text())
    args.out.write_text(json.dumps(bake_shot(args.film_dir, shot)))
    print(args.out)


if __name__ == "__main__":
    main()
