"""synfig_mcp: the director's animation tools over MCP (stdio).

    uv run synfig-mcp                                      # stdio (any MCP client)
    npx @modelcontextprotocol/inspector uv run synfig-mcp  # browse and call the tools

The tools edit **intent** in shots/<id>/shot.json (studio_core.shot_spec, engine-neutral, D-030)
and render it through the Synfig backend (studio_core.shot). Tool names and arguments never
mention Synfig, so another backend can sit behind the same tools later (ROADMAP Step 6).

Every refused edit raises ToolError: the client gets `is_error` and the message, which says what
to fix ("unknown bone 'tail'; pip has: ..."). Nothing is saved when an edit is refused.
Media results are file paths inside the film folder, never bytes (AGENTS.md).
"""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from studio_core import placement, shot_spec
from studio_core.config import load_config
from studio_core.face import EXPRESSIONS
from studio_core.motions import MOTIONS
from studio_core.rig import load_rig
from studio_core.scene import CAMERA_MOVES
from studio_core.schema import SCHEMA_DIR
from studio_core.shot import render_preview, render_shot
from studio_core.sif.render import RenderError
from studio_core.sif.units import frames

_SHOT = json.loads((SCHEMA_DIR / "shot.schema.json").read_text())["$defs"]
# Enums come from the shot schema and the code that implements them, so the tool schemas the
# model sees can't drift from what the spec accepts.
Motion = Literal[tuple(_SHOT["action"]["properties"]["motion"]["enum"])]  # type: ignore[valid-type]
Expression = Literal[tuple(EXPRESSIONS)]  # type: ignore[valid-type]
CameraMove = Literal[tuple(CAMERA_MOVES)]  # type: ignore[valid-type]
Ease = Literal[tuple(placement.EASES)]  # type: ignore[valid-type]
View = Literal["front", "three_quarter"]
Side = Literal["left", "right"]
Removable = Literal[tuple(shot_spec.REMOVABLE)]  # type: ignore[valid-type]
assert set(_SHOT["action"]["properties"]["motion"]["enum"]) == set(MOTIONS)

FilmArg = Annotated[str, Field(description="Film folder name under films/, e.g. 'step2-demo'.")]
ShotArg = Annotated[
    str, Field(pattern=r"^s[0-9]{2}_sh[0-9]{2}$", description="Shot id, e.g. 's01_sh01'.")
]
CharArg = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$", description="Character id, e.g. 'pip'.")
]
Seconds = Annotated[float, Field(ge=0, description="Seconds from the start of the shot.")]
FramePos = Annotated[
    tuple[
        Annotated[float, Field(ge=-0.5, le=1.5)],
        Annotated[float, Field(ge=-0.5, le=1.5)],
    ],
    Field(description="[x, y] as fractions of the frame: [0, 0] top-left, [1, 1] bottom-right."),
]

INSTRUCTIONS = """\
Animation tools for a children's cut-out film. A shot is a spec (shots/<id>/shot.json) that you
build up with small edits, check, then render.

Typical order: describe_film (what exists: characters, bones, backgrounds, recorded lines,
music cues, motions) → create_scene → add_character → apply_motion / set_expression /
apply_lipsync / pose_at / camera_move → add_sound_effect / set_music → describe_shot (spec +
warnings) → render_preview_frame at a few key times → render_shot.

Lines, music and sounds are made on the audio server (audio_mcp: speak, compose, find_sfx);
these tools place them in a shot by id.

Conventions: times are seconds from the start of the shot. Positions are frame fractions,
[0, 0] top-left to [1, 1] bottom-right; a character's position is where its feet touch the
ground ([0.5, 0.92] = centre, near the bottom). Every character should get 'blink' and usually
'idle_breathe' for the whole shot so it looks alive. Edits that would make the spec invalid are
refused with a message saying what to fix; nothing is saved then.
"""


class ShotUpdate(BaseModel):
    shot_id: str
    spec_path: str = Field(description="The saved shot spec.")
    change: str = Field(description="What this call changed.")
    warnings: list[str] = Field(description="Problems that don't block rendering.")


