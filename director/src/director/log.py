"""Append-only log of every model call and tool call: films/<slug>/director/log.jsonl.

Cheap to write now, hard to recover later: Step 7 scores the director from it and Step 9
trains on it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

EventFn = Callable[[dict[str, Any]], None]


class EventLog:
    def __init__(self, path: Path | None, echo: bool = False) -> None:
        self.path = path
        self.echo = echo
        self.t0 = time.monotonic()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: dict[str, Any]) -> None:
        event = {"t": round(time.monotonic() - self.t0, 1), **event}
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(event, default=str) + "\n")
        if self.echo:
            print(_line(event), flush=True)


def _line(e: dict[str, Any]) -> str:
    kind = e.get("kind", "?")
    if kind == "model":
        text = e.get("text", "")[:80]
        return (
            f"  [llm] {e.get('seconds', 0):5.1f}s  {e.get('tool_calls', 0)} tool call(s)  {text!r}"
        )
    if kind == "tool":
        mark = "refused" if e.get("refused") else "ok"
        return (
            f"  [tool] {e.get('name')} {mark} {e.get('seconds', 0):.1f}s {e.get('text', '')[:100]}"
        )
    return f"[{kind}] {e.get('msg', '')}"


def null_log(_event: dict[str, Any]) -> None:
    """For tests that do not care about events."""
