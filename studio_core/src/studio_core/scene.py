"""Scene layout (D-027: nested groups for scene layout): backdrop, parallax background layers,
characters placed by frame position, and a camera that pans and zooms.

Scenes are built once at the **1920x1080 design resolution** (`DESIGN`, 120 px per unit) and
rendered at any size with the CLI's `-w/-h` (studio_core.sif.render.render_frames(size=...)), so a
quick 640x360 preview and the final 1080p render come from the same .sif.

Structure (bottom-first):

    backdrop        solid fill, never moves (no transparent edges, even when zoomed out)
    camera          scale = zoom(t), about the frame centre
      layer groups  offset = -pan(t) * parallax, for each background layer behind the characters
      characters    the ground plane (parallax 1): each character, feet at its frame position
      front layers  layers marked in_front (foreground grass) with parallax > 1
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio_core.rig import BuiltCharacter
from studio_core.schema import validate
from studio_core.sif import (
    Animated,
    Canvas,
    Color,
    Group,
    ImportLayer,
    Interp,
    Layer,
    Rectangle,
    Space,
    Transform,
    Vec,
    Waypoint,
    frames,
)

DESIGN = Space(1920, 1080, 120)
CAMERA_MOVES = ("static", "slow_pan_left", "slow_pan_right", "push_in", "pull_out")
PAN_PX = 240  # how far a slow pan travels over its duration, in design pixels
PUSH = 1.25  # zoom factor of push_in / pull_out


class SceneError(ValueError):
    pass


@dataclass(frozen=True)
class Background:
    data: dict[str, Any]
    folder: Path

    @property
    def id(self) -> str:
        return self.data["id"]


def load_background(path: Path, *, check_files: bool = True) -> Background:
    data = json.loads(path.read_text())
    issues = validate("background", data)
    if issues:
        raise SceneError(f"{path}: " + "; ".join(map(str, issues)))
    bg = Background(data, path.parent)
    if check_files:
        missing = [
            layer["file"] for layer in data["layers"] if not (bg.folder / layer["file"]).is_file()
        ]
        if missing:
            raise SceneError(f"{path}: layer files not found: {missing}")
    return bg


@dataclass
class PlacedCharacter:
    built: BuiltCharacter  # built with space=DESIGN
    position: tuple[float, float]  # where the feet touch the ground, as fractions of the frame
    scale: float = 1.0
    facing: str = "right"  # "left" mirrors the character
    ground_px: float = 0.0  # feet below the root at rest, art px (studio_core.rig.ground_offset_px)


@dataclass(frozen=True)
class CameraTracks:
    pan: Animated | None  # design px along x (+ = camera moves right, content slides left)
    zoom: Animated | float


def camera_tracks(camera: dict[str, Any] | None, fps: int, n_frames: int) -> CameraTracks:
    """Keyframes for a named camera move (shot spec `camera`). Moves ease in and out."""
    camera = camera or {"move": "static"}
    move = camera["move"]
    if move not in CAMERA_MOVES:
        raise SceneError(f"unknown camera move {move!r}; known: {list(CAMERA_MOVES)}")
    z0 = float(camera.get("zoom", 1.0))
    start = frames(camera.get("start_s", 0), fps)
    end = n_frames - 1 if "duration_s" not in camera else start + frames(camera["duration_s"], fps)
    end = min(end, n_frames - 1)
    if move == "static" or end <= start:
        return CameraTracks(None, z0)

    def track(kind: str, a: Any, b: Any) -> Animated:
        keys = [Waypoint(start, a, Interp.EASE), Waypoint(end, b, Interp.EASE)]
        if start > 0:
            keys.insert(0, Waypoint(0, a, Interp.CONSTANT))
        return Animated(kind, tuple(keys))

    if move in ("slow_pan_left", "slow_pan_right"):
        direction = -1 if move == "slow_pan_left" else 1
        return CameraTracks(track("real", 0.0, float(direction * PAN_PX)), z0)
    a, b = (z0, z0 * PUSH) if move == "push_in" else (z0 * PUSH, z0)
    return CameraTracks(None, track("real", a, b))


def _plane(name: str, factor: float, pan: Animated | None, children: list[Layer]) -> Group:
    """A depth plane: content that slides by -pan * factor when the camera pans."""
    if pan is None or factor == 0:
        offset: Vec | Animated = Vec(0, 0)
    else:
        offset = Animated(
            "vector",
            tuple(
                Waypoint(w.frame, Vec(DESIGN.length(-w.value * factor), 0), w.interp)
                for w in pan.waypoints
            ),
        )
    return Group(name, transform=Transform(offset=offset), children=children)


def build_scene(
    *,
    fps: int,
    n_frames: int,
    background: Background,
    background_prefix: str,
    characters: list[PlacedCharacter],
    camera: dict[str, Any] | None = None,
    name: str = "shot",
) -> Canvas:
    """The whole shot as a Canvas. `background_prefix` is the background folder relative to the
    .sif (e.g. '../../backgrounds/meadow')."""
    tracks = camera_tracks(camera, fps, n_frames)
    w_px, h_px = background.data["size_px"]
    tl = Vec(DESIGN.length(-w_px / 2), DESIGN.length(h_px / 2))
    br = Vec(DESIGN.length(w_px / 2), DESIGN.length(-h_px / 2))

    def layer_plane(layer: dict[str, Any]) -> Group:
        image = ImportLayer(
            layer["name"], file=f"{background_prefix}/{layer['file']}", tl=tl, br=br
        )
        return _plane(f"bg {layer['name']}", layer["parallax"], tracks.pan, [image])

    placed: list[Layer] = []
    for ch in characters:
        if ch.facing not in ("left", "right"):
            raise SceneError(f"facing must be 'left' or 'right', not {ch.facing!r}")
        x, y = DESIGN.to_units(ch.position[0] * DESIGN.width, ch.position[1] * DESIGN.height)
        y += DESIGN.length(ch.ground_px * ch.scale)  # the root sits above the feet
        sx = -ch.scale if ch.facing == "left" else ch.scale
        placed.append(
            Group(
                f"place {ch.built.group.desc}",
                transform=Transform(offset=Vec(x, y), scale=Vec(sx, ch.scale)),
                children=[ch.built.group],
            )
        )

    back = [layer_plane(layer) for layer in background.data["layers"] if not layer.get("in_front")]
    front = [layer_plane(layer) for layer in background.data["layers"] if layer.get("in_front")]
    zoom = tracks.zoom
    scale: Vec | Animated = (
        Vec(zoom, zoom)
        if not isinstance(zoom, Animated)
        else Animated(
            "vector",
            tuple(Waypoint(w.frame, Vec(w.value, w.value), w.interp) for w in zoom.waypoints),
        )
    )
    world = Group(
        "camera",
        transform=Transform(scale=scale),
        children=[*back, _plane("characters", 1.0, tracks.pan, placed), *front],
    )
    half_w, half_h = DESIGN.half_width_units * 4, DESIGN.half_height_units * 4
    backdrop = Rectangle(
        "backdrop",
        color=Color.hex(background.data.get("backdrop", "#9fd2f2")),
        point1=Vec(-half_w, half_h),
        point2=Vec(half_w, -half_h),
    )
    return Canvas(
        width=DESIGN.width,
        height=DESIGN.height,
        fps=fps,
        frames=n_frames,
        ppu=DESIGN.ppu,
        bgcolor=Color(1, 1, 1),
        name=name,
        layers=[backdrop, world],
        bones=[b for ch in characters for b in ch.built.bones],
    )
