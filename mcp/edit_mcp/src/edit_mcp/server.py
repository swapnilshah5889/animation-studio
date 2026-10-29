"""edit_mcp: the director's editing tools over MCP (stdio), Step 5.

    uv run edit-mcp                                      # stdio (any MCP client)
    npx @modelcontextprotocol/inspector uv run edit-mcp  # browse and call the tools

Finished shot videos (shots/<id>/shot.mp4) become one film: assemble writes the edit spec
(edit/edit.json, engine-neutral) and the MLT project (edit/film.mlt) with title cards and
cross-fades or cuts; render_film encodes edit/final.mp4 with melt and checks it. create_film
makes the empty film folder everything else lives in.

Same conventions as synfig_mcp (D-034): docstrings written for the model, validated arguments,
structured results with absolute file paths inside the film folder, refused requests raised as
ToolError with a message saying what to fix, and slow work (ffmpeg, melt) in a worker thread.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from studio_core.audio.ffmpeg import AudioError
from studio_core.config import load_config
from studio_core.edit import build
from studio_core.edit import spec as edit_spec
from studio_core.edit.render import probe, run_melt, verify
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.shot_spec import FILM_SLUG

FilmArg = Annotated[str, Field(description="Film folder name under films/, e.g. 'step3-demo'.")]
ShotArg = Annotated[str, Field(pattern=r"^s[0-9]{2}_sh[0-9]{2}$", description="A shot id.")]

INSTRUCTIONS = """\
Editing tools for a children's film: finished shots in, one film out.

- create_film starts an empty film folder (a name, a title, a style).
- describe_edit lists the shots that have a rendered picture (shot.mp4), their lengths, and the
  current edit if there is one. Render shots with the animation server first (render_shot).
- assemble puts shots in order with optional title cards and cross-fades or cuts, and builds the
  edit. Run it again to change the edit; it replaces the old one.
- render_film encodes the edit to edit/final.mp4 and checks it: size, one video and one audio
  stream, the length (shots minus cross-fade overlaps) and the loudness (-14 LUFS). Use quality
  'preview' for a quick look and 'final' for the finished 1080p film.