class CharacterInfo(BaseModel):
    id: str
    name: str
    views: dict[str, list[str]] = Field(description="View name → bone names (for pose_at).")
    has_face: bool = Field(description="True if expressions, blinks and lip-sync work.")


class BackgroundInfo(BaseModel):
    id: str
    name: str
    layers: list[str] = Field(description="Far to near: 'name (parallax factor)'.")


class LineInfo(BaseModel):
    line_id: str
    text: str | None
    duration_s: float
    has_mouth_cues: bool


class FilmDescription(BaseModel):
    film: str
    path: str
    characters: list[CharacterInfo]
    backgrounds: list[BackgroundInfo]
    dialogue_lines: list[LineInfo]
    shots: list[str]
    motions: dict[str, str] = Field(description="Motion name → what it does.")
    expressions: list[str]
    camera_moves: list[str]
    music_cues: list[str] = Field(description="Music cue ids made with compose (set_music).")


class ShotDescription(BaseModel):
    shot_id: str
    spec: dict[str, Any] = Field(description="The shot spec, as saved.")
    fps: int
    n_frames: int
    errors: list[str] = Field(description="Problems that block rendering (fix these first).")
    warnings: list[str]
    files: dict[str, str | None] = Field(description="Rendered outputs, null if not rendered yet.")


class RigResult(BaseModel):
    character_id: str
    rig_path: str
    placeholder: bool = Field(description="True if the placeholder puppet was used.")
    views: dict[str, list[str]] = Field(description="View name → bone names.")


class PreviewResult(BaseModel):
    image_path: str
    frame: int
    size: tuple[int, int]


class RenderResult(BaseModel):
    video_path: str
    scene_path: str
    frames: int
    duration_s: float
    size: tuple[int, int]
    render_seconds: float


@contextmanager
def fixable() -> Iterator[None]:
    """Turn our validation errors into ToolErrors the model can read and act on."""
    try:
        yield
    except ToolError:
        raise
    except (ValueError, RenderError) as e:  # SpecError, ShotError, RigError, MotionError, ...
        raise ToolError(str(e)) from None


def _motion_help() -> dict[str, str]:
    """Motion name → the first paragraph of its docstring, on one line."""
    return {
        name: " ".join((fn.__doc__ or "").strip().split("\n\n")[0].split())
        for name, fn in sorted(MOTIONS.items())
    }


