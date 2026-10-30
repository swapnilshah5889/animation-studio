"""comfy_mcp: the director's art tools over MCP (stdio), task 4.8.

    uv run comfy-mcp                                      # stdio (any MCP client)
    npx @modelcontextprotocol/inspector uv run comfy-mcp  # browse and call the tools

The tools turn words into the two kinds of art a shot needs (Step 4), each through a short
pipeline with a choice in the middle (the owner's eye now, the director's from Step 5):

    design_character → choose_design → build_puppet → preview_puppet
    generate_background → choose_background → split_depth_layers → preview_background

describe_art shows where every character and place stands, with its next step. The animation
server (synfig_mcp) uses the results by id: add_character places a built puppet, create_scene
and add_parallax_background use a layered background.

Same conventions as synfig_mcp and audio_mcp (D-034, D-046): docstrings written for the model,
validated arguments, structured results with absolute paths inside the film folder, and refused
requests raised as ToolError with a message saying what to fix. New here (D-056): art jobs take
minutes and need the GPU, so they run one at a time (ComfyUI holds one large model at a time) in
a worker thread, and send MCP progress notifications (elapsed seconds and the latest news, at
least every HEARTBEAT_S) so a client can tell a long job from a hung one. The previews render
with Synfig on the CPU, so they don't wait for art jobs; each has its own lock, because each
replaces one test shot.
"""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from studio_core import shot_spec
from studio_core.comfy_runs import film_style
from studio_core.config import load_config
from studio_core.models import load_manifest
from studio_core.place.design import background_dir, load_plates
from studio_core.place.design import check_request as check_place_request
from studio_core.place.design import choose_background as run_choose_background
from studio_core.place.design import design_dir as place_design_dir
from studio_core.place.design import generate_background as run_generate
from studio_core.place.layers import split_depth_layers as run_split
from studio_core.preview.background import preview_background as run_preview_background
from studio_core.preview.puppet import LINE
from studio_core.preview.puppet import preview_puppet as run_preview_puppet
from studio_core.puppet.build import build_puppet as run_build
from studio_core.puppet.design import check_request as check_design_request
from studio_core.puppet.design import choose_design as run_choose_design
from studio_core.puppet.design import design_character as run_design
from studio_core.puppet.design import design_dir, load_candidates
from studio_core.scene import CAMERA_MOVES
from studio_core.workspace import Workspace

T = TypeVar("T")
HEARTBEAT_S = 15.0  # a long job reports progress at least this often
SIZES = {"preview": (640, 360), "final": (1920, 1080)}
ID = r"^[a-z][a-z0-9_]{0,39}$"

FilmArg = Annotated[
    str,
    Field(
        description="Film name: a folder under films/ (e.g. 'step4-demo'), or with `project` "
        "the film's name in that project."
    ),
]
ProjectArg = Annotated[
    str | None,
    Field(
        description="Project id, for a film of a project (edit_mcp describe_project lists them). "
        "Omit for an old film folder under films/."
    ),
]
CharArg = Annotated[str, Field(pattern=ID, description="Character id, e.g. 'kit'.")]
PlaceArg = Annotated[str, Field(pattern=ID, description="Background (place) id, e.g. 'meadow'.")]
CandidateArg = Annotated[
    str, Field(pattern=r"^c[0-9]{1,3}$", description="A candidate id from its list, e.g. 'c3'.")
]
Count = Annotated[int, Field(ge=1, le=8, description="How many candidates to draw this round.")]
Seed = Annotated[
    int | None, Field(ge=0, description="First seed (then +1 each); omit for a random one.")
]
Quality = Annotated[
    Literal["preview", "final"], Field(description="preview = 640x360 (fast), final = 1920x1080.")
]
Move = Literal[tuple(CAMERA_MOVES)]  # type: ignore[valid-type]

