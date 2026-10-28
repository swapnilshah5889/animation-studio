"""Shot assembly: a shot spec (shots/<id>/shot.json, D-028) → scene.sif → shot.mp4.

The director writes the spec; everything from there is deterministic code (AGENTS.md "rules in
code"): motions become bone tracks, expressions and Rhubarb cues become face switch tracks,
characters are placed by their feet, and the camera and parallax come from the background.

Paths follow the film project layout (docs/ARCHITECTURE.md):

    characters/<id>/rig.json            backgrounds/<id>/layers.json
    audio/dialogue/<line_id>.wav        audio/lipsync/<line_id>.json
    shots/<id>/shot.json → scene.sif, frames/, mix.wav, shot.mp4

The soundtrack (dialogue, sound effects, music ducked under the dialogue, at the web loudness
target) comes from studio_core.audio.mix.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio_core import placement
from studio_core.audio.mix import mix_shot
from studio_core.config import StudioConfig, load_config
from studio_core.face import face_attachments
from studio_core.hands import hand_attachments, hand_bone, hand_track, merge_attachments
from studio_core.motions import animate
from studio_core.rig import build_character, ground_offset_px, load_rig
from studio_core.scene import DESIGN, PlacedCharacter, build_scene, load_background
from studio_core.schema import validate
from studio_core.sif import Animated, Canvas, Interp, Vec, Waypoint, frames
from studio_core.sif.lipsync import load_cues, mouth_track
from studio_core.sif.render import RenderError, encode_mp4, render_frames

DEFAULT_FPS = 24


class ShotError(ValueError):
    pass


@dataclass
class BuiltShot:
    canvas: Canvas
    fps: int
    n_frames: int
    dialogue: list[tuple[Path, float]] = field(default_factory=list)  # (wav, start_s)


@dataclass(frozen=True)
class RenderedShot:
    sif: Path
    frames: list[Path]
    mp4: Path


def shot_dir(film_dir: Path, shot_id: str) -> Path:
    return film_dir / "shots" / shot_id


def load_shot(film_dir: Path, shot_id: str) -> dict[str, Any]:
    path = shot_dir(film_dir, shot_id) / "shot.json"
    if not path.is_file():
        raise ShotError(f"no shot spec at {path}")
    return json.loads(path.read_text())


def expression_track(expressions: list[dict[str, Any]], fps: int) -> str | Animated:
    """Expression changes as a switch track ('neutral' until the first change)."""
    by_frame = {0: "neutral"}
    for e in sorted(expressions, key=lambda e: e["start_s"]):
        by_frame[frames(e["start_s"], fps)] = e["expr"]
    if len(set(by_frame.values())) == 1:
        return by_frame[0]
    return Animated(
        "string", tuple(Waypoint(f, v, Interp.CONSTANT) for f, v in sorted(by_frame.items()))
    )


def hand_tracks(tracks: dict[str, Animated]) -> dict[str, Animated | str]:
    """Hand-pose tracks from the motions, each starting at `rest` from frame 0."""
    return {
        bone: hand_track([(w.frame, w.value) for w in t.waypoints]) for bone, t in tracks.items()
    }


def dialogue_mouth(film_dir: Path, lines: list[dict[str, Any]], fps: int) -> str | Animated:
    """One character's mouth track from the Rhubarb cues of all their lines in the shot. Each
    line's cues are shifted to its start time."""
    cues: list[dict[str, object]] = []
    for line in sorted(lines, key=lambda line: line["start_s"]):
        path = film_dir / "audio" / "lipsync" / f"{line['line_id']}.json"
        if not path.is_file():
            raise ShotError(f"line {line['line_id']} has no mouth cues at {path}")
        for cue in load_cues(path):
            cues.append({"start": float(cue["start"]) + line["start_s"], "value": cue["value"]})
    return mouth_track(cues, fps) if cues else "X"