def create_server(films_root: Path | None = None, sfx_root: Path | None = None) -> MCPServer:
    """The server, with every tool registered. `films_root` defaults to config [paths] films,
    `sfx_root` (the sound library) to config [paths] sfx_library."""
    root = films_root or load_config().path("paths", "films")
    server = MCPServer(
        "synfig_mcp",
        title="Animation studio (cut-out animation)",
        instructions=INSTRUCTIONS,
        version="0.1.0",
    )

    def tool(name: str | None = None) -> Any:
        """Register a tool with its docstring cleaned of code indentation (the model reads it)."""

        def register(fn: Any) -> Any:
            server.add_tool(fn, name=name, description=inspect.cleandoc(fn.__doc__ or ""))
            return fn

        return register

    def open_film(film: str) -> shot_spec.FilmFolder:
        return shot_spec.FilmFolder.open(root, film, sfx_root=sfx_root)

    def update(
        film: shot_spec.FilmFolder, shot_id: str, change: str, warnings: list[str]
    ) -> ShotUpdate:
        return ShotUpdate(
            shot_id=shot_id,
            spec_path=str(film.shot_file(shot_id)),
            change=change,
            warnings=warnings,
        )

    # ----------------------------------------------------------------- reading state

    @tool()
    def describe_film(film: FilmArg) -> FilmDescription:
        """What a film has to work with: characters (with their views and bone names), parallax
        backgrounds, recorded dialogue lines (with text and length), existing shots, and the
        available motions, expressions and camera moves. Call this first."""
        with fixable():
            f = open_film(film)
            chars = []
            for cid in f.characters():
                rig = load_rig(f.rig_file(cid), check_files=False)
                views = {name: sorted(v["bones"]) for name, v in rig.data["views"].items()}
                has_face = any("face" in v for v in rig.data["views"].values())
                chars.append(
                    CharacterInfo(id=cid, name=rig.data["name"], views=views, has_face=has_face)
                )
            backgrounds = []
            for bid in f.backgrounds():
                data = json.loads(f.background_file(bid).read_text())
                layers = [
                    f"{layer['name']} ({layer['parallax']}"
                    + (", in front)" if layer.get("in_front") else ")")
                    for layer in data["layers"]
                ]
                backgrounds.append(
                    BackgroundInfo(id=bid, name=data.get("name", bid), layers=layers)
                )
            lines = []
            for line_id in f.lines():
                wav, cues, txt = f.line_files(line_id)
                lines.append(
                    LineInfo(
                        line_id=line_id,
                        text=txt.read_text().strip() if txt.is_file() else None,
                        duration_s=round(shot_spec.wav_seconds(wav), 2),
                        has_mouth_cues=cues.is_file(),
                    )
                )
            return FilmDescription(
                film=film,
                path=str(f.root),
                characters=chars,
                backgrounds=backgrounds,
                dialogue_lines=lines,
                shots=f.shots(),
                motions=_motion_help(),
                expressions=list(EXPRESSIONS),
                camera_moves=list(CAMERA_MOVES),
                music_cues=f.music_cues(),
            )

    @tool()
    def describe_shot(film: FilmArg, shot_id: ShotArg) -> ShotDescription:
        """The shot's current spec, with errors (block rendering) and warnings, and the paths of
        anything already rendered. Cheap: call it after a few edits to check your work."""
        with fixable():
            f = open_film(film)
            spec = shot_spec.load(f, shot_id)
            errors, warnings = shot_spec.check(f, spec)
            folder = f.shot_file(shot_id).parent
            files = {
                name: str(folder / name) if (folder / name).is_file() else None
                for name in ("scene.sif", "preview.png", "shot.mp4")
            }
            return ShotDescription(
                shot_id=shot_id,
                spec=spec,
                fps=shot_spec.FPS,
                n_frames=frames(spec["duration_s"], shot_spec.FPS),
                errors=errors,
                warnings=warnings,
                files=files,
            )

    # ----------------------------------------------------------------- editing a shot

    @tool()
    def create_scene(
        film: FilmArg,
        shot_id: ShotArg,
        duration_s: Annotated[float, Field(gt=0, le=60, description="Shot length in seconds.")],
        background: Annotated[str, Field(description="Background id (see describe_film).")],
        camera_move: CameraMove = "static",
        zoom: Annotated[
            float, Field(ge=0.5, le=3, description="Starting zoom; 1 = full frame.")
        ] = 1.0,
        replace: Annotated[
            bool, Field(description="Start an existing shot over from scratch.")
        ] = False,
    ) -> ShotUpdate:
        """Create a new, empty shot with a background and a camera move over the whole shot.
        Add characters next with add_character."""
        with fixable():
            f = open_film(film)
            camera = (
                {"move": camera_move, "zoom": zoom}
                if camera_move != "static" or zoom != 1
                else None
            )
            warnings = shot_spec.create_shot(
                f, shot_id, duration_s, background, camera, replace=replace
            )
            return update(f, shot_id, f"created {duration_s}s shot on '{background}'", warnings)

    @tool()
    def add_character(
        film: FilmArg,
        shot_id: ShotArg,
        character_id: CharArg,
        position: Annotated[
            FramePos,
            Field(
                description="Where the feet touch the ground, as frame fractions. "
                "[0.5, 0.92] = centre, standing near the bottom."
            ),
        ],
        view: View | None = None,
        scale: Annotated[float | None, Field(ge=0.2, le=3, description="1 = natural size.")] = None,
        facing: Side | None = None,
    ) -> ShotUpdate:
        """Put a character in the shot, or move it if it is already there (its motions,
        expressions and poses are kept). Characters are drawn back to front in the order
        added."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.place_character(
                f, shot_id, character_id, list(position), view=view, scale=scale, facing=facing
            )
            return update(f, shot_id, f"{character_id} placed at {list(position)}", warnings)

    @tool()
    def apply_motion(
        film: FilmArg,
        shot_id: ShotArg,
        character_id: CharArg,
        motion: Motion,
        start_s: Seconds,
        duration_s: Annotated[
            float | None,
            Field(gt=0, description="Defaults to the motion's natural length."),
        ] = None,
        energy: Annotated[
            float | None, Field(ge=0, le=1, description="0 = subtle, 1 = big and fast.")
        ] = None,
        side: Annotated[
            Side | None, Field(description="Which arm/side, from the character's view.")
        ] = None,
        cycles: Annotated[
            int | None, Field(ge=1, le=20, description="Repetitions (wave swings, steps).")
        ] = None,
        target: Annotated[
            FramePos | None, Field(description="For 'point': where to point, in the frame.")
        ] = None,
    ) -> ShotUpdate:
        """Add a named motion from the motion library, starting at start_s. Later motions take
        over a limb from earlier ones; idle_breathe adds on top of everything. For a living
        character, add 'blink' and 'idle_breathe' with start_s 0 and duration_s = the shot."""
        with fixable():
            f = open_film(film)
            params: dict[str, Any] = {}
            for key, value in (
                ("energy", energy),
                ("side", side),
                ("cycles", cycles),
                ("target", list(target) if target else None),
            ):
                if value is not None:
                    params[key] = value
            warnings = shot_spec.add_action(
                f, shot_id, character_id, motion, start_s, duration_s=duration_s, params=params
            )
            return update(f, shot_id, f"{character_id}: {motion} at {start_s}s", warnings)

    @tool()
    def move_character(
        film: FilmArg,
        shot_id: ShotArg,
        character_id: CharArg,
        to: Annotated[
            FramePos, Field(description="Where its feet end up: [x, y] frame fractions.")
        ],
        start_s: Seconds,
        duration_s: Annotated[float, Field(gt=0, description="How long the move takes.")],
        ease: Annotated[
            Ease,
            Field(
                description="ease_in_out (default: starts and stops gently), linear (constant "
                "speed), ease_in (starts slow), ease_out (ends slow)."
            ),
        ] = "ease_in_out",
    ) -> ShotUpdate:
        """Move a character across the frame: it stays where it is until start_s, then travels
        to `to` in duration_s. Moves must come in time order (a new move cannot start before the
        last one ends). To WALK while moving, also apply_motion 'walk_cycle' over the same time
        span: the steps then match the distance covered (code decides the step count, so feet do
        not slide) and the character turns to face the direction of travel. Without walk_cycle it
        just glides. Walking across the frame swings the legs sideways, which suits side-on art;
        in the front view it reads as a simple toy-like waddle."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.move_character(
                f, shot_id, character_id, list(to), start_s, duration_s, ease
            )
            return update(
                f, shot_id, f"{character_id}: moves to {list(to)} at {start_s}s", warnings
            )

    @tool()
    def pose_at(
        film: FilmArg,
        shot_id: ShotArg,
        character_id: CharArg,
        time_s: Seconds,
        bone_angles: Annotated[
            dict[str, float],
            Field(
                min_length=1,
                description="Bone name → degrees from the rest pose (positive = "
                "counter-clockwise on screen). Bone names: describe_film.",
            ),
        ],
    ) -> ShotUpdate:
        """A manual key pose: these bones reach these angles at time_s and hold until the next
        key. Angles are clamped to each joint's limits. Prefer apply_motion when a motion fits."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.add_pose(f, shot_id, character_id, time_s, bone_angles)
            return update(f, shot_id, f"{character_id}: pose at {time_s}s", warnings)

    @tool()
    def set_expression(
        film: FilmArg, shot_id: ShotArg, character_id: CharArg, expr: Expression, start_s: Seconds
    ) -> ShotUpdate:
        """Change the character's expression (brows and resting mouth) from start_s on. The
        character is 'neutral' until its first expression."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.add_expression(f, shot_id, character_id, expr, start_s)
            return update(f, shot_id, f"{character_id}: {expr} from {start_s}s", warnings)

    @tool()
    def apply_lipsync(
        film: FilmArg,
        shot_id: ShotArg,
        character_id: CharArg,
        line_id: Annotated[
            str,
            Field(pattern=r"^l[0-9]{3,}$", description="A recorded line (see describe_film)."),
        ],
        start_s: Seconds,
        text: Annotated[
            str | None, Field(description="The words; defaults to the line's transcript.")
        ] = None,
    ) -> ShotUpdate:
        """The character speaks a recorded dialogue line starting at start_s: the line's audio
        plays in the shot and its mouth cues drive the character's mouth. Calling it again with
        the same line_id moves the line."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.add_dialogue(f, shot_id, character_id, line_id, start_s, text)
            return update(f, shot_id, f"{character_id} says {line_id} at {start_s}s", warnings)

    @tool()
    def add_parallax_background(
        film: FilmArg,
        shot_id: ShotArg,
        background_id: Annotated[str, Field(description="Background id (see describe_film).")],
    ) -> ShotUpdate:
        """Set the shot's background: a set of depth layers that slide at different speeds when
        the camera pans (parallax). Its layers are listed by describe_film."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.set_background(f, shot_id, background_id)
            return update(f, shot_id, f"background is now '{background_id}'", warnings)

    @tool()
    def camera_move(
        film: FilmArg,
        shot_id: ShotArg,
        move: CameraMove,
        start_s: Annotated[float | None, Field(ge=0, description="Defaults to 0.")] = None,
        duration_s: Annotated[
            float | None, Field(gt=0, description="Defaults to the rest of the shot.")
        ] = None,
        zoom: Annotated[
            float | None, Field(ge=0.5, le=3, description="Starting zoom; 1 = full frame.")
        ] = None,
    ) -> ShotUpdate:
        """Set the shot's camera move (one per shot). Pans travel a fixed, gentle distance;
        push_in / pull_out zoom by 1.25x; all ease in and out."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.set_camera(
                f, shot_id, move, start_s=start_s, duration_s=duration_s, zoom=zoom
            )
            return update(f, shot_id, f"camera: {move}", warnings)

    @tool()
    def add_sound_effect(
        film: FilmArg,
        shot_id: ShotArg,
        sound_id: Annotated[
            str,
            Field(
                pattern=r"^[a-z0-9][a-z0-9_]{0,79}$",
                description="A library sound id, from audio_mcp's find_sfx.",
            ),
        ],
        start_s: Seconds,
        volume: Annotated[
            float, Field(ge=0, le=1, description="0.5 = a normal effect level; 1 = loud.")
        ] = 0.5,
        query: Annotated[
            str | None,
            Field(
                min_length=2,
                max_length=100,
                description="What the sound is for, in words (defaults to its description).",
            ),
        ] = None,
    ) -> ShotUpdate:
        """Play a sound effect from the library at start_s. Find sounds by describing them with
        audio_mcp's find_sfx, then pass the chosen sound_id here."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.add_sound_effect(
                f, shot_id, sound_id, start_s, volume=volume, query=query
            )
            return update(f, shot_id, f"sound {sound_id} at {start_s}s", warnings)

    @tool()
    def set_music(
        film: FilmArg,
        shot_id: ShotArg,
        cue_id: Annotated[
            str | None,
            Field(
                pattern=r"^[a-z][a-z0-9_]{0,39}$",
                description="A music cue made with audio_mcp's compose; null for no music.",
            ),
        ],
        volume: Annotated[
            float | None,
            Field(ge=0, le=1, description="Music level before ducking; default 0.5."),
        ] = None,
    ) -> ShotUpdate:
        """Set the shot's background music. It plays from the start of the shot and dips
        automatically while anyone speaks."""
        with fixable():
            f = open_film(film)
            warnings = shot_spec.set_music(f, shot_id, cue_id, volume=volume)
            return update(f, shot_id, f"music: {cue_id or 'none'}", warnings)

    @tool()
    def remove_from_shot(
        film: FilmArg,
        shot_id: ShotArg,
        kind: Removable,
        character_id: CharArg | None = None,
        index: Annotated[
            int | None,
            Field(ge=0, description="0-based position in the list shown by describe_shot."),
        ] = None,
    ) -> ShotUpdate:
        """Undo part of a shot: remove a character (with its dialogue), or one of a character's
        actions, poses or expressions, a character's whole movement path (kind 'movement'), or one
        dialogue line or sound effect, by its index in describe_shot."""
        with fixable():
            f = open_film(film)
            removed, warnings = shot_spec.remove_item(
                f, shot_id, kind, character_id=character_id, index=index
            )
            return update(f, shot_id, f"removed {kind}: {json.dumps(removed)}", warnings)

    # ----------------------------------------------------------------- characters

    @tool()
    def build_rig(
        film: FilmArg,
        character_id: CharArg,
        rig: Annotated[
            dict[str, Any] | None,
            Field(
                description="A rig.json document (schemas/rig.schema.json) whose part images "
                "are already in characters/<id>/. Omit it to use the placeholder puppet."
            ),
        ] = None,
    ) -> RigResult:
        """Validate and register a character's rig (bones, parts, pivots, face), making the
        character available to shots. Without a rig, a placeholder puppet is created under
        this id."""
        with fixable():
            f = open_film(film)
            path, placeholder = shot_spec.register_rig(f, character_id, rig)
            data = load_rig(path).data
            views = {name: sorted(v["bones"]) for name, v in data["views"].items()}
            return RigResult(
                character_id=character_id, rig_path=str(path), placeholder=placeholder, views=views
            )

    # ----------------------------------------------------------------- rendering

    @tool()
    async def render_preview_frame(
        film: FilmArg,
        shot_id: ShotArg,
        time_s: Seconds,
        scale: Annotated[
            float, Field(ge=0.1, le=1, description="Fraction of 1920x1080; 0.5 = 960x540.")
        ] = 0.5,
    ) -> PreviewResult:
        """Render one frame of the shot to a PNG (a few seconds), to check poses, placement
        and framing before rendering the whole shot."""
        with fixable():
            f = open_film(film)
            png, frame, size = await anyio.to_thread.run_sync(
                partial(render_preview, f.root, shot_id, time_s, scale=scale)
            )
            return PreviewResult(image_path=str(png), frame=frame, size=size)

    @tool(name="render_shot")
    async def render_shot_tool(
        film: FilmArg,
        shot_id: ShotArg,
        quality: Annotated[
            Literal["preview", "final"],
            Field(description="preview = 640x360 (fast), final = 1920x1080."),
        ] = "final",
        audio: Annotated[bool, Field(description="Mix the dialogue in.")] = True,
    ) -> RenderResult:
        """Render the whole shot to an MP4 with its dialogue (about 0.25 s per final frame:
        a 10 s shot takes about a minute). The spec is checked first."""
        with fixable():
            f = open_film(film)
            size = (640, 360) if quality == "preview" else (1920, 1080)
            spec = shot_spec.load(f, shot_id)
            errors, _ = shot_spec.check(f, spec)
            if errors:
                raise ToolError("fix the shot first: " + "; ".join(errors))
            t0 = time.monotonic()
            out = await anyio.to_thread.run_sync(
                partial(render_shot, f.root, shot_id, size=size, audio=audio)
            )
            return RenderResult(
                video_path=str(out.mp4),
                scene_path=str(out.sif),
                frames=len(out.frames),
                duration_s=spec["duration_s"],
                size=size,
                render_seconds=round(time.monotonic() - t0, 1),
            )

    return server


def main() -> None:
    create_server().run()  # stdio


if __name__ == "__main__":
    main()