INSTRUCTIONS = """\
Art tools for a children's cut-out film: words in, a rigged puppet or a parallax background out.
Art jobs take minutes (each tool says how long) and run one at a time.

- Characters: design_character draws candidate sheets of a described character (standing
  front-on and turned three-quarters) and checks each. Look at them and choose_design one;
  build_puppet cuts it into a rigged puppet (bones, parts, both views, a faceless head whose
  face is drawn by code). preview_puppet renders it waving, blinking and talking beside Pip,
  the reference puppet. Then add_character (animation server) can place it in shots.
- Places: generate_background paints candidate drafts of a described place. choose_background
  finishes one into a wide plate with room to pan, split_depth_layers cuts it into parallax
  layers by depth, and preview_background pans across it and checks that no hole shows. Then
  create_scene and add_parallax_background (animation server) can use it.
- describe_art shows the film's style and, for every character and place, how far it got and
  its next step. Call it first.

Candidate ids are c1, c2, ... per character or place; another round adds to the list.

Films of a project: pass `project` with the film's name. The project keeps a library of characters
and places that all its films share (describe_art lists it: reuse before drawing anew). A puppet
built by build_puppet and a background layered by split_depth_layers are published to the library
as a new version and the film uses it; earlier versions never change, so finished films keep
rendering the same.
Everything must suit young children: descriptions that don't are refused with the reason.
Describe looks in plain words, never by a studio's or an artist's name.
"""


# --------------------------------------------------------------------------- results


class StyleInfo(BaseModel):
    id: str
    label: str
    commercial: str = Field(description="yes / no / unclear: may the art be used commercially.")


class CandidateOut(BaseModel):
    candidate_id: str
    description: str
    seed: int
    ok: bool = Field(description="The automatic checks passed. The final word is a look.")
    problems: list[str]
    image_path: str = Field(description="The sheet (characters) or the draft (places).")
    plate_path: str | None = Field(default=None, description="Places: the finished plate.")
    seconds: float | None = None


class CharacterArt(BaseModel):
    id: str
    name: str | None
    candidates: list[CandidateOut]
    chosen: str | None
    rig_path: str | None
    views: list[str] = Field(description="The rig's views; empty until built.")
    built_from: str | None = Field(description="The candidate the puppet was cut from.")
    views_consistent: bool | None
    has_voice: bool = Field(description="Cast with audio_mcp set_voice; preview_puppet needs it.")
    next_step: str


class LayerOut(BaseModel):
    name: str
    parallax: float = Field(description="1 moves with the ground; smaller is farther away.")
    in_front: bool = Field(description="Drawn in front of the characters.")
    image_path: str


class BackgroundArt(BaseModel):
    id: str
    drafts: list[CandidateOut]
    chosen: str | None
    plate_path: str | None
    layers_path: str | None
    layers: list[LayerOut]
    next_step: str


class ArtDescription(BaseModel):
    film: str
    style: str = Field(description="The film's art style; every character and place uses it.")
    style_locked: bool = Field(description="Fixed in film.json; otherwise the machine default.")
    styles: list[StyleInfo]
    characters: list[CharacterArt]
    backgrounds: list[BackgroundArt]
    library: dict[str, list[str]] | None = Field(
        default=None,
        description="With a project: its whole library (characters, places, films), including "
        "what this film does not use yet. Reuse a character or place before drawing a new one.",
    )


class DesignResult(BaseModel):
    character_id: str
    style: str
    candidates: list[CandidateOut] = Field(description="This round's candidates.")
    all_candidates: list[str]
    note: str


class ChosenDesign(BaseModel):
    character_id: str
    candidate_id: str
    image_path: str
    ok: bool
    problems: list[str]
    note: str


class ViewBuilt(BaseModel):
    view: str
    bones: list[str]
    parts: int
    limbs_ok: bool = Field(description="Every limb part lies along its bone.")
    loose_limbs: list[str] = Field(description="Limbs whose part strays from its bone.")
    eyes_found: list[str] = Field(description="Eyes found on the drawing (and painted out).")
    hidden_limbs: list[str] = Field(description="Limbs the drawing hides, completed by code.")
    poses_image: str = Field(description="The part cut out in a few test poses: look at it.")


class PuppetResult(BaseModel):
    character_id: str
    name: str
    candidate: str
    rig_path: str
    views: list[ViewBuilt]
    three_quarter_from: str = Field(description="How the three-quarter view was drawn.")
    views_consistent: bool
    consistency_problems: list[str]
    report_path: str
    seconds: float
    note: str
    library_version: int | None = Field(
        default=None,
        description="With a project: the library version published (and now used by the film).",
    )