"""


class ShotInfo(BaseModel):
    shot_id: str
    video_path: str
    duration_s: float
    width: int
    height: int
    has_audio: bool


class ClipInfo(BaseModel):
    kind: str
    shot_id: str | None
    text: str | None
    duration_s: float
    start_s: float
    transition_in: str | None = Field(description="'cut' or 'crossfade' into this clip.")


class EditInfo(BaseModel):
    spec_path: str
    mlt_path: str | None
    clips: list[ClipInfo]
    duration_s: float = Field(description="Film length: the clips minus the cross-fade overlaps.")
    final_path: str | None = Field(description="edit/final.mp4 if it has been rendered.")


class FilmDescription(BaseModel):
    film: str
    title: str | None
    style: str | None
    rendered_shots: list[ShotInfo]
    unrendered_shots: list[str] = Field(description="Shots with a spec but no shot.mp4 yet.")
    edit: EditInfo | None


class CreateResult(BaseModel):
    film: str
    film_path: str
    film_json_path: str
    style: str
    next_step: str


class TitleIn(BaseModel):
    text: str = Field(min_length=1, max_length=120, description="The card's main text.")
    subtitle: str | None = Field(default=None, max_length=160)
    duration_s: Annotated[float, Field(ge=1, le=10)] = 3.0
    position: str = Field(
        default="start",
        description="'start', 'end', or a shot id to put the card just before that shot.",
    )


class TransitionIn(BaseModel):
    into: ShotArg = Field(description="The join INTO this shot (from whatever comes before it).")
    type: Literal["cut", "crossfade"] = "crossfade"
    duration_s: Annotated[float, Field(gt=0, le=3)] = edit_spec.DEFAULT_CROSSFADE_S


class AssembleResult(BaseModel):
    spec_path: str
    mlt_path: str
    clips: list[ClipInfo]
    duration_s: float
    n_frames: int


class RenderResult(BaseModel):
    final_path: str
    quality: str
    width: int
    height: int
    duration_s: float
    expected_duration_s: float
    integrated_lufs: float | None
    true_peak_db: float | None
    normalised_db: float | None = Field(
        description="Gain applied to bring the loudness into range; null when none was needed."
    )
    render_seconds: float
    checks_passed: bool
    problems: list[str]


@contextmanager
def fixable() -> Iterator[None]:
    """Turn our validation errors into ToolErrors the model can read and act on."""
    try:
        yield
    except ToolError:
        raise
    except (ValueError, RuntimeError, AudioError, FileExistsError, KeyError) as e:
        raise ToolError(str(e.args[0]) if isinstance(e, KeyError) else str(e)) from None


def _clips(spec: dict[str, Any]) -> list[ClipInfo]:
    fps = spec["fps"]
    out = []
    for clip, p in zip(spec["clips"], edit_spec.layout(spec), strict=True):
        t = clip.get("transition_in")
        out.append(
            ClipInfo(
                kind=clip["kind"],
                shot_id=clip.get("shot"),
                text=clip.get("text"),
                duration_s=round(p.length / fps, 3),
                start_s=round(p.start / fps, 3),
                transition_in=(t["type"] if t else "cut") if p.index else None,
            )
        )
    return out


def create_server(films_root: Path | None = None) -> MCPServer:
    """The server, with every tool registered."""
    cfg = load_config()
    root = films_root or cfg.path("paths", "films")
    server = MCPServer(
        "edit_mcp",
        title="Animation studio: editing (shots into a film)",
        instructions=INSTRUCTIONS,
        version="0.1.0",
    )

    def tool(name: str | None = None) -> Any:
        def register(fn: Any) -> Any:
            server.add_tool(fn, name=name, description=inspect.cleandoc(fn.__doc__ or ""))
            return fn

        return register

    def open_film(film: str) -> Path:
        if not FILM_SLUG.match(film):
            raise ValueError(f"film {film!r} is not a film name (lowercase letters, digits, '-')")
        path = root / film
        if not (path / "film.json").is_file():
            known = sorted(p.name for p in root.iterdir() if (p / "film.json").is_file())
            raise ValueError(f"no film {film!r}; films: {known or 'none yet (create_film)'}")
        return path

    async def in_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))

    @tool()
    def create_film(
        film: Annotated[
            str,
            Field(
                pattern=r"^[a-z0-9][a-z0-9-]{0,59}$",
                description="Lowercase letters, digits and '-', e.g. 'bo-and-the-kite'.",
            ),
        ],
        title: Annotated[str, Field(min_length=1, max_length=120, description="The film's title.")],
        style: Annotated[
            str | None,
            Field(description="A style preset id; omit for the studio default (see describe_art)."),
        ] = None,
    ) -> CreateResult:
        """Create a new, empty film: films/<film>/film.json with its title and its art style. The
        style is locked once the film has a character, so choose it now. Refuses a name that
        already exists."""
        with fixable():
            path = root / film
            if path.exists():
                raise ValueError(f"films/{film} already exists; pick another name or use it")
            style_id = style or cfg.get("comfyui", "default_style", "storybook")
            created = Film.create(path, style_id, load_manifest())
            created.data["title"] = title
            created.save()
            return CreateResult(
                film=film,
                film_path=str(path),
                film_json_path=str(created.file),
                style=style_id,
                next_step="design_character and generate_background (comfy_mcp), then create_scene",
            )

    @tool()
    async def describe_edit(film: FilmArg) -> FilmDescription:
        """The film's editing state: which shots have a rendered picture (shot.mp4) with their
        durations, which shots are still unrendered, and the current edit (clips, joins, length)
        if assemble has been run. Call this before assemble."""
        with fixable():
            path = open_film(film)

            def look() -> FilmDescription:
                info = []
                for sid in build.rendered_shots(path):
                    video = edit_spec.shot_video(path, sid)
                    p = probe(video, cfg)
                    info.append(
                        ShotInfo(
                            shot_id=sid,
                            video_path=str(video),
                            duration_s=round(p.duration_s, 3),
                            width=p.width,
                            height=p.height,
                            has_audio=p.has_audio,
                        )
                    )
                shots_dir = path / "shots"
                everything = (
                    sorted(d.name for d in shots_dir.iterdir() if d.is_dir())
                    if shots_dir.is_dir()
                    else []
                )
                done = {s.shot_id for s in info}
                spec = edit_spec.load(path)
                edit = None
                if spec:
                    mlt = edit_spec.edit_dir(path) / "film.mlt"
                    final = edit_spec.edit_dir(path) / "final.mp4"
                    edit = EditInfo(
                        spec_path=str(edit_spec.spec_file(path)),
                        mlt_path=str(mlt) if mlt.is_file() else None,
                        clips=_clips(spec),
                        duration_s=round(edit_spec.total_seconds(spec), 3),
                        final_path=str(final) if final.is_file() else None,
                    )
                data = Film.load(path).data
                return FilmDescription(
                    film=film,
                    title=data.get("title"),
                    style=data.get("style"),
                    rendered_shots=info,
                    unrendered_shots=[s for s in everything if s not in done],
                    edit=edit,
                )

            return await in_thread(look)

    @tool()
    async def assemble(
        film: FilmArg,
        shots: Annotated[
            list[ShotArg],
            Field(min_length=1, max_length=100, description="Shot ids in playing order."),
        ],
        default_transition: Annotated[
            Literal["cut", "crossfade"], Field(description="How clips join unless overridden.")
        ] = "cut",
        transitions: Annotated[
            list[TransitionIn] | None,
            Field(max_length=100, description="Per-join overrides, by the shot joined into."),
        ] = None,
        titles: Annotated[list[TitleIn] | None, Field(max_length=20)] = None,
    ) -> AssembleResult:
        """Put rendered shots in order and build the film's edit (edit/edit.json and the MLT
        project edit/film.mlt). Every shot needs a rendered shot.mp4 (describe_edit). Optional
        title cards (text on a plain cream backdrop, 3 s, at the start, the end or before a shot)
        and joins: 'cut', or 'crossfade' (0.5 s by default, which overlaps the two clips and so
        shortens the film). Replaces any earlier edit; render_film makes the video."""
        with fixable():
            path = open_film(film)
            spec = await in_thread(
                build.assemble,
                path,
                list(shots),
                default_transition=default_transition,
                transitions=[t.model_dump() for t in transitions or []],
                titles=[t.model_dump() for t in titles or []],
                cfg=cfg,
            )
            (edit_spec.edit_dir(path) / "final.mp4").unlink(missing_ok=True)  # now out of date
            return AssembleResult(
                spec_path=str(edit_spec.spec_file(path)),
                mlt_path=str(edit_spec.edit_dir(path) / "film.mlt"),
                clips=_clips(spec),
                duration_s=round(edit_spec.total_seconds(spec), 3),
                n_frames=edit_spec.total_frames(spec),
            )

    @tool()
    async def render_film(
        ctx: Context,
        film: FilmArg,
        quality: Annotated[
            Literal["preview", "final"],
            Field(description="'preview' 640x360 (quick look), 'final' 1920x1080."),
        ] = "final",
    ) -> RenderResult:
        """Encode the assembled edit to edit/final.mp4 with melt (about 6 s for a 30 s film at
        1080p), then check it: video and audio streams, the size, a length equal to the shots
        minus cross-fade overlaps, and a loudness within 1 LU of -14 LUFS (corrected with one
        linear gain if it is off, reported as normalised_db). checks_passed false lists the
        problems."""
        with fixable():
            path = open_film(film)
            spec = edit_spec.load(path)
            mlt = edit_spec.edit_dir(path) / "film.mlt"
            if spec is None or not mlt.is_file():
                raise ValueError("nothing to render: run assemble first")
            for clip in spec["clips"]:
                if not (path / clip["file"]).is_file():
                    raise ValueError(f"{clip['file']} is missing; render the shot, then assemble")
            out = edit_spec.edit_dir(path) / "final.mp4"
            progress = {"pct": 0, "done": False}

            def work() -> Any:
                t0 = time.monotonic()
                try:
                    run_melt(
                        mlt, out, quality, spec["fps"], lambda p: progress.update(pct=p), cfg=cfg
                    )
                    report = verify(out, spec, quality, cfg)
                    report.render_seconds = round(time.monotonic() - t0, 1)
                    return report
                finally:
                    progress["done"] = True

            result: dict[str, Any] = {}

            async def runner() -> None:
                try:
                    result["report"] = await in_thread(work)
                except Exception as e:  # re-raised below, outside the task group
                    result["error"] = e

            async with anyio.create_task_group() as tg:
                tg.start_soon(runner)
                while not progress["done"]:
                    await anyio.sleep(1)
                    await ctx.report_progress(progress["pct"], 100, f"encoding {progress['pct']}%")
            if "error" in result:
                raise result["error"]
            r = result["report"]
            return RenderResult(
                final_path=str(r.path),
                quality=quality,
                width=r.width,
                height=r.height,
                duration_s=r.duration_s,
                expected_duration_s=r.expected_duration_s,
                integrated_lufs=r.integrated_lufs,
                true_peak_db=r.true_peak_db,
                normalised_db=r.normalised_db,
                render_seconds=r.render_seconds,
                checks_passed=r.ok,
                problems=r.problems,
            )

    return server


def main() -> None:
    create_server().run()  # stdio


if __name__ == "__main__":
    main()
