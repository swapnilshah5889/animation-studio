"""The director's memory: films/<slug>/director/state.json.

The film folder is the truth about *what exists*; this file only remembers *progress*: which stage
we are in, what the owner approved, how many attempts and model calls it took. It is saved
atomically (write a temp file, rename) after every change so a crash never leaves half a file.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from director.config import CHECKPOINTS, STAGES

Status = Literal["pending", "running", "awaiting_approval", "complete", "failed"]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Counters(BaseModel):
    """What a run cost. Step 7 (evals) and Step 9 (training) read it: only ever add to it."""

    model_calls: int = 0
    tool_calls: int = 0
    refusals: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    llm_seconds: float = 0.0
    tool_seconds: float = 0.0


class StageState(BaseModel):
    status: Status = "pending"
    attempts: int = 0
    started: str | None = None
    finished: str | None = None
    last_error: str | None = None
    # Art stages resume per character / place: id -> "built" / "failed" ...
    per_item: dict[str, str] = Field(default_factory=dict)
    # Owner notes from `revise`, appended to the stage's user message on the next run.
    revision_notes: list[str] = Field(default_factory=list)
    counters: Counters = Field(default_factory=Counters)


class Approval(BaseModel):
    mode: Literal["required", "auto"] = "required"
    status: Literal["pending", "waiting", "approved"] = "pending"
    at: str | None = None


class DirectorState(BaseModel):
    schema_version: int = 1
    film: str
    prompt: str
    target_seconds: int = 15
    current_stage: str = "story"
    stages: dict[str, StageState] = Field(default_factory=lambda: {s: StageState() for s in STAGES})
    approvals: dict[str, Approval] = Field(
        default_factory=lambda: {c: Approval() for c in CHECKPOINTS}
    )
    counters: Counters = Field(default_factory=Counters)

    def stage(self, name: str) -> StageState:
        return self.stages[name]

    def checkpoint_after(self, stage: str) -> str | None:
        """The approval checkpoint that follows a whole stage (first_shot is inside shots)."""
        return next((c for c, s in CHECKPOINTS.items() if s == stage and c != "first_shot"), None)

    def first_pending(self) -> str | None:
        return next((s for s in STAGES if self.stages[s].status != "complete"), None)


def state_dir(film_root: Path) -> Path:
    return film_root / "director"


def state_file(film_root: Path) -> Path:
    return state_dir(film_root) / "state.json"


def load(film_root: Path) -> DirectorState:
    return DirectorState.model_validate_json(state_file(film_root).read_text())


def save(film_root: Path, state: DirectorState) -> None:
    path = state_file(film_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.model_dump(), indent=2) + "\n")
    os.replace(tmp, path)  # atomic on one filesystem


def counters_delta(after: Counters, before: Counters) -> Counters:
    """What was spent between two snapshots (a stage's share of the run)."""
    return Counters(**{k: getattr(after, k) - getattr(before, k) for k in Counters.model_fields})


def counters_add(into: Counters, more: Counters) -> None:
    for k in Counters.model_fields:
        setattr(into, k, getattr(into, k) + getattr(more, k))