class KeyFrame(BaseModel):
    label: str
    frame: int


class PuppetPreviewResult(BaseModel):
    character_id: str
    shot_id: str
    video_path: str
    contact_sheet_path: str = Field(description="Key frames with face close-ups: look at it.")
    shot_dir: str
    view: str
    facing: str
    scale: float
    duration_s: float
    line_id: str
    key_frames: list[KeyFrame]
    warnings: list[str]
    seconds: float
    note: str


class DraftsResult(BaseModel):
    background_id: str
    style: str
    drafts: list[CandidateOut] = Field(description="This round's drafts.")
    all_drafts: list[str]
    note: str


class PlateResult(BaseModel):
    background_id: str
    candidate_id: str
    plate_path: str
    ok: bool
    problems: list[str]
    seconds: float
    note: str


class LayersResult(BaseModel):
    background_id: str
    layers_path: str
    layers: list[LayerOut]
    filled: list[str] = Field(description="Layers repainted behind nearer ones, for the pan.")
    bands_image: str = Field(description="The plate tinted by layer: look at it.")
    depth_image: str
    seconds: float
    note: str
    library_version: int | None = Field(
        default=None,
        description="With a project: the library version published (and now used by the film).",
    )


class HoleOut(BaseModel):
    frame: int
    pixels: int


class BackgroundPreviewResult(BaseModel):
    background_id: str
    ok: bool = Field(description="No hole and no layer edge showed during the move.")
    shot_id: str
    video_path: str
    contact_sheet_path: str = Field(description="Five frames of the move: look at it.")
    shot_dir: str
    move: str
    duration_s: float
    character_id: str | None
    frames_checked: int
    holes: list[HoleOut]
    verdicts: list[str]
    layer_room: list[str] = Field(description="How much further each layer could pan.")
    warnings: list[str]
    seconds: float


# --------------------------------------------------------------------------- reading the film


def _folders(parent: Path, markers: tuple[str, ...]) -> list[str]:
    """Sub-folders holding any of `markers` (probe copies from a preview are left out)."""
    if not parent.is_dir():
        return []
    return sorted(
        p.name
        for p in parent.iterdir()
        if p.is_dir() and not p.name.endswith("_probe") and any((p / m).exists() for m in markers)
    )


def _candidate(folder: Path, c: dict[str, Any], image_key: str) -> CandidateOut:
    return CandidateOut(
        candidate_id=c["id"],
        description=c["description"],
        seed=c["seed"],
        ok=c["ok"],
        problems=c["problems"],
        image_path=str(folder / c[image_key]),
        plate_path=str(folder / c["plate"]) if c.get("plate") else None,
        seconds=c.get("seconds"),
    )


def _layers(layers_file: Path) -> list[LayerOut]:
    data = json.loads(layers_file.read_text())
    return [
        LayerOut(
            name=layer["name"],
            parallax=layer["parallax"],
            in_front=layer.get("in_front", False),
            image_path=str(layers_file.parent / layer["file"]),
        )
        for layer in data["layers"]
    ]


def character_art(film: shot_spec.FilmFolder, cid: str) -> CharacterArt:
    folder = film.root / "characters" / cid
    data = load_candidates(film.root, cid)
    candidates = (
        [_candidate(design_dir(film.root, cid), c, "sheet") for c in data["candidates"]]
        if data
        else []
    )
    chosen = data.get("chosen") if data else None
    rig_file = film.rig_file(cid)
    rig = json.loads(rig_file.read_text()) if rig_file.is_file() else None
    report_file = folder / "build" / "report.json"
    report = json.loads(report_file.read_text()) if report_file.is_file() else {}
    has_voice = (folder / "voice.json").is_file()
    built_from = report.get("candidate")
    if rig is None and not candidates:
        step = "design_character"
    elif rig is None and chosen is None:
        step = "look at the sheets, then choose_design"
    elif rig is not None and data is None:
        step = "ready (a hand-made puppet): add_character"
    elif chosen is None:
        step = "choose_design"
    elif rig is None or built_from != chosen:
        step = f"build_puppet (from {chosen})"
    elif not has_voice:
        step = "ready: add_character; cast a voice (audio_mcp set_voice) to preview_puppet"
    else:
        step = "ready: preview_puppet to check it, add_character to use it"
    return CharacterArt(
        id=cid,
        name=rig.get("name") if rig else None,
        candidates=candidates,
        chosen=chosen,
        rig_path=str(rig_file) if rig else None,
        views=list(rig["views"]) if rig else [],
        built_from=built_from,
        views_consistent=report.get("consistency", {}).get("ok"),
        has_voice=has_voice,
        next_step=step,
    )


