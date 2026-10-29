"""CORE (2/3): one tool call, from the model's request to the message that goes back.

Three jobs, in this order, and the order matters:

1. `validate_call`: is this call even sensible? The checks run in code, BEFORE the tool runs, and a
   failure is not an exception: it becomes the text of the tool message, so the model can read
   what to fix and try again. (The MCP servers do the same for what they refuse, D-034.)
2. `run_tool_call`: run it (a local tool or an MCP tool). A server refusal is data, not a crash.
3. The result is shortened, so a long answer cannot flood the model's context window.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from director.chat import ToolCall
from director.craft import read_craft
from director.hub import ProgressFn, ToolDispatcher, ToolResult, compact
from director.toolview import LOCAL_TOOLS, ToolView


@dataclass
class CallContext:
    """What code knows that the model should not have to remember."""

    fixed_args: dict[str, Any] = field(default_factory=dict)  # film, shot_id: injected on each call
    # argument name -> the values that exist right now (e.g. character_id -> cast in this shot)
    allowed: dict[str, set[str]] = field(default_factory=dict)
    # tool name -> None if it may run now, else why not (e.g. "look at a frame before rendering")
    preconditions: dict[str, Callable[[], str | None]] = field(default_factory=dict)


def parse_arguments(raw: dict[str, Any] | str) -> tuple[dict[str, Any] | None, str | None]:
    """Models sometimes send the arguments as a JSON *string*; accept that, reject anything else."""
    if isinstance(raw, dict):
        return dict(raw), None
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as err:
        return None, f"the arguments are not valid JSON ({err.msg}). Send a JSON object."
    if not isinstance(parsed, dict):
        return None, "the arguments must be a JSON object of name: value pairs."
    return parsed, None


def validate_call(
    call: ToolCall, view: ToolView, ctx: CallContext
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (arguments to send, None) or (None, a message that says what to fix)."""
    if call.name not in view:
        return (
            None,
            f"{call.name} is not available now. Tools you can use: {', '.join(view.names())}.",
        )
    args, err = parse_arguments(call.arguments)
    if args is None:
        return None, err
    # Inject what code already knows. A wrong value is refused rather than silently overwritten.
    props = view.schema(call.name).get("properties", {})
    for key, value in ctx.fixed_args.items():
        if key in props:
            if key in args and args[key] != value:
                return None, f"{key} must be {value!r} here, not {args[key]!r}. Leave {key} out."
            args[key] = value
    schema_errors = sorted(
        jsonschema.Draft202012Validator(view.schema(call.name)).iter_errors(args),
        key=lambda e: list(e.path),
    )
    if schema_errors:
        e = schema_errors[0]
        where = ".".join(map(str, e.path)) or "arguments"
        return None, f"invalid {where}: {e.message}"
    if (gate := ctx.preconditions.get(call.name)) and (why := gate()):
        return None, why
    for key, known in ctx.allowed.items():
        if key in args and known and args[key] not in known:
            return None, f"{key} {args[key]!r} does not exist. Known: {', '.join(sorted(known))}."
    return args, None


async def run_tool_call(
    hub: ToolDispatcher, name: str, args: dict[str, Any], on_progress: ProgressFn | None = None
) -> ToolResult:
    """Run a validated call. A refusal or a dead server is returned as text, never raised."""
    if name in LOCAL_TOOLS:  # a tool that lives in this process, not on an MCP server
        return ToolResult(compact(read_craft(str(args.get("topic", "")))))
    return await hub.call(name, args, on_progress)
