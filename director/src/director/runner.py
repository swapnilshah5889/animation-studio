"""CORE (3/3): the stage state machine around the conversations.

`run_film` is the only entry point. It is resume-aware: it re-checks finished stages against the
film folder, runs the next unfinished one, and stops at each approval checkpoint until the
owner says go.
The rules this file enforces (design §1):

  * a stage is complete only when `checks.stage_complete` says so, never because a stage
    said "done";
  * a failed stage stays failed until the owner retries it (no silent retries);
  * a crash mid-stage (status "running") restarts that stage; tools are idempotent, so
    nothing is replayed;
  * an approval is a pause that survives a restart (state.json), written before the process exits.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from director import state as st
from director.checks import shotplan_of, stage_complete
from director.config import CHECKPOINTS, STAGE_SECONDS, STAGES
from director.context import Deps, PauseForApproval, StageCtx, StageFailed
from director.hub import ToolRefused
from director.memory import MemoryConflict
from director.plans import PlanError
from director.review import write_review
from director.stages import art, audio, finish, shots, story

StageFn = Callable[[StageCtx], Awaitable[None]]
STAGE_FNS: dict[str, StageFn] = {
    "story": story.run,
    "characters": art.run_characters,
    "backgrounds": art.run_backgrounds,
    "audio": audio.run,
    "shots": shots.run,
    "edit": finish.run_edit,
    "qa": finish.run_qa,
}


def reverify(state: st.DirectorState, film: Path) -> None:
    """Resume rule 1: walk the stages from the top; the first finished one whose files no longer
    check out (deleted, edited) and everything after it go back to pending. A crashed `running`
    stage restarts. `failed` and `awaiting_approval` are left for the owner."""
    stale_from = None
    for name in STAGES:
        s = state.stage(name)
        if stale_from is None:
            if s.status == "running":
                s.status = "pending"
            elif s.status in ("complete", "awaiting_approval") and stage_complete(
                name, film, state.target_seconds
            ):
                stale_from, s.status = name, "pending"
        elif s.status in ("complete", "awaiting_approval", "running"):
            s.status = "pending"
        if stale_from is not None and (cp := state.checkpoint_after(name)):
            state.approvals[cp].status = "pending"
    if stale_from in ("story", "characters", "backgrounds", "audio", "shots"):
        state.approvals["first_shot"].status = "pending"  # its shots must be looked at again


async def run_stage(name: str, state: st.DirectorState, film: Path, deps: Deps) -> str:
    """Run one stage. Returns "complete", "awaiting_approval" or "failed"."""
    s = state.stage(name)
    s.status, s.attempts, s.started, s.last_error = "running", s.attempts + 1, st.now(), None
    state.current_stage = name
    st.save(film, state)
    ctx = StageCtx(state, film, deps, name)
    before = state.counters.model_copy()
    t0 = time.monotonic()
    deps.on_event({"kind": "stage", "stage": name, "msg": f"start (attempt {s.attempts})"})
    try:
        if deps.guard:
            async with deps.guard.for_stage(name):
                await _with_budget(STAGE_FNS[name](ctx), name)
        else:
            await _with_budget(STAGE_FNS[name](ctx), name)
        missing = stage_complete(name, film, state.target_seconds)
        if missing:
            raise StageFailed(f"the stage ended but is not complete: {missing}")
        s.status = "complete"
        s.finished = st.now()
        if (cp := state.checkpoint_after(name)) and _needs_owner(state, cp, deps):
            s.status = "awaiting_approval"
            state.approvals[cp].status = "waiting"
            deps.on_event({"kind": "approval", "msg": f"review: {write_review(cp, film, state)}"})
    except PauseForApproval as pause:
        s.status = "awaiting_approval"
        deps.on_event(
            {
                "kind": "approval",
                "msg": f"review: {st.state_dir(film) / 'review' / (pause.checkpoint + '.md')}",
            }
        )
    except (StageFailed, ToolRefused, PlanError, TimeoutError, MemoryConflict) as err:
        s.status, s.last_error = "failed", str(err)
        deps.on_event({"kind": "stage", "stage": name, "msg": f"FAILED: {err}"})
    finally:
        # A stage's share of the run's cost, kept per stage and in the run total.
        st.counters_add(s.counters, st.counters_delta(state.counters, before))
        st.save(film, state)
        deps.on_event(
            {
                "kind": "stage",
                "stage": name,
                "msg": f"{s.status} after {time.monotonic() - t0:.0f}s",
            }
        )
    return s.status


async def _with_budget(work: Awaitable[None], name: str) -> None:
    await asyncio.wait_for(work, STAGE_SECONDS[name])


def _needs_owner(state: st.DirectorState, checkpoint: str, deps: Deps) -> bool:
    ap = state.approvals[checkpoint]
    if ap.status == "approved":
        return False
    if deps.auto or ap.mode == "auto":
        ap.status, ap.at = "approved", st.now()
        return False
    return True


async def run_film(slug: str, deps: Deps, films_root: Path) -> str:
    """Run until the film is finished or something needs the owner. Returns one of
    "finished", "awaiting_approval:<stage>", "failed:<stage>"."""
    film = films_root / slug
    state = st.load(film)
    reverify(state, film)
    st.save(film, state)
    for name in STAGES:
        s = state.stage(name)
        if s.status == "complete":
            continue
        if s.status in ("awaiting_approval", "failed"):
            return f"{s.status}:{name}"
        status = await run_stage(name, state, film, deps)
        if status != "complete":
            return f"{status}:{name}"
    return "finished"


# ---- the owner's side: approve / revise / retry -------------------------------------------------


def approve(state: st.DirectorState, film: Path, name: str) -> None:
    if name not in CHECKPOINTS:
        raise KeyError(f"unknown checkpoint {name!r}; checkpoints: {', '.join(CHECKPOINTS)}")
    state.approvals[name].status, state.approvals[name].at = "approved", st.now()
    stage = state.stage(CHECKPOINTS[name])
    if stage.status == "awaiting_approval":
        stage.status = "pending" if name == "first_shot" else "complete"
    st.save(film, state)


def revise(state: st.DirectorState, film: Path, name: str, note: str) -> None:
    """Ask for a change: the checkpoint's stage runs again with the owner's note in its brief."""
    stage_name = CHECKPOINTS[name]
    stage = state.stage(stage_name)
    stage.revision_notes.append(note)
    stage.status = "pending"
    state.approvals[name].status = "pending"
    owned = {"story": ["story/story.json"], "shots": ["story/shotplan.json"]}.get(stage_name, [])
    plan = shotplan_of(film) if stage_name == "shots" else None
    for rel in owned:
        (film / rel).unlink(missing_ok=True)
    for planned in (plan or {"shots": []})["shots"]:  # the old renders no longer match the new plan
        (film / "shots" / planned["id"] / "shot.mp4").unlink(missing_ok=True)
        stage.per_item.pop(planned["id"], None)
    st.save(film, state)


def retry(state: st.DirectorState, film: Path, stage: str | None = None) -> None:
    """Reset a failed stage (and its attempt count) so run_film tries it again."""
    for name in [stage] if stage else list(STAGES):
        s = state.stage(name)
        if s.status == "failed":
            s.status, s.attempts, s.last_error = "pending", 0, None
    st.save(film, state)