def background_art(film: shot_spec.FilmFolder, bid: str) -> BackgroundArt:
    folder = background_dir(film.root, bid)
    data = load_plates(film.root, bid)
    drafts = (
        [_candidate(place_design_dir(film.root, bid), c, "draft") for c in data["candidates"]]
        if data
        else []
    )
    chosen = data.get("chosen") if data else None
    plate, layers_file = folder / "plate.png", film.background_file(bid)
    has_plate, has_layers = plate.is_file(), layers_file.is_file()
    stale = has_plate and has_layers and layers_file.stat().st_mtime < plate.stat().st_mtime
    if has_layers and data is None:
        step = "ready (a hand-made background): create_scene / add_parallax_background"
    elif not drafts:
        step = "generate_background"
    elif chosen is None:
        step = "look at the drafts, then choose_background"
    elif not has_plate:
        step = f"choose_background (finish {chosen} into the plate)"
    elif not has_layers or stale:
        step = "split_depth_layers"
    else:
        step = "ready: preview_background to check a pan, add_parallax_background to use it"
    return BackgroundArt(
        id=bid,
        drafts=drafts,
        chosen=chosen,
        plate_path=str(plate) if has_plate else None,
        layers_path=str(layers_file) if has_layers else None,
        layers=_layers(layers_file) if has_layers else [],
        next_step=step,
    )


def view_built(film_root: Path, cid: str, view: str, rig_view: dict, report: dict) -> ViewBuilt:
    limbs = report.get("limbs", {})
    return ViewBuilt(
        view=view,
        bones=list(rig_view["bones"]),
        parts=len(rig_view["parts"]),
        limbs_ok=report.get("limbs_ok", True),
        loose_limbs=sorted(name for name, limb in limbs.items() if not limb.get("ok", True)),
        eyes_found=report.get("face", {}).get("eyes_found", []),
        hidden_limbs=sorted(report.get("hidden_limbs", {})),
        poses_image=str(film_root / "characters" / cid / "build" / view / "poses.png"),
    )


def progress_news(made: Any, done: str, doing: str, k: int, n: int) -> str:
    """'c4 drawn (1/3): ok; drawing sheet 2 of 3'. Between candidates the heartbeat repeats the
    latest news, so it says what is being made now, not only what was made last."""
    state = "ok" if made.ok else "; ".join(made.problems)
    after = f"; {doing} {k + 1} of {n}" if k < n else ""
    return f"{made.id} {done} ({k}/{n}): {state}{after}"


# --------------------------------------------------------------------------- the server


@contextmanager
def fixable() -> Iterator[None]:
    """Turn our validation errors into ToolErrors the model can read and act on. Every refusal
    in studio_core is a ValueError (DesignError, BuildError, PlaceError, PreviewError, SpecError,
    ...); ComfyUI, Synfig and the GPU guard raise RuntimeErrors."""
    try:
        yield
    except ToolError:
        raise
    except (ValueError, RuntimeError) as e:
        raise ToolError(str(e)) from None


