"""The agent loop core with a fake model and a fake tool server: no Ollama, no MCP, no GPU."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from director_world import FakeChat, calls, says

from director.config import LoopLimits
from director.dispatch import CallContext
from director.hub import ToolInfo, ToolResult
from director.loop import run_conversation
from director.state import Counters
from director.toolview import STAGE_TOOLS, ToolView


class Hub:
    """A tool server whose answers are scripted per tool name."""

    def __init__(self, answers: dict[str, list[ToolResult]] | None = None) -> None:
        schema = {
            "type": "object",
            "properties": {
                "film": {"type": "string"},
                "shot_id": {"type": "string"},
                "t": {"type": "number"},
            },
            "required": ["film", "t"],
        }  # fmt: skip
        self.tools = {n: ToolInfo("f", n, n, schema) for n in ("describe_shot", "render_shot")}
        self.answers = answers or {}
        self.seen: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool, args, on_progress=None) -> ToolResult:
        self.seen.append((tool, args))
        queue = self.answers.get(tool)
        return queue.pop(0) if queue else ToolResult('{"ok":true}', {"ok": True})


def go(
    script,
    hub=None,
    complete=lambda: None,
    limits=None,
    ctx=None,
    tools=("describe_shot", "render_shot"),
):
    hub = hub or Hub()
    chat = FakeChat(script)
    view = ToolView({n: i for n, i in hub.tools.items() if n in tools})
    counters = Counters()
    events: list[dict] = []
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    turn = asyncio.run(
        run_conversation(
            chat, hub, messages, view, ctx or CallContext({"film": "f1", "shot_id": "s01_sh01"}),
            think=False, limits=limits or LoopLimits(), complete=complete,
            on_event=events.append, counters=counters,
        )
    )  # fmt: skip
    return turn, hub, chat, counters, events


def test_tool_result_goes_back_and_complete_ends_the_loop():
    turn, hub, _, counters, _ = go([calls(("describe_shot", {"t": 1.0}))])
    assert turn.stop == "done" and turn.tool_calls == 1
    # film and shot_id were added by code, not by the model
    assert hub.seen == [("describe_shot", {"t": 1.0, "film": "f1", "shot_id": "s01_sh01"})]
    assert (counters.model_calls, counters.tool_calls) == (1, 1)
    assert counters.prompt_tokens == 10


def test_the_model_never_sees_the_arguments_code_fills_in():
    view = ToolView({"describe_shot": Hub().tools["describe_shot"]})
    (tool,) = view.ollama_tools()
    params = tool["function"]["parameters"]
    assert "film" not in params["properties"] and "shot_id" not in params["properties"]
    assert params["required"] == ["t"]


def test_a_refused_call_is_fed_back_and_the_model_can_retry():
    refusal = ToolResult("refused: t must be inside the shot", refused=True)
    hub = Hub({"describe_shot": [refusal]})
    finished = {"v": False}

    def complete():
        return None if finished["v"] else "not rendered."

    def fix(messages, tools, fmt):
        assert messages[-1] == {
            "role": "tool",
            "tool_name": "describe_shot",
            "content": refusal.text,
        }
        finished["v"] = True
        return calls(("describe_shot", {"t": 0.5}))

    turn, hub, _, counters, _ = go([calls(("describe_shot", {"t": 99})), fix], hub, complete)
    assert turn.stop == "done" and turn.refusals == 1 and counters.refusals == 1
    assert [a["t"] for _, a in hub.seen] == [99, 0.5]


def test_invalid_calls_never_reach_the_server_and_say_what_to_fix():
    bad = [
        ("not_a_tool", {}, "not available"),
        ("describe_shot", {}, "invalid"),  # t is required
        ("describe_shot", {"t": "soon"}, "invalid t"),
        ("describe_shot", {"t": 1, "film": "other"}, "must be 'f1'"),
        ("describe_shot", "[1, 2]", "JSON object"),
        ("describe_shot", "{oops", "not valid JSON"),
    ]
    seen_messages: list[str] = []

    def collect(messages, tools, fmt):
        seen_messages.extend(m["content"] for m in messages if m["role"] == "tool")
        return says("ok")

    script = [calls((n, a)) for n, a, _ in bad] + [collect, says()]
    limits = LoopLimits(consecutive_refusals=99, refusals=99, repeats=99)
    _, hub, _, counters, _ = go(script, complete=lambda: "x", limits=limits)
    assert hub.seen == []
    assert counters.refusals == len(bad)
    for (_, _, expect), message in zip(bad, seen_messages, strict=True):
        assert expect in message


def test_string_arguments_are_accepted():
    _, hub, *_ = go([calls(("describe_shot", json.dumps({"t": 2})))], complete=lambda: None)
    assert hub.seen[0][1]["t"] == 2


def test_unknown_ids_are_refused_before_running():
    ctx = CallContext({"film": "f1"}, allowed={"t": {"1", "2"}})
    _, hub, *_ = go(
        [calls(("describe_shot", {"t": 3}))] + [says()] * 3, ctx=ctx, complete=lambda: "x"
    )
    assert hub.seen == []


def test_three_refusals_of_one_tool_in_a_row_stop_the_loop():
    refusals = [ToolResult("refused: no", refused=True)] * 5
    script = [calls(("describe_shot", {"t": i})) for i in range(5)]
    turn, _, chat, *_ = go(script, Hub({"describe_shot": refusals}), complete=lambda: "unfinished")
    assert turn.stop == "stuck" and "3 times in a row" in turn.why
    assert len(chat.calls) == 3  # it did not ask the model a fourth time


def test_a_success_resets_the_consecutive_refusal_count():
    no = ToolResult("refused: no", refused=True)
    hub = Hub({"describe_shot": [no, no, ToolResult('{"ok":1}', {}), no, no]})
    script = [calls(("describe_shot", {"t": i})) for i in range(5)] + [says(), says()]
    turn, *_ = go(script, hub, complete=lambda: "unfinished")
    assert turn.stop == "unfinished"  # 2 refusals, a success, 2 more: never 3 in a row


def test_asking_for_the_same_thing_again_and_again_is_stuck():
    script = [calls(("describe_shot", {"t": 1.0}))] * 5
    turn, hub, _, *_ = go(script, complete=lambda: "unfinished")
    assert turn.stop == "stuck" and "same arguments" in turn.why
    assert len(hub.seen) == 2  # the third request is stopped before it runs


def test_plain_text_while_incomplete_nudges_once_then_gives_up():
    def nudged(messages, tools, fmt):
        assert (
            messages[-1]["role"] == "user"
            and "Not finished yet: the shot is not rendered." in messages[-1]["content"]
        )
        return says("still thinking")

    turn, _, chat, *_ = go([says("done!"), nudged], complete=lambda: "the shot is not rendered.")
    assert turn.stop == "unfinished" and turn.why == "the shot is not rendered."
    assert len(chat.calls) == 2


def test_plain_text_when_complete_is_done():
    turn, *_ = go([says("all done")])
    assert turn.stop == "done" and turn.model_calls == 1


def test_model_call_cap():
    script = [calls(("describe_shot", {"t": float(i)})) for i in range(10)]
    turn, _, chat, *_ = go(script, complete=lambda: "x", limits=LoopLimits(model_calls=4))
    assert turn.stop == "limit" and len(chat.calls) == 4


def test_a_refusal_cap_over_different_tools():
    no = ToolResult("refused", refused=True)
    hub = Hub({"describe_shot": [no] * 9, "render_shot": [no] * 9})
    script = [calls(("describe_shot", {"t": 1}), ("render_shot", {"t": 2}))] * 3
    limits = LoopLimits(refusals=4, consecutive_refusals=99, repeats=99)
    turn, *_ = go(script, hub, complete=lambda: "x", limits=limits)
    assert turn.stop == "limit" and "4 refused" in turn.why


def test_a_precondition_blocks_a_tool_until_code_allows_it():
    state = {"looked": False}
    ctx = CallContext(
        {"film": "f1"},
        preconditions={"render_shot": lambda: None if state["looked"] else "Look first."},
    )

    def then_look(messages, tools, fmt):
        assert messages[-1]["content"] == "refused: Look first."
        state["looked"] = True
        return calls(("render_shot", {"t": 1}))

    complete = lambda: None if state["looked"] and len(hub.seen) == 1 else "not rendered."  # noqa: E731
    hub = Hub()
    go([calls(("render_shot", {"t": 1})), then_look], hub=hub, ctx=ctx, complete=complete)
    assert [t for t, _ in hub.seen] == ["render_shot"]  # the blocked first try never ran


def test_out_of_time_stops_before_asking_the_model():
    chat_calls = []

    async def run():
        hub = Hub()
        return await run_conversation(
            FakeChat([says()]), hub, [], ToolView(hub.tools), CallContext(), think=False,
            limits=LoopLimits(), complete=lambda: "x", on_event=chat_calls.append,
            counters=Counters(), out_of_time=lambda: "stage clock ran out",
        )  # fmt: skip

    turn = asyncio.run(run())
    assert turn.stop == "limit" and turn.why == "stage clock ran out" and chat_calls == []


def test_read_craft_is_a_local_tool(tmp_path, monkeypatch):
    from director import craft, dispatch

    (tmp_path / "staging.md").write_text("# Staging\n> where to stand\nbody text")
    monkeypatch.setattr(dispatch, "read_craft", lambda topic: craft.read_craft(topic, tmp_path))
    assert "read_craft" in ToolView.for_stage("shots", {}) and "read_craft" in STAGE_TOOLS["shots"]
    result = asyncio.run(dispatch.run_tool_call(Hub(), "read_craft", {"topic": "Staging"}))
    assert "body text" in result.text and not result.refused
    unknown = asyncio.run(dispatch.run_tool_call(Hub(), "read_craft", {"topic": "nope"}))
    assert "Topics: staging" in unknown.text