def build_shot(
    film_dir: Path, shot: dict[str, Any], *, fps: int = DEFAULT_FPS, bend: bool = True
) -> BuiltShot:
    """Validate a shot spec and build its scene (to be saved at shots/<id>/scene.sif). `bend`
    False draws every limb as two rigid parts, the fallback for bendable limbs."""
    issues = validate("shot", shot)
    if issues:
        raise ShotError(f"shot {shot.get('id', '?')} is invalid: " + "; ".join(map(str, issues)))
    n_frames = frames(shot["duration_s"], fps)
    bg_id = shot["background"]
    bg_file = film_dir / "backgrounds" / bg_id / "layers.json"
    if not bg_file.is_file():
        raise ShotError(f"background {bg_id!r} not found at {bg_file}")
    background = load_background(bg_file)

    dialogue = shot.get("dialogue", [])
    placed = []
    for ch in shot["characters"]:
        cid = ch["id"]
        rig_file = film_dir / "characters" / cid / "rig.json"
        if not rig_file.is_file():
            raise ShotError(f"character {cid!r} not found at {rig_file}")
        rig = load_rig(rig_file)
        view = rig.view(ch.get("view"))
        scale = float(ch.get("scale", 1.0))
        facing = ch.get("facing", "right")
        ground = ground_offset_px(view)
        feet = Vec(ch["position"][0] * DESIGN.width, ch["position"][1] * DESIGN.height)
        root = Vec(feet.x, feet.y - ground * scale)  # screen px, y down
        track = facings = travel = None
        if ch.get("path"):  # the character moves: walk_cycle steps with the distance covered
            track = placement.frame_positions(ch["position"], ch["path"], fps, n_frames)
            walking = placement.walking_frames(ch.get("actions", []), fps, n_frames)
            facings = placement.facing_frames(facing, track, walking)
            travel = placement.forward_travel(
                track, facings, width_px=DESIGN.width, height_px=DESIGN.height, scale=scale
            )

        actions = []
        for action in ch.get("actions", []):
            action = json.loads(json.dumps(action))  # don't mutate the spec
            target = action.get("params", {}).get("target")
            if target is not None:  # frame fractions → design px, mirrored for a left-facer
                x, y = target[0] * DESIGN.width, target[1] * DESIGN.height
                action["params"]["target"] = [2 * root.x - x if facing == "left" else x, y]
            actions.append(action)
        hand_poses = []
        for hp in ch.get("hands", []):  # set_hand: which hand, by the forearm bone that has it
            bone = hand_bone(view, hp["side"])
            if bone is None:
                raise ShotError(f"{cid!r} has no {hp['side']} hand poses (its rig has no `hands`)")
            hand_poses.append({"bone": bone, "pose": hp["pose"], "start_s": hp["start_s"]})
        anim = animate(
            view,
            actions,
            fps=fps,
            n_frames=n_frames,
            root_px=root,
            scale=scale,
            seed=f"{shot['id']}:{cid}",
            poses=ch.get("poses"),
            hand_poses=hand_poses,
            travel=travel,
        )
        attachments = None
        if "face" in view:
            lines = [line for line in dialogue if line["character"] == cid]
            attachments = face_attachments(
                view,
                DESIGN,
                expression=expression_track(ch.get("expressions", []), fps),
                eyes=anim.eyes or "open",
                mouth=dialogue_mouth(film_dir, lines, fps),
            )
        attachments = merge_attachments(
            attachments, hand_attachments(view, DESIGN, hand_tracks(anim.hands))
        )
        built = build_character(
            rig,
            ch.get("view"),
            DESIGN,
            file_prefix=f"../../characters/{cid}",
            offsets=dict(anim.angles),
            shifts=anim.shifts,
            attachments=attachments,
            bend=bend,
        )
        placed.append(
            PlacedCharacter(
                built, tuple(ch["position"]), scale, facing, ground, track=track, facings=facings
            )
        )

    canvas = build_scene(
        fps=fps,
        n_frames=n_frames,
        background=background,
        background_prefix=f"../../backgrounds/{bg_id}",
        characters=placed,
        camera=shot.get("camera"),
        name=shot["id"],
    )
    wavs = []
    for line in dialogue:
        wav = film_dir / "audio" / "dialogue" / f"{line['line_id']}.wav"
        if not wav.is_file():
            raise ShotError(f"line {line['line_id']} has no audio at {wav}")
        wavs.append((wav, float(line["start_s"])))
    return BuiltShot(canvas, fps, n_frames, wavs)


def render_shot(
    film_dir: Path,
    shot_id: str,
    *,
    fps: int = DEFAULT_FPS,
    size: tuple[int, int] | None = None,
    audio: bool = True,
    keep_frames: bool = True,
    bend: bool = True,
    cfg: StudioConfig | None = None,
) -> RenderedShot:
    """Build shots/<id>/scene.sif from shot.json, render it and encode shot.mp4 with dialogue
    (unless `audio` is False). `size` renders smaller than the 1920x1080 design (e.g. (640, 360)
    for a quick preview). `bend=False` turns limb bending off: two rigid parts per limb."""
    cfg = cfg or load_config()
    shot = load_shot(film_dir, shot_id)
    built = build_shot(film_dir, shot, fps=fps, bend=bend)
    folder = shot_dir(film_dir, shot_id)
    sif = built.canvas.save(folder / "scene.sif")
    frames_dir = folder / "frames"
    rendered = render_frames(sif, frames_dir, size=size, cfg=cfg)
    if len(rendered) != built.n_frames:
        raise RenderError(f"expected {built.n_frames} frames, synfig wrote {len(rendered)}")
    mix = mix_shot(film_dir, shot, folder / "mix.wav", cfg) if audio else None
    mp4 = encode_mp4(frames_dir, folder / "shot.mp4", fps, audio=mix, cfg=cfg)
    if not keep_frames:
        shutil.rmtree(frames_dir)
        rendered = []
    return RenderedShot(sif, rendered, mp4)


def render_preview(
    film_dir: Path,
    shot_id: str,
    time_s: float,
    *,
    scale: float = 0.5,
    fps: int = DEFAULT_FPS,
    cfg: StudioConfig | None = None,
) -> tuple[Path, int, tuple[int, int]]:
    """Render the single frame at time_s to shots/<id>/preview.png (also refreshes scene.sif).
    Returns (png, frame index, size). scale 0.5 = 960x540."""
    shot = load_shot(film_dir, shot_id)
    if not 0 <= time_s < shot["duration_s"]:
        raise ShotError(f"time {time_s}s is outside the {shot['duration_s']}s shot")
    if not 0.1 <= scale <= 1:
        raise ShotError(f"scale must be between 0.1 and 1, not {scale}")
    built = build_shot(film_dir, shot, fps=fps)
    folder = shot_dir(film_dir, shot_id)
    sif = built.canvas.save(folder / "scene.sif")
    frame = min(frames(time_s, fps), built.n_frames - 1)
    size = (round(DESIGN.width * scale), round(DESIGN.height * scale))
    scratch = folder / ".preview"
    out = render_frames(sif, scratch, begin=frame, end=frame, size=size, cfg=cfg)
    png = folder / "preview.png"
    shutil.move(out[0], png)
    shutil.rmtree(scratch)
    return png, frame, size
