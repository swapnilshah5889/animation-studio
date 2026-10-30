"""qa_mcp: the director's eyes over MCP (stdio).

    uv run qa-mcp                                      # stdio (any MCP client)
    npx @modelcontextprotocol/inspector uv run qa-mcp  # browse and call the tools

The tools look at a rendered frame and at text, and say what is wrong. Two layers in every
answer: **code checks are facts** (holes, cropped or missing characters, a black frame, blocklisted
words) and **the vision model is advisory** (`qwen3-vl:8b-instruct`, one call per frame or text,
unloaded afterwards).

Same conventions as the other servers (D-034): docstrings written for the model, validated ids,
structured results, refused requests raised as ToolError with a message saying what to fix, and
slow work in a worker thread with progress notes.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Annotated, Any, TypeVar

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from studio_core import shot_spec
from studio_core.config import load_config
from studio_core.qa import runner
from studio_core.qa.rubric import SAFETY_CATEGORIES
from studio_core.shot import ShotError, load_shot
from studio_core.sif.render import RenderError
from studio_core.workspace import Workspace

T = TypeVar("T")
HEARTBEAT_S = 15.0
FilmArg = Annotated[
    str,
    Field(
        description="Film name: a folder under films/ (e.g. 'step3-demo'), or with `project` "
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
ShotArg = Annotated[str, Field(pattern=r"^s[0-9]{2}_sh[0-9]{2}$", description="Shot id.")]

INSTRUCTIONS = """\
Eyes for the director. They check; they never change the film.

Films of a project: pass `project` with the film's name; shots are read from the project's acts.

- check_frame looks at one rendered frame of a shot against the shot spec (who is in it, the
  expressions, the background, the camera). Code checks are facts (holes, seams, detached pieces,
  a character missing or cropped by the frame, a black frame); the model's matches and problems
  are advice. Fix what the code found first.
- check_safety judges text (a line, a description, a story paragraph) and/or a shot's picture for
  children aged 3-8. When unsure it says ok false with needs_human true: ask the owner.
- check_film runs both over a whole film: up to 3 key frames per shot, every dialogue line and the
  premise. Slow (about 5-10 s per frame, 2-4 s per text), one model at a time.