def create_server(
    films_root: Path | None = None, *, workspace: Workspace | None = None
) -> MCPServer:
    """The server, with every tool registered."""
    cfg = load_config()
    ws = workspace or Workspace.from_config(cfg, films_root=films_root)
    server = MCPServer(
        "comfy_mcp",
        title="Animation studio: art (character puppets and parallax backgrounds)",
        instructions=INSTRUCTIONS,
        version="0.1.0",
    )
    # One art job at a time on the GPU; one preview per test shot.
    locks = {"art": anyio.Lock(), "puppet preview": anyio.Lock(), "place preview": anyio.Lock()}

    def tool(name: str | None = None) -> Any:
        def register(fn: Any) -> Any:
            server.add_tool(fn, name=name, description=inspect.cleandoc(fn.__doc__ or ""))
            return fn

        return register

    def open_film(
        film: str, project: str | None = None, act: str | None = None
    ) -> shot_spec.FilmFolder:
        return ws.open_film(film, project, act=act)

    def library_of(project: str | None) -> dict[str, list[str]] | None:
        if project is None:
            return None
        proj = ws.open_project(project)
        return {
            "characters": [c["slug"] for c in proj.list_characters()],
            "places": [b["slug"] for b in proj.list_backgrounds()],
            "films": [x["slug"] for x in proj.list_films()],
        }

    async def to_library(f: shot_spec.FilmFolder, kind: str, slug: str) -> int | None:
        """A project film: publish what was just built as a new version in the project library
        (nothing changed = no new version) and let the film use it. None for an old film."""
        if f.link is None:
            return None
        publish = f.link.publish_character if kind == "character" else f.link.publish_background
        return (await anyio.to_thread.run_sync(partial(publish, slug)))["version"]

    async def job(
        ctx: Context, lock: str, label: str, work: Callable[[Callable[[str], None]], T]
    ) -> T:
        """Run `work(say)` in a worker thread under one of the locks, reporting progress: the
        elapsed seconds and the latest news (`say` from the worker), every HEARTBEAT_S at least.
        A client that sent no progress token gets nothing; the job runs the same."""
        t0, news = time.monotonic(), [label]

        async def report() -> None:
            elapsed = time.monotonic() - t0
            with suppress(Exception):  # a client that went away mustn't fail the job
                await ctx.report_progress(elapsed, None, f"{news[-1]} ({elapsed:.0f} s)")

        def say(message: str) -> None:  # called from the worker thread
            news.append(message)
            anyio.from_thread.run(report)

        async def heartbeat() -> None:
            while True:
                await anyio.sleep(HEARTBEAT_S)
                await report()

        result: T | None = None
        error: Exception | None = None
        async with anyio.create_task_group() as tg:
            tg.start_soon(heartbeat)
            if locks[lock].locked():
                news.append(f"waiting for the running {lock} job")
                await report()
            try:
                async with locks[lock]:
                    news.append(label)
                    result = await anyio.to_thread.run_sync(partial(work, say))
            except Exception as e:  # re-raised below, so it isn't wrapped in an ExceptionGroup
                error = e
            tg.cancel_scope.cancel()
        if error is not None:
            raise error
        return result  # type: ignore[return-value]

    @tool()
    def describe_art(film: FilmArg, project: ProjectArg = None) -> ArtDescription:
        """The film's art: its style (and the styles there are), every character (design
        candidates with their checks, the chosen one, the built rig's views) and every place
        (drafts, the chosen one, the plate, the parallax layers), each with its next step.
        Call this first."""
        with fixable():
            f = open_film(film, project)
            manifest = load_manifest()
            film_json = f.root / "film.json"
            locked = film_json.is_file() and bool(json.loads(film_json.read_text()).get("style"))
            chars = _folders(f.root / "characters", ("rig.json", "design/candidates.json"))
            places = _folders(
                f.root / "backgrounds", ("layers.json", "plate.png", "design/plates.json")
            )
            return ArtDescription(
                film=film,
                style=film_style(f.root, cfg),
                style_locked=locked,
                styles=[
                    StyleInfo(id=s.id, label=s.label, commercial=manifest.style_commercial(s.id))
                    for s in manifest.styles.values()
                ],
                characters=[character_art(f, cid) for cid in chars],
                backgrounds=[background_art(f, bid) for bid in places],
                library=library_of(project),
            )

    @tool()
    async def design_character(
        ctx: Context,
        film: FilmArg,
        character_id: CharArg,
        description: Annotated[
            str,
            Field(
                min_length=3,
                max_length=300,
                description="What it looks like: kind, colours, clothes, e.g. 'a cheerful young "
                "fox with a green scarf'. Leave out the pose and the face (code draws both).",
            ),
        ],
        n: Count = 4,
        seed: Seed = None,
        project: ProjectArg = None,
    ) -> DesignResult:
        """Draw `n` candidate sheets of a described character in the film's style, each with the
        figure standing front-on and turned three-quarters in the rig's pose (about 4 min per
        candidate: 4 take about 16 min). Each is checked: ok, or the problems (a missing limb,
        clutter, a figure off its skeleton). Look at the sheets, then choose_design one.
        Another round adds candidates to the list, with the same or a new description."""
        with fixable():
            f = open_film(film, project)
            if problems := check_design_request(character_id, description, n):
                raise ToolError("; ".join(problems))
            if f.rig_file(character_id).is_file() and load_candidates(f.root, character_id) is None:
                raise ToolError(f"{character_id!r} is a hand-made puppet; design under a new id")

            def work(say: Callable[[str], None]) -> list:
                finished: list[Any] = []

                def done(c: Any) -> None:
                    finished.append(c)
                    say(progress_news(c, "drawn", "drawing sheet", len(finished), n))

                return run_design(
                    f.root, character_id, description, n=n, seed=seed, on_candidate=done
                )

            made = await job(ctx, "art", f"drawing {n} sheets of {character_id}", work)
            data = load_candidates(f.root, character_id) or {}
            folder = design_dir(f.root, character_id)
            return DesignResult(
                character_id=character_id,
                style=data.get("style", ""),
                candidates=[_candidate(folder, asdict(c), "sheet") for c in made],
                all_candidates=[c["id"] for c in data.get("candidates", [])],
                note="Look at the sheets (image_path), then choose_design one.",
            )

    @tool()
    def choose_design(
        film: FilmArg, character_id: CharArg, candidate_id: CandidateArg, project: ProjectArg = None
    ) -> ChosenDesign:
        """Choose the candidate sheet the puppet is built from. A candidate whose checks failed
        can still be chosen if it looks right. Then build_puppet."""
        with fixable():
            f = open_film(film, project)
            sheet = run_choose_design(f.root, character_id, candidate_id)
            data = load_candidates(f.root, character_id) or {}
            c = next(c for c in data["candidates"] if c["id"] == candidate_id)
            return ChosenDesign(
                character_id=character_id,
                candidate_id=candidate_id,
                image_path=str(sheet),
                ok=c["ok"],
                problems=c["problems"],
                note="build_puppet next (about 8 min the first time, under a minute after).",
            )

    @tool()
    async def build_puppet(
        ctx: Context,
        film: FilmArg,
        character_id: CharArg,
        name: Annotated[
            str | None,
            Field(
                pattern=r"^[A-Za-z][A-Za-z' -]{0,39}$",
                description="The name shown for it, e.g. 'Kit'; defaults to the id, capitalised.",
            ),
        ] = None,
        project: ProjectArg = None,
    ) -> PuppetResult:
        """Cut the chosen design into a rigged puppet: a front view and a three-quarter view
        (redrawn from the front so the two match), each with bones, parts and a faceless head
        whose eyes, brows and mouth code draws. About 8 min the first time (the three-quarter
        redraw), under a minute when rebuilt. Rebuilding replaces the parts and the rig. Look
        at each view's poses_image; then preview_puppet."""
        with fixable():
            f = open_film(film, project)
            t0 = time.monotonic()
            built = await job(
                ctx,
                "art",
                f"building {character_id}",
                lambda say: run_build(f.root, character_id, name=name),
            )
            version = await to_library(f, "character", character_id)
            report = built.report
            consistency = report.get("consistency", {})
            source = report.get("three_quarter_source", {})
            return PuppetResult(
                character_id=character_id,
                name=built.rig["name"],
                candidate=report.get("candidate", ""),
                rig_path=str(built.rig_path),
                views=[
                    view_built(f.root, character_id, view, rig_view, report["views"].get(view, {}))
                    for view, rig_view in built.rig["views"].items()
                ],
                three_quarter_from=source.get("method", "the sheet"),
                views_consistent=consistency.get("ok", True),
                consistency_problems=consistency.get("problems", []),
                report_path=str(f.root / "characters" / character_id / "build" / "report.json"),
                seconds=round(time.monotonic() - t0, 1),
                note="Look at each view's poses_image, then preview_puppet.",
                library_version=version,
            )

    @tool()
    async def preview_puppet(
        ctx: Context,
        film: FilmArg,
        character_id: CharArg,
        view: Annotated[
            Literal["front", "three_quarter"],
            Field(description="three_quarter turns it toward Pip."),
        ] = "front",
        line: Annotated[
            str, Field(min_length=1, max_length=200, description="What it says, in its voice.")
        ] = LINE,
        background_id: PlaceArg = "meadow",
        quality: Quality = "preview",
        project: ProjectArg = None,
    ) -> PuppetPreviewResult:
        """Render a short test shot of a built puppet beside Pip (the reference puppet, at the
        same standing height): it rests, waves toward Pip, blinks, and says `line` lip-synced
        (about 1-2 min at preview quality). The character needs a voice first (audio_mcp
        set_voice). The test shot (s00_sh01) is replaced by every preview; the film gains Pip and
        the placeholder meadow if it lacks them. Look at the contact sheet."""
        with fixable():
            f = open_film(film, project)
            preview = await job(
                ctx,
                "puppet preview",
                f"previewing {character_id}",
                lambda say: run_preview_puppet(
                    f,
                    character_id,
                    view=view,
                    background=background_id,
                    line=line,
                    size=SIZES[quality],
                    cfg=cfg,
                    log=say,
                ),
            )
            return PuppetPreviewResult(
                character_id=character_id,
                shot_id=preview.shot_id,
                video_path=str(preview.video),
                contact_sheet_path=str(preview.contact_sheet),
                shot_dir=str(preview.shot_dir),
                view=preview.view,
                facing=preview.facing,
                scale=preview.scale,
                duration_s=preview.duration_s,
                line_id=preview.line_id,
                key_frames=[KeyFrame(label=k, frame=n) for k, n in preview.key_frames],
                warnings=preview.warnings,
                seconds=round(preview.seconds, 1),
                note=f"{preview.shot_id} is a test shot, replaced by the next preview.",
            )

    @tool()
    async def generate_background(
        ctx: Context,
        film: FilmArg,
        background_id: PlaceArg,
        description: Annotated[
            str,
            Field(
                min_length=3,
                max_length=300,
                description="The place, e.g. 'a sunny meadow at the edge of a forest with a "
                "small stream'. No characters or animals: they are separate puppets.",
            ),
        ],
        n: Count = 4,
        seed: Seed = None,
        project: ProjectArg = None,
    ) -> DraftsResult:
        """Paint `n` candidate drafts of a described place in the film's style (about 2 min
        each), wide enough to pan across, with things in the middle and far distance and an
        open floor along the bottom for characters to stand on. Each is checked: ok, or the
        problems (a busy or uneven floor). Look at the drafts, then choose_background one.
        Another round adds drafts to the list."""
        with fixable():
            f = open_film(film, project)
            if problems := check_place_request(background_id, description, n):
                raise ToolError("; ".join(problems))

            def work(say: Callable[[str], None]) -> list:
                finished: list[Any] = []

                def done(d: Any) -> None:
                    finished.append(d)
                    say(progress_news(d, "painted", "painting draft", len(finished), n))

                return run_generate(
                    f.root, background_id, description, n=n, seed=seed, on_draft=done
                )

            made = await job(ctx, "art", f"painting {n} drafts of {background_id}", work)
            data = load_plates(f.root, background_id) or {}
            folder = place_design_dir(f.root, background_id)
            return DraftsResult(
                background_id=background_id,
                style=data.get("style", ""),
                drafts=[_candidate(folder, asdict(d), "draft") for d in made],
                all_drafts=[c["id"] for c in data.get("candidates", [])],
                note="Look at the drafts (image_path), then choose_background one.",
            )

    @tool()
    async def choose_background(
        ctx: Context,
        film: FilmArg,
        background_id: PlaceArg,
        candidate_id: CandidateArg,
        project: ProjectArg = None,
    ) -> PlateResult:
        """Choose a draft and finish it into the background's plate: upscaled to 2880x1080 (the
        frame plus room to pan) and redrawn lightly for crisp detail (about 5-6 min). Choosing
        again replaces the plate. Then split_depth_layers."""
        with fixable():
            f = open_film(film, project)
            t0 = time.monotonic()
            plate = await job(
                ctx,
                "art",
                f"finishing {background_id} {candidate_id}",
                lambda say: run_choose_background(f.root, background_id, candidate_id, cfg=cfg),
            )
            data = load_plates(f.root, background_id) or {}
            c = next(c for c in data["candidates"] if c["id"] == candidate_id)
            return PlateResult(
                background_id=background_id,
                candidate_id=candidate_id,
                plate_path=str(plate),
                ok=c["ok"],
                problems=c["problems"],
                seconds=round(time.monotonic() - t0, 1),
                note="split_depth_layers next.",
            )

    @tool()
    async def split_depth_layers(
        ctx: Context, film: FilmArg, background_id: PlaceArg, project: ProjectArg = None
    ) -> LayersResult:
        """Cut the background's plate into parallax layers by depth (sky, far, middle, ground,
        and a foreground in front of the characters when there is one), repaint what a pan
        reveals behind each nearer layer, and write layers.json (about 8-14 min). Look at
        bands_image; then preview_background, and use it with add_parallax_background."""
        with fixable():
            f = open_film(film, project)
            t0 = time.monotonic()
            path = await job(
                ctx,
                "art",
                f"layering {background_id}",
                lambda say: run_split(f.root, background_id, cfg=cfg),
            )
            version = await to_library(f, "background", background_id)
            build = path.parent / "build"
            report_file = build / "layers_report.json"
            report = json.loads(report_file.read_text()) if report_file.is_file() else {}
            return LayersResult(
                background_id=background_id,
                layers_path=str(path),
                layers=_layers(path),
                filled=report.get("filled", []),
                bands_image=str(build / "bands.png"),
                depth_image=str(build / "depth" / "depth.png"),
                seconds=round(time.monotonic() - t0, 1),
                note="preview_background next.",
                library_version=version,
            )

    @tool()
    async def preview_background(
        ctx: Context,
        film: FilmArg,
        background_id: PlaceArg,
        move: Move = "slow_pan_right",
        duration_s: Annotated[
            float, Field(ge=1, le=20, description="The shot's (and the move's) length.")
        ] = 6.0,
        zoom: Annotated[
            float | None, Field(ge=0.5, le=3, description="The camera's starting zoom (1 = none).")
        ] = None,
        character_id: Annotated[
            str | None,
            Field(pattern=ID, description="A built character to stand on the ground, for scale."),
        ] = None,
        quality: Quality = "preview",
        project: ProjectArg = None,
    ) -> BackgroundPreviewResult:
        """Render a test shot of a layered background during a camera move (about 1 min at
        preview quality) and check, frame by frame, that the move never shows a hole or a
        layer's edge: ok, or which frames fail. With character_id, a puppet stands on the
        ground to show the place's scale. The test shot (s00_sh02) is replaced by every
        preview. Look at the contact sheet."""
        with fixable():
            f = open_film(film, project)
            preview = await job(
                ctx,
                "place preview",
                f"panning across {background_id}",
                lambda say: run_preview_background(
                    f,
                    background_id,
                    character=character_id,
                    move=move,
                    zoom=zoom,
                    seconds=duration_s,
                    size=SIZES[quality],
                    cfg=cfg,
                    log=say,
                ),
            )
            return BackgroundPreviewResult(
                background_id=background_id,
                ok=preview.ok,
                shot_id=preview.shot_id,
                video_path=str(preview.video),
                contact_sheet_path=str(preview.contact_sheet),
                shot_dir=str(preview.shot_dir),
                move=preview.move,
                duration_s=preview.seconds_long,
                character_id=preview.character,
                frames_checked=preview.sampled,
                holes=[HoleOut(frame=h.frame, pixels=h.pixels) for h in preview.holes],
                verdicts=preview.verdicts,
                layer_room=preview.layer_table,
                warnings=preview.warnings,
                seconds=round(preview.seconds, 1),
            )

    return server


def main() -> None:
    create_server().run()  # stdio


if __name__ == "__main__":
    main()
