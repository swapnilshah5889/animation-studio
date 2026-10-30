"""What every stage is handed: the services (model, tools, memory, log) and the run's state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from director import state as st
from director.chat import ChatFn
from director.config import LoopLimits
from director.hub import ToolDispatcher, call_data
from director.log import EventFn, null_log
from director.memory import MemoryGuard
from director.plans import Capabilities
from studio_core.project import Project

# Tools that take no film argument (find_sfx searches the shared library; check_safety, given only
# `text`, would refuse a lone `film`).
TEXT_ONLY_TOOLS = ("find_sfx", "check_safety")


class StageFailed(RuntimeError):
    """The stage cannot go on without the owner (message says why). State records it as failed."""


class PauseForApproval(Exception):
    """Raised inside a stage when it reaches a checkpoint that needs the owner (first_shot)."""

    def __init__(self, checkpoint: str) -> None:
        super().__init__(checkpoint)
        self.checkpoint = checkpoint


@dataclass
class Deps:
    chat: ChatFn
    hub: ToolDispatcher
    guard: MemoryGuard | None = None
    limits: LoopLimits = field(default_factory=LoopLimits)
    on_event: EventFn = null_log
    auto: bool = False  # every approval checkpoint approves itself
    quality: str = "final"  # render quality for shots and the film: preview | final
    clock: Callable[[], float] | None = None
    # Project films (D-094): the project (for code-side bookkeeping such as adding library items to
    # the film) and a function that brings the derived working folder up to date with the store.
    project: Project | None = None
    refresh: Callable[[], None] | None = None


@dataclass
class StageCtx:
    state: st.DirectorState
    film: Path
    deps: Deps
    stage: str

    @property
    def slug(self) -> str:
        return self.state.film

    @property
    def me(self) -> st.StageState:
        return self.state.stage(self.stage)

    def save(self) -> None:
        st.save(self.film, self.state)

    def note(self, msg: str) -> None:
        self.deps.on_event({"kind": "stage", "stage": self.stage, "msg": msg})

    def film_args(self) -> dict[str, Any]:
        """The arguments that say which film a tool works on: `film`, and `project` for a film of
        a project (the servers then keep its specs, art and recordings in the project)."""
        return {
            "film": self.slug,
            **({"project": self.state.project} if self.state.project else {}),
        }

    def refresh(self) -> None:
        """Bring the working folder up to date with the project (no-op for an old film folder)."""
        if self.deps.refresh:
            self.deps.refresh()

    async def tool(self, name: str, /, **args: Any) -> dict[str, Any]:
        """A code-driven tool call (film is filled in). Raises ToolRefused on a refusal."""
        if "film" not in args and name not in TEXT_ONLY_TOOLS:
            args = {**self.film_args(), **args}
        res = await call_data_timed(self, name, args)
        return res


async def call_data_timed(ctx: StageCtx, name: str, args: dict[str, Any]) -> dict[str, Any]:
    import time

    t0 = time.monotonic()
    ctx.state.counters.tool_calls += 1
    try:
        return await call_data(
            ctx.deps.hub, name, args, lambda m: ctx.deps.on_event({"kind": "progress", "msg": m})
        )
    finally:
        ctx.state.counters.tool_seconds += time.monotonic() - t0
        ctx.deps.on_event(
            {"kind": "stage", "stage": ctx.stage, "msg": f"{name} {time.monotonic() - t0:.1f}s"}
        )


async def capabilities(ctx: StageCtx) -> tuple[Capabilities, dict[str, Any]]:
    """The capability block (D-065 part 4): ask the tools what exists, plan only from that."""
    film = await ctx.tool("describe_film")
    audio = await ctx.tool("describe_audio")
    caps = Capabilities(
        motions=list(film.get("motions", {})),
        expressions=list(film.get("expressions", [])),
        camera_moves=list(film.get("camera_moves", [])),
        moods=list(audio.get("moods", {})),
    )
    return caps, film