Needs Ollama running and refuses while ComfyUI is busy.
"""


class CodeFinding(BaseModel):
    kind: str = Field(description="black_frame | missing | cropped | hole | seam | detached")
    detail: str
    character: str = ""


class MatchOut(BaseModel):
    what: str
    ok: bool
    reason: str


class FrameCheck(BaseModel):
    shot_id: str
    time_s: float
    frame_path: str = Field(description="The rendered frame (inside the film folder).")
    ok: bool = Field(description="True only when the code checks are clean AND the model agrees.")
    code_ok: bool
    code_findings: list[CodeFinding] = Field(description="Facts found by code.")
    matches: list[MatchOut] = Field(description="Advisory: character present, expression, place.")
    problems: list[str] = Field(description="Advisory: what the model thinks looks wrong.")
    description: str = Field(description="What the model says it sees.")
    model_seconds: float = Field(description="The whole call, including loading the model.")
    model_load_seconds: float = Field(description="Of which loading the model into memory.")
    model_memory_gb: float | None
    notes: list[str]


class SafetyCheck(BaseModel):
    subject: str = Field(description="What was checked: 'text', 'frame', a dialogue line...")
    ok: bool
    needs_human: bool = Field(description="The model was unsure; the owner should look.")
    categories: list[str] = Field(
        description=f"Rubric categories hit: {', '.join(SAFETY_CATEGORIES)}"
    )
    reasons: list[str]
    blocked_words: list[str]
    model_seconds: float


class SafetyResult(BaseModel):
    text: SafetyCheck | None
    frame: SafetyCheck | None
    frame_path: str | None
    ok: bool
    needs_human: bool


class ShotRow(BaseModel):
    shot_id: str
    ok: bool
    frames: list[FrameCheck]
    dialogue: list[SafetyCheck]


class FilmCheck(BaseModel):
    film: str
    ok: bool
    shots: list[ShotRow]
    premise: SafetyCheck | None = Field(description="Null when film.json has no premise.")
    total_model_seconds: float
    model: str
    model_memory_gb: float | None
    needs_human: bool
    summary: list[str] = Field(description="One line per shot with what to fix.")


@contextmanager
def fixable() -> Iterator[None]:
    """Turn our validation errors into ToolErrors the model can read and act on."""
    try:
        yield
    except ToolError:
        raise
    except (ValueError, RuntimeError, RenderError, ShotError, runner.QAError) as e:
        raise ToolError(str(e)) from None


def _check(r: runner.SafetyReport) -> SafetyCheck:
    return SafetyCheck(**asdict(r))


def create_server(
    films_root: Path | None = None,
    client: runner.VisionClient | None = None,
    *,
    workspace: Workspace | None = None,
) -> MCPServer:
    """The server, with every tool registered. `client` replaces the real model (tests)."""
    cfg = load_config()
    ws = workspace or Workspace.from_config(cfg, films_root=films_root)
    server = MCPServer(
        "qa_mcp",
        title="Animation studio: frame and safety checks",
        instructions=INSTRUCTIONS,
        version="0.1.0",
    )
    lock = anyio.Lock()  # one model at a time, one check at a time

    def tool(name: str | None = None) -> Any:
        def register(fn: Any) -> Any:
            server.add_tool(fn, name=name, description=inspect.cleandoc(fn.__doc__ or ""))
            return fn

        return register

    def open_film(
        film: str, project: str | None = None, act: str | None = None
    ) -> shot_spec.FilmFolder:
        return ws.open_film(film, project, act=act)

    def vision() -> runner.VisionClient:
        return client or runner.OllamaVision(cfg)

    async def job(ctx: Context, label: str, work: Callable[[Callable[[str], None]], T]) -> T:
        """Run `work(say)` in a worker thread, reporting progress every HEARTBEAT_S at least."""
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
            try:
                async with lock:
                    result = await anyio.to_thread.run_sync(partial(work, say))
            except Exception as e:  # re-raised below, not wrapped in an ExceptionGroup
                error = e
            tg.cancel_scope.cancel()
        if error is not None:
            raise error
        return result  # type: ignore[return-value]

    def shot_of(
        film: str, shot_id: str, time_s: float | None = None, project: str | None = None
    ) -> tuple[Path, dict]:
        f = open_film(film, project)
        spec = shot_spec.load(f, shot_id)
        if time_s is not None and not 0 <= time_s < spec["duration_s"]:
            raise ValueError(
                f"time {time_s}s is outside the {spec['duration_s']}s shot; "
                f"use 0 to {spec['duration_s'] - 0.05:.2f}"
            )
        return f.root, spec

    @tool()
    async def check_frame(
        ctx: Context,
        film: FilmArg,
        shot_id: ShotArg,
        time_s: Annotated[float, Field(ge=0, description="Seconds from the start of the shot.")],
        project: ProjectArg = None,
    ) -> FrameCheck:
        """Render the shot at time_s and check the frame against the shot spec (about 15-30 s).
        Code checks first, always: black frame, each character visible and inside the frame, no
        holes, seams or detached pieces. Then one vision-model call that describes the frame and
        judges it against the spec (characters present, expressions plausible, place present)
        and lists visible problems. `ok` is true only when the code checks are clean and the
        model agrees. code_findings are facts, fix them; matches and problems are advice and can
        be wrong (it sometimes calls a pose unreadable or misses a small hole). The model is
        unloaded afterwards. Refused while ComfyUI is busy."""
        with fixable():
            film_dir, _ = shot_of(film, shot_id, time_s, project)

            def work(say: Callable[[str], None]) -> runner.FrameReport:
                return runner.check_frame(film_dir, shot_id, time_s, vision(), cfg=cfg, say=say)

            return FrameCheck(**asdict(await job(ctx, f"checking {shot_id}", work)))

    @tool()
    async def check_safety(
        ctx: Context,
        text: Annotated[
            str | None,
            Field(max_length=4000, description="A line, a description or a story paragraph."),
        ] = None,
        film: FilmArg | None = None,
        shot_id: ShotArg | None = None,
        time_s: Annotated[
            float | None, Field(ge=0, description="Frame time; default the middle of the shot.")
        ] = None,
        project: ProjectArg = None,
    ) -> SafetyResult:
        """Check material for children aged 3-8: text, a shot's picture (give film and shot_id),
        or both. The word blocklist runs first (a fact), then the model judges against a fixed
        rubric (violence, fear, sexual content, hate, adult themes, dangerous behaviour to
        imitate, scary imagery) and returns the categories hit with reasons. Conservative: when
        unsure it returns ok false with needs_human true. Takes 2-8 s per item."""
        with fixable():
            if bool(film) != bool(shot_id):
                raise ValueError("`film` and `shot_id` go together")
            if not text and not film:
                raise ValueError("give `text`, or `film` and `shot_id` for a picture, or both")
            film_dir = spec = None
            if film and shot_id:
                film_dir, spec = shot_of(film, shot_id, time_s, project)
                if time_s is None:
                    time_s = round(spec["duration_s"] / 2, 2)

            def work(say: Callable[[str], None]) -> SafetyResult:
                c = vision()
                try:
                    runner.make_room(cfg, c.model)
                    t_res = f_res = frame = None
                    if text:
                        say("judging the text")
                        t_res = _check(runner.check_text_safety(text, c, subject="text"))
                    if film_dir and shot_id and time_s is not None:
                        say(f"rendering {shot_id}")
                        frame = runner.render_frame(film_dir, shot_id, time_s, cfg)
                        say("judging the picture")
                        f_res = _check(
                            runner.check_text_safety("", c, image=frame, subject="frame")
                        )
                finally:
                    c.unload()
                parts = [r for r in (t_res, f_res) if r]
                return SafetyResult(
                    text=t_res,
                    frame=f_res,
                    frame_path=str(frame) if frame else None,
                    ok=all(r.ok for r in parts),
                    needs_human=any(r.needs_human for r in parts),
                )

            return await job(ctx, "checking safety", work)

    @tool()
    async def check_film(ctx: Context, film: FilmArg, project: ProjectArg = None) -> FilmCheck:
        """Check a whole film, one model call after another: up to 3 key frames per shot (start,
        middle and end of its real action) with check_frame, and every dialogue line and the film
        premise (film.json) with check_safety's text check. Returns a table per shot, whether
        each is ok, and the total model seconds. A film of 5 shots with 4 lines takes about 5
        minutes. Run it before render_shot of the last shot, not after every edit."""
        with fixable():
            f = open_film(film, project)
            shot_ids = f.shots()
            if not shot_ids:
                raise ValueError(f"film {film!r} has no shots yet; create_scene first")

            def work(say: Callable[[str], None]) -> FilmCheck:
                c = vision()
                rows: list[ShotRow] = []
                summary: list[str] = []
                total = 0.0
                try:
                    runner.make_room(cfg, c.model)
                    premise_text, _ = runner.film_texts(f.root, [])
                    premise = None
                    if premise_text:
                        say("judging the premise")
                        r = runner.check_text_safety(premise_text, c, subject="premise")
                        premise, total = _check(r), total + r.model_seconds
                    for sid in shot_ids:
                        spec = load_shot(f.root, sid)
                        frames_, lines = [], []
                        for t in runner.key_times(spec):
                            say(f"{sid} at {t:.1f}s")
                            fr = runner.check_frame(
                                f.root, sid, t, c, cfg=cfg, keep_model=True, room_made=True
                            )
                            frames_.append(FrameCheck(**asdict(fr)))
                            total += fr.model_seconds
                        for label, text in runner.film_texts(f.root, [sid])[1]:
                            say(f"{label}")
                            r = runner.check_text_safety(text, c, subject=label)
                            lines.append(_check(r))
                            total += r.model_seconds
                        ok = all(x.ok for x in frames_) and all(x.ok for x in lines)
                        rows.append(ShotRow(shot_id=sid, ok=ok, frames=frames_, dialogue=lines))
                        if not ok:
                            bits = [
                                f"{fc.time_s:.1f}s: "
                                + "; ".join(
                                    [x.detail for x in fc.code_findings]
                                    + fc.problems
                                    + [m.what for m in fc.matches if not m.ok]
                                )
                                for fc in frames_
                                if not fc.ok
                            ] + [
                                f"line {x.subject}: {', '.join(x.categories) or 'unsure'}"
                                for x in lines
                                if not x.ok
                            ]
                            summary.append(f"{sid}: " + " | ".join(bits))
                finally:
                    memory = getattr(c, "memory_gb", None)
                    c.unload()
                all_ok = all(r.ok for r in rows) and (premise is None or premise.ok)
                if premise is not None and not premise.ok:
                    summary.insert(0, f"premise: {', '.join(premise.categories) or 'unsure'}")
                return FilmCheck(
                    film=film,
                    ok=all_ok,
                    shots=rows,
                    premise=premise,
                    total_model_seconds=round(total, 1),
                    model=c.model,
                    model_memory_gb=memory,
                    needs_human=any(x.needs_human for r in rows for x in r.dialogue)
                    or bool(premise and premise.needs_human),
                    summary=summary,
                )

            return await job(ctx, f"checking {film}", work)

    return server


def main() -> None:
    create_server().run()  # stdio


if __name__ == "__main__":
    main()
