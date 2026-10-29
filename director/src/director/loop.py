"""CORE (1/3): one conversation with the model, until code says it is finished.

This is the whole idea of an agent in ~100 lines. Read `run_conversation` top to bottom:

    ask the model  ->  it answers with tool calls?  ->  run them, show it the results, ask again
                       it answers with plain text?  ->  ask CODE if the work is complete
                                                         complete: stop.  not complete: nudge once.

The model never decides that it is done: `complete()` does, by looking at the film folder. And the
loop can always stop: every way it could run on forever has a cap in `LoopLimits` (config.py).
Why the caps are code and not instructions: a model told "stop after three tries" will sometimes
try a fourth time; a counter will not.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from director.chat import ChatFn, assistant_message
from director.config import LoopLimits
from director.dispatch import CallContext, run_tool_call, validate_call
from director.hub import ToolDispatcher
from director.log import EventFn
from director.state import Counters
from director.toolview import ToolView

Stop = Literal["done", "limit", "stuck", "unfinished"]


@dataclass
class Turn:
    messages: list[dict[str, Any]]  # the whole history, including this conversation's new messages
    stop: Stop
    why: str  # one sentence, for the log and the owner (empty when done)
    model_calls: int = 0
    tool_calls: int = 0
    refusals: int = 0


async def run_conversation(
    chat: ChatFn,
    hub: ToolDispatcher,
    messages: list[dict[str, Any]],
    view: ToolView,
    ctx: CallContext,
    *,
    think: bool,
    limits: LoopLimits,
    complete: Callable[[], str | None],
    on_event: EventFn,
    counters: Counters,
    out_of_time: Callable[[], str | None] = lambda: None,
) -> Turn:
    """Run until `complete()` returns None (done) or a cap trips.

    `complete()` returns None when the work is finished, else a sentence naming what is missing:
    the nudge shown to the model. `counters` is the run's cost ledger (state.json).
    """
    turn = Turn(messages, "done", "")
    tools = view.ollama_tools()
    seen: Counter[str] = Counter()  # identical calls so far: (name, arguments) -> times
    refused_in_a_row: Counter[str] = Counter()  # tool name -> consecutive refusals
    nudges = 0

    while True:
        # --- stop conditions that need no model call --------------------------------------
        if turn.model_calls >= limits.model_calls:
            return _stop(turn, "limit", f"{limits.model_calls} model calls used")
        if late := out_of_time():
            return _stop(turn, "limit", late)

        # --- 1. ask the model ------------------------------------------------------------
        reply = await chat(messages, tools=tools, think=think)
        turn.model_calls += 1
        counters.model_calls += 1
        counters.prompt_tokens += reply.prompt_tokens
        counters.output_tokens += reply.output_tokens
        counters.llm_seconds += reply.seconds
        on_event(
            {
                "kind": "model",
                "seconds": round(reply.seconds, 1),
                "text": reply.content,
                "tool_calls": len(reply.tool_calls),
                "prompt_tokens": reply.prompt_tokens,
                "output_tokens": reply.output_tokens,
                "calls": [c.name for c in reply.tool_calls],
            }
        )
        messages.append(assistant_message(reply))

        # --- 2. the model asked for tools: run each, feed every result back ---------------
        if reply.tool_calls:
            for call in reply.tool_calls:
                name = call.name
                args, problem = validate_call(call, view, ctx)  # before anything runs
                if args is not None:
                    key = name + json.dumps(args, sort_keys=True, default=str)
                    seen[key] += 1
                    if seen[key] >= limits.repeats:  # asking for the same thing again and again
                        return _stop(
                            turn,
                            "stuck",
                            f"{name} was requested {seen[key]} times with the same arguments",
                        )
                    result = await run_tool_call(
                        hub, name, args, lambda m: on_event({"kind": "progress", "msg": m})
                    )
                    refused, text, seconds = result.refused, result.text, result.seconds
                else:
                    refused, text, seconds = True, f"refused: {problem}", 0.0
                turn.tool_calls += 1
                counters.tool_calls += 1
                counters.tool_seconds += seconds
                on_event(
                    {
                        "kind": "tool",
                        "name": name,
                        "args": args or call.arguments,
                        "refused": refused,
                        "seconds": round(seconds, 1),
                        "text": text,
                    }
                )
                # A refusal is information, not an error: the model reads it and tries again.
                messages.append({"role": "tool", "tool_name": name, "content": text})
                if refused:
                    turn.refusals += 1
                    counters.refusals += 1
                    refused_in_a_row[name] += 1
                    if refused_in_a_row[name] >= limits.consecutive_refusals:
                        return _stop(
                            turn,
                            "stuck",
                            f"{name} refused {refused_in_a_row[name]} times in a row: {text[:200]}",
                        )
                    if turn.refusals >= limits.refusals:
                        return _stop(turn, "limit", f"{turn.refusals} refused calls")
                else:
                    refused_in_a_row[name] = 0
            if complete() is None:  # the work is finished: no need to ask the model anything else
                return turn
            continue

        # --- 3. plain text, no tool call: is the work really done? Code decides. -----------
        missing = complete()
        if missing is None:
            return turn
        if nudges >= limits.nudges:
            return _stop(turn, "unfinished", missing)
        nudges += 1
        messages.append(
            {"role": "user", "content": f"Not finished yet: {missing} Use the tools to finish."}
        )


def _stop(turn: Turn, stop: Stop, why: str) -> Turn:
    turn.stop, turn.why = stop, why
    return turn
