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

from studio_core import acts as act_ops
from studio_core.acts import Renderer, Target
from studio_core.audio.ffmpeg import AudioError
from studio_core.config import load_config
from studio_core.edit import build
from studio_core.edit import spec as edit_spec
from studio_core.edit.render import probe, run_melt, verify
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.shot_spec import FILM_SLUG, FilmFolder
from studio_core.store import StoreError
from studio_core.workspace import Workspace

FilmArg = Annotated[
    str,
    Field(
        description="Film name: a folder under films/ (e.g. 'step3-demo'), or with `project` the "
        "film's slug in that project."
    ),
]
ProjectArg = Annotated[
    str | None,
    Field(
        description="Project id. Omit for an old film folder; give it for a film of a project "
        "(describe_project lists them)."
    ),
]
QualityArg = Annotated[
    Literal["preview", "final"],
    Field(
        description="'preview' 640x360 (quick look), 'final' 1920x1080. A preview render never "
        "counts as a final one."
    ),
]
ActArg = Annotated[str, Field(description="An act's id, its title, or its number ('2').")]
ShotArg = Annotated[str, Field(pattern=r"^s[0-9]{2}_sh[0-9]{2}$", description="A shot id.")]

INSTRUCTIONS = """\
Editing tools for a children's film: finished shots in, one film out.

- create_film starts an empty film folder (a name, a title, a style).
- describe_edit lists the shots that have a rendered picture (shot.mp4), their lengths, and the
  current edit if there is one. Render shots with the animation server first (render_shot).
- assemble puts shots in order with optional title cards and cross-fades or cuts, and builds the
  edit. Run it again to change the edit; it replaces the old one.
- Projects: describe_project lists a project's cast, places and films; create_film with `project`
  starts a film that uses them. A film is made of acts, each with a place and several shots (camera
  angles). list_acts shows each act and whether it needs rendering (stale); add_act, edit_act,
  reorder_acts, remove_act, reorder_shots and remove_shot edit the film; shots are created and
  changed with the animation server (create_scene with `act`). render_act renders one act;
  export_movie ("export all acts") renders only the acts that changed and joins the act videos in
  order into edit/final.mp4. Nothing is baked until export: change any spec and export again.
  clear_renders throws all renders away (the specs make them again).
- assemble and render_film are for old film folders (shots in a list); a project film is exported
  with export_movie.
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


class ShotBrief(BaseModel):
    shot_id: str
    duration_s: float


class ActInfo(BaseModel):
    act_id: str
    order: int
    title: str
    background: str = Field(description="The act's place (a background slug).")
    cast: list[str]
    beats: list[str]
    shots: list[ShotBrief] = Field(description="The camera angles, in cut order.")
    stale: bool = Field(description="True when export_movie would render this act again.")
    rendered: bool = Field(description="True when the act has a render (maybe an old one).")
    problems: list[str] = Field(description="Mistakes in the act's specs; fix before rendering.")


class ActsDescription(BaseModel):
    project: str
    film: str
    quality: str
    acts: list[ActInfo]
    stale_acts: list[str] = Field(description="Titles of the acts export_movie would render.")


class ProjectDescription(BaseModel):
    project: str
    name: str
    characters: list[str] = Field(description="Character slugs in the project's library.")
    places: list[str] = Field(description="Background slugs in the project's library.")
    films: list[str]


class ActRendered(BaseModel):
    act_id: str
    title: str
    rendered: bool = Field(description="False when the act was already up to date.")
    shots: list[str]
    video_path: str | None


class MovieResult(BaseModel):
    final_path: str
    quality: str
    width: int
    height: int
    duration_s: float
    expected_duration_s: float
    integrated_lufs: float | None
    checks_passed: bool
    problems: list[str]
    rendered_acts: list[str] = Field(description="Acts rendered by this export (they had changed).")
    reused_acts: list[str] = Field(description="Acts whose earlier render was still good.")
    act_order: list[str]


def _acts_info(rows: list[dict[str, Any]]) -> list[ActInfo]:
    return [ActInfo(**r) for r in rows]


@contextmanager
def fixable() -> Iterator[None]:
    """Turn our validation errors into ToolErrors the model can read and act on."""
    try:
        yield
    except ToolError:
        raise
    except (ValueError, RuntimeError, AudioError, FileExistsError, KeyError, StoreError) as e:
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


def create_server(
    films_root: Path | None = None,
    *,
    workspace: Workspace | None = None,
    renderer: Renderer | None = None,
) -> MCPServer:
    """The server, with every tool registered. `workspace` says where films and projects live
    (default: config); `renderer` replaces the shot renderer (tests)."""
    cfg = load_config()
    ws = workspace or Workspace.from_config(cfg, films_root=films_root)
    root = ws.films_root
    engine = cfg.get("render", "engine", act_ops.DEFAULT_ENGINE)
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

    def open_folder(film: str, project: str | None, act: str | None = None) -> FilmFolder:
        if project is None:
            open_film(film)  # the friendly errors for an old film folder
        return ws.open_film(film, project, act=act)

    def open_film(film: str, project: str | None = None) -> Path:
        if project is not None:
            return ws.open_film(film, project).root
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
        project: ProjectArg = None,
        cast: Annotated[
            list[str] | None,
            Field(description="With `project`: character slugs to use; omit for all of them."),
        ] = None,
        places: Annotated[
            list[str] | None,
            Field(description="With `project`: background slugs to use; omit for all of them."),
        ] = None,
    ) -> CreateResult:
        """Create a new, empty film. Without `project`: films/<film>/film.json with its title and
        its art style (locked once the film has a character, so choose it now). With `project`: a
        film of that project that uses its characters and places (their current versions are
        pinned; they stay the same until you upgrade); add acts with add_act. Refuses a name that
        already exists."""
        with fixable():
            if project is not None:
                proj = ws.open_project(project)
                made = proj.create_film(
                    title,
                    slug=film,
                    style=style
                    or proj.doc.get("style")
                    or cfg.get("comfyui", "default_style", "storybook"),
                    cast=cast if cast is not None else [c["slug"] for c in proj.list_characters()],
                    places=(
                        places
                        if places is not None
                        else [b["slug"] for b in proj.list_backgrounds()]
                    ),
                )
                folder = ws.open_film(made["slug"], project)
                return CreateResult(
                    film=made["slug"],
                    film_path=str(folder.root),
                    film_json_path=f"project {project}, film {made['id']}",
                    style=made.get("style") or "",
                    next_step="add_act (a place and the characters in it), then create_scene "
                    "(animation server) with act for each camera angle",
                )
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
    async def describe_edit(film: FilmArg, project: ProjectArg = None) -> FilmDescription:
        """The film's editing state: which shots have a rendered picture (shot.mp4) with their
        durations, which shots are still unrendered, and the current edit (clips, joins, length)
        if assemble (or export_movie) has been run. Call this before assemble. For a film of a
        project, list_acts is the better overview."""
        with fixable():
            path = open_film(film, project)

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
                if project is None:
                    data = Film.load(path).data
                else:
                    data = ws.open_project(project).get_film(film)
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
        shortens the film). Replaces any earlier edit; render_film makes the video. For old film
        folders; a film of a project is exported with export_movie."""
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
        problems. For old film folders; a film of a project is exported with export_movie."""
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

    # ------------------------------------------------------------ projects and acts

    def with_film(film: str, project: str, act: str | None = None) -> tuple[Any, Any]:
        """(working folder, link) of a project film."""
        folder = ws.open_film(film, project, act=act)
        return folder, folder.link

    def target_of(quality: str) -> Target:
        return Target(engine, quality)

    def shots_renderer() -> Renderer:
        return renderer or act_ops.renderer_for(engine, cfg)

    async def with_progress(ctx: Context, work: Any) -> Any:
        """Run work(say) in a thread and report each message it says as progress."""
        state: dict[str, Any] = {"msg": "starting", "n": 0, "done": False, "out": None, "err": None}

        def say(msg: str) -> None:
            state["msg"], state["n"] = msg, state["n"] + 1

        async def runner() -> None:
            try:
                state["out"] = await in_thread(work, say)
            except Exception as e:  # re-raised below, outside the task group
                state["err"] = e
            finally:
                state["done"] = True

        async with anyio.create_task_group() as tg:
            tg.start_soon(runner)
            while not state["done"]:
                await anyio.sleep(1)
                await ctx.report_progress(state["n"], None, state["msg"])
        if state["err"] is not None:
            raise state["err"]
        return state["out"]

    @tool()
    def describe_project(
        project: Annotated[str, Field(description="A project id.")],
    ) -> ProjectDescription:
        """A project's library and films: the characters and places (backgrounds) every film of
        the project can use, and the films made so far. Start here to find a project's ids."""
        with fixable():
            proj = ws.open_project(project)
            return ProjectDescription(
                project=proj.id,
                name=proj.doc["name"],
                characters=[c["slug"] for c in proj.list_characters()],
                places=[b["slug"] for b in proj.list_backgrounds()],
                films=[f["slug"] for f in proj.list_films()],
            )

    @tool()
    async def list_acts(
        project: Annotated[str, Field(description="A project id.")],
        film: FilmArg,
        quality: QualityArg = "final",
    ) -> ActsDescription:
        """The film's acts in order: place, cast, beats, shots (camera angles) and for each
        whether it is stale, that is, whether export_movie would render it again because a spec
        (a shot, the act, a character version, a recorded line) changed since its last render at
        this quality. Also lists mistakes in the specs. Call this before and after editing."""
        with fixable():
            folder = ws.open_film(film, project)
            rows = await in_thread(act_ops.act_table, folder, target_of(quality))
            return ActsDescription(
                project=project,
                film=film,
                quality=quality,
                acts=_acts_info(rows),
                stale_acts=[r["title"] for r in rows if r["stale"]],
            )

    @tool()
    def add_act(
        project: Annotated[str, Field(description="A project id.")],
        film: FilmArg,
        title: Annotated[str, Field(min_length=1, max_length=80)],
        background: Annotated[
            str, Field(description="The act's place: a background slug the film uses.")
        ],
        cast: Annotated[
            list[str] | None,
            Field(description="Character slugs in the act; omit for the whole film cast."),
        ] = None,
        beats: Annotated[
            list[str] | None, Field(max_length=20, description="What happens, one line each.")
        ] = None,
    ) -> ActInfo:
        """Add an act at the end of the film. An act has one place; give it camera angles with
        create_scene (animation server, `act` argument). The background and cast must already be
        in the film (create_film chose them)."""
        with fixable():
            folder, link = with_film(film, project)
            made = link.project.add_act(
                link.film_id, title, background=background, cast=cast, beats=beats or []
            )
            row = next(
                r
                for r in act_ops.act_table(folder, target_of("final"))
                if r["act_id"] == made["id"]
            )
            return ActInfo(**row)

    @tool()
    def edit_act(
        project: Annotated[str, Field(description="A project id.")],
        film: FilmArg,
        act: ActArg,
        title: Annotated[str | None, Field(min_length=1, max_length=80)] = None,
        beats: Annotated[list[str] | None, Field(max_length=20)] = None,
        background: Annotated[
            str | None, Field(description="Move the act to another of the film's places.")
        ] = None,
        cast: Annotated[list[str] | None, Field(description="Character slugs in the act.")] = None,
    ) -> ActInfo:
        """Change an act's title, beats, place or cast. Changing the place or cast changes the
        picture, so the act becomes stale (retitling does not). The shots keep their own
        background: check list_acts for problems after moving an act."""
        with fixable():
            folder, link = with_film(film, project)
            found = act_ops.find_act(folder, act)
            proj = link.project
            if background is not None:
                proj.set_act_background(link.film_id, found["id"], background)
            changes: dict[str, Any] = {}
            if title is not None:
                changes["title"] = title
            if beats is not None:
                changes["beats"] = beats
            if changes:
                proj.update_act(found["id"], **changes)
            if cast is not None:
                proj.set_act_cast(link.film_id, found["id"], cast)
            row = next(
                r
                for r in act_ops.act_table(folder, target_of("final"))
                if r["act_id"] == found["id"]
            )
            return ActInfo(**row)

    @tool()
    def reorder_acts(
        project: Annotated[str, Field(description="A project id.")],
        film: FilmArg,
        acts: Annotated[
            list[str],
            Field(min_length=1, description="Every act (id, title or number), in the new order."),
        ],
    ) -> ActsDescription:
        """Change the order of the acts. The movie follows the new order on the next export_movie;
        no act needs rendering again."""
        with fixable():
            folder, link = with_film(film, project)
            ids = [act_ops.find_act(folder, a)["id"] for a in acts]
            link.project.reorder_acts(link.film_id, ids)
            rows = act_ops.act_table(folder, target_of("final"))
            return ActsDescription(
                project=project,
                film=film,
                quality="final",
                acts=_acts_info(rows),
                stale_acts=[r["title"] for r in rows if r["stale"]],
            )

    @tool()
    def remove_act(
        project: Annotated[str, Field(description="A project id.")], film: FilmArg, act: ActArg
    ) -> ActsDescription:
        """Delete an act with all its shots (their specs); later acts move up. Cannot be undone."""
        with fixable():
            folder, link = with_film(film, project)
            found = act_ops.find_act(folder, act)
            link.project.remove_act(link.film_id, found["id"])
            link.pull()
            rows = act_ops.act_table(folder, target_of("final"))
            return ActsDescription(
                project=project,
                film=film,
                quality="final",
                acts=_acts_info(rows),
                stale_acts=[r["title"] for r in rows if r["stale"]],
            )

    @tool()
    def reorder_shots(
        project: Annotated[str, Field(description="A project id.")],
        film: FilmArg,
        act: ActArg,
        shots: Annotated[
            list[ShotArg], Field(min_length=1, description="Every shot of the act, in cut order.")
        ],
    ) -> ActInfo:
        """Change the order of an act's shots (the cut). The act becomes stale."""
        with fixable():
            folder, link = with_film(film, project)
            found = act_ops.find_act(folder, act)
            by_spec = {
                s["spec"]["id"]: s["id"] for s in link.project.list_shots(link.film_id, found["id"])
            }
            unknown = [s for s in shots if s not in by_spec]
            if unknown:
                raise ValueError(f"not shots of this act: {unknown}; its shots: {sorted(by_spec)}")
            link.project.reorder_shots(found["id"], [by_spec[s] for s in shots])
            row = next(
                r
                for r in act_ops.act_table(folder, target_of("final"))
                if r["act_id"] == found["id"]
            )
            return ActInfo(**row)

    @tool()
    def remove_shot(
        project: Annotated[str, Field(description="A project id.")],
        film: FilmArg,
        act: ActArg,
        shot_id: ShotArg,
    ) -> ActInfo:
        """Delete one shot (camera angle) from an act. The act becomes stale. Cannot be undone."""
        with fixable():
            folder, link = with_film(film, project)
            found = act_ops.find_act(folder, act)
            docs = {
                s["spec"]["id"]: s["id"] for s in link.project.list_shots(link.film_id, found["id"])
            }
            if shot_id not in docs:
                raise ValueError(f"{shot_id} is not a shot of this act; its shots: {sorted(docs)}")
            link.project.remove_shot(found["id"], docs[shot_id])
            link.pull()
            row = next(
                r
                for r in act_ops.act_table(folder, target_of("final"))
                if r["act_id"] == found["id"]
            )
            return ActInfo(**row)

    @tool()
    async def render_act(
        ctx: Context,
        project: Annotated[str, Field(description="A project id.")],
        film: FilmArg,
        act: ActArg,
        quality: QualityArg = "final",
        force: Annotated[bool, Field(description="Render even if the act is up to date.")] = False,
    ) -> ActRendered:
        """Render one act: every shot in cut order, joined into the act's video. Does nothing
        (rendered false) when the act is up to date, unless force. The shots are checked first;
        a mistake is refused with what to fix. About 0.25 s per final frame, so a 10 s act of
        three shots takes a minute or two."""
        with fixable():
            folder = ws.open_film(film, project)
            result = await with_progress(
                ctx,
                lambda say: act_ops.render_act(
                    folder,
                    act,
                    target_of(quality),
                    shots_renderer(),
                    cfg,
                    force=force,
                    progress=say,
                ),
            )
            return ActRendered(
                act_id=result["act_id"],
                title=result["title"],
                rendered=result["rendered"],
                shots=result["shots"],
                video_path=result.get("video_path"),
            )

    @tool()
    async def export_movie(
        ctx: Context,
        project: Annotated[str, Field(description="A project id.")],
        film: FilmArg,
        quality: QualityArg = "final",
        transition: Annotated[
            Literal["cut", "crossfade"], Field(description="How acts join (crossfade is 0.5 s).")
        ] = "cut",
        start_title: Annotated[
            str | None, Field(max_length=120, description="A title card first.")
        ] = None,
        end_title: Annotated[
            str | None, Field(max_length=120, description="A card at the end.")
        ] = None,
        force: Annotated[bool, Field(description="Render every act again.")] = False,
    ) -> MovieResult:
        """Export all acts as one movie: render the acts that need it (stale; the others are
        reused), join the act videos in the acts' order and write edit/final.mp4, then check it:
        size, one video and one audio stream, the length and the loudness (-14 LUFS, corrected
        with one gain). rendered_acts says what was redone. Nothing is baked before this: edit any
        spec, run it again, and only the changed acts render."""
        with fixable():
            folder = ws.open_film(film, project)
            result = await with_progress(
                ctx,
                lambda say: act_ops.export_movie(
                    folder,
                    target_of(quality),
                    shots_renderer(),
                    cfg,
                    transition=transition,
                    start_title=start_title,
                    end_title=end_title,
                    force=force,
                    progress=say,
                    progress_pct=lambda p: say(f"encoding {p}%"),
                ),
            )
            return MovieResult(
                final_path=result["path"],
                quality=result["quality"],
                width=result["width"],
                height=result["height"],
                duration_s=result["duration_s"],
                expected_duration_s=result["expected_duration_s"],
                integrated_lufs=result["integrated_lufs"],
                checks_passed=result["checks_passed"],
                problems=result["problems"],
                rendered_acts=result["rendered_acts"],
                reused_acts=result["reused_acts"],
                act_order=result["act_order"],
            )

    @tool()
    def clear_renders(
        project: Annotated[str, Field(description="A project id.")], film: FilmArg
    ) -> ActsDescription:
        """Delete every render of the film (act videos, shot videos, the movie). The specs stay:
        export_movie makes all of it again from them, the same film. Use it to free disk space
        or to prove nothing is baked in."""
        with fixable():
            folder = ws.open_film(film, project)
            act_ops.clear_renders(folder)
            rows = act_ops.act_table(folder, target_of("final"))
            return ActsDescription(
                project=project,
                film=film,
                quality="final",
                acts=_acts_info(rows),
                stale_acts=[r["title"] for r in rows if r["stale"]],
            )

    return server


def main() -> None:
    create_server().run()  # stdio


if __name__ == "__main__":
    main()
