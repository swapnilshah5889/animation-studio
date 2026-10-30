"""Names and limits in one place. Every cap the agent loop obeys is here, so it is easy to read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Stage order. The design's seven stages; film.json's own `stages` list has six (no qa).
STAGES = ("story", "characters", "backgrounds", "audio", "shots", "edit", "qa")
StageName = Literal["story", "characters", "backgrounds", "audio", "shots", "edit", "qa"]

# Owner stops. name -> the stage it follows. `first_shot` pauses inside the shots stage.
CHECKPOINTS = {"story": "story", "characters": "characters", "first_shot": "shots", "final": "qa"}

# Project films (D-094) add one stop per act, "act_<scene id>", inside the shots stage.
ACT_CHECKPOINT = "act_"


def act_checkpoint(scene_id: str) -> str:
    return ACT_CHECKPOINT + scene_id


def checkpoint_stage(name: str) -> str | None:
    """The stage a checkpoint belongs to (None = unknown name)."""
    return "shots" if name.startswith(ACT_CHECKPOINT) else CHECKPOINTS.get(name)


MODEL = "qwen3:14b"  # D-024
NUM_CTX = 16384
KEEP_ALIVE = "30m"  # while LLM stages run back to back; art stages unload it (keep_alive 0)

# Shots: seconds each, and the step added after a spoken line so the picture outlasts the voice.
SHOT_SECONDS = (2.0, 8.0)
LINE_TAIL_S = 0.6
LINE_LEAD_S = 0.6
DURATION_TOLERANCE = 0.10  # the story's scene seconds may be off the target by this fraction

# Rough size of a tool result the model may see (the design's 600 tokens, at ~4 characters each).
MAX_RESULT_CHARS = 2400


@dataclass(frozen=True)
class LoopLimits:
    """Hard caps for one conversation. A loop that cannot stop is the classic agent failure, so
    every way a conversation can run on forever has a number here, enforced in code (loop.py)."""

    model_calls: int = 25  # model calls in one conversation (one shot, one planning retry)
    consecutive_refusals: int = 3  # the same tool refused this many times in a row -> stuck
    refusals: int = 12  # refused calls in one conversation, any tool
    repeats: int = 3  # the very same call (name + arguments) this many times -> stuck
    nudges: int = 1  # "you are not finished" reminders before giving up


STAGE_SECONDS = {
    "story": 1800,
    "characters": 3 * 3600,
    "backgrounds": 3 * 3600,
    "audio": 1800,
    "shots": 2 * 3600,
    "edit": 1800,
    "qa": 1800,
}
