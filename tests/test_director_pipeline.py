"""The stage machine end to end with a fake model and a fake MCP world (offline, under a second)."""

from __future__ import annotations

import asyncio
import json

import pytest
from director_world import STORY, FakeChat, FakeHub, PipelineChat, make_cast, says

from director import runner
from director import state as st
from director.config import STAGES
from director.context import Deps
from director.memory import MemoryConflict, MemoryGuard


class World:
    def __init__(self, tmp_path, *, auto=True, chat=None, target=15):
        self.films = tmp_path / "films"
        self.film = make_cast(self.films, "t1")
        st.save(
            self.film, st.DirectorState(film="t1", prompt="a gentle film", target_seconds=target)
        )
        self.hub = FakeHub(self.film)
        self.chat = chat or PipelineChat()
        self.events: list[dict] = []
        self.auto = auto

    def deps(self, **kw) -> Deps:
        return Deps(
            self.chat,
            self.hub,
            None,
            on_event=self.events.append,
            auto=self.auto,
            quality="preview",
            **kw,
        )

    def run(self) -> str:
        return asyncio.run(runner.run_film("t1", self.deps(), self.films))

    @property
    def state(self) -> st.DirectorState:
        return st.load(self.film)


def test_auto_run_goes_through_all_seven_stages_to_a_finished_film(tmp_path):
    w = World(tmp_path)
    assert w.run() == "finished"
    state = w.state
    assert [state.stage(s).status for s in STAGES] == ["complete"] * 7
    assert all(a.status == "approved" for a in state.approvals.values())
    # the files the stage checks look at
    plan = json.loads((w.film / "story" / "shotplan.json").read_text())
    assert [s["id"] for s in plan["shots"]] == ["s01_sh01", "s01_sh02", "s02_sh01", "s02_sh02"]
    for s in plan["shots"]:
        spec = json.loads((w.film / "shots" / s["id"] / "shot.json").read_text())
        for ch in spec["characters"]:  # the rules in code: blink and idle for everyone
            assert {"blink", "idle_breathe"} <= {a["motion"] for a in ch["actions"]}
        assert (w.film / "shots" / s["id"] / "qa.json").is_file()
    assert (w.film / "edit" / "final.mp4").is_file() and (
        w.film / "qa" / "film_report.json"
    ).is_file()
    # existing cast and place were reused: no art tool ran; the code-driven stages made the audio
    names = w.hub.names()
    assert not {"design_character", "build_puppet", "generate_background"} & set(names)
    assert (
        names.count("speak") == 2
        and names.count("compose") == 2
        and names.count("render_shot") == 4
    )
    assert names.count("set_voice") == 2
    # the dialogue shot got its line (apply_lipsync) and the first shot did not
    lipsync = [a["shot_id"] for t, a in w.hub.log if t == "apply_lipsync"]
    assert lipsync == ["s01_sh02", "s02_sh02"]
    # cost ledger and log
    c = state.counters
    assert c.model_calls == 2 + 4 * 4 and c.tool_calls > 40
    assert state.stage("shots").counters.model_calls == 17
    assert (w.film / "director" / "transcripts" / "s01_sh01.json").is_file()


def test_a_shot_that_outlasts_its_line_is_fitted_in_code(tmp_path):
    w = World(tmp_path)
    w.run()
    plan = json.loads((w.film / "story" / "shotplan.json").read_text())
    line_shot = next(s for s in plan["shots"] if s.get("line"))
    assert line_shot["seconds"] >= 0.6 + 1.5 + 0.6  # lead + the 1.5 s recording + tail


def test_approvals_stop_the_run_and_survive_a_restart(tmp_path):
    w = World(tmp_path, auto=False)
    expected = [
        ("awaiting_approval:story", "story"),
        ("awaiting_approval:characters", "characters"),
        ("awaiting_approval:shots", "first_shot"),
        ("awaiting_approval:qa", "final"),
    ]
    for outcome, checkpoint in expected:
        assert w.run() == outcome
        assert (w.film / "director" / "review" / f"{checkpoint}.md").is_file()
        assert w.run() == outcome  # asking again does nothing: still waiting
        state = w.state  # a "restart" reads everything from state.json
        runner.approve(state, w.film, checkpoint)
        if checkpoint == "first_shot":
            assert w.hub.names().count("render_shot") == 1  # only the look-and-feel shot so far
    assert w.run() == "finished"
    assert w.hub.names().count("render_shot") == 4


def test_nothing_runs_past_a_story_the_owner_has_not_approved(tmp_path):
    w = World(tmp_path, auto=False)
    assert w.run() == "awaiting_approval:story"
    assert w.state.stage("characters").status == "pending"
    assert "speak" not in w.hub.names()


def test_revise_runs_the_stage_again_with_the_owners_note(tmp_path):
    class Spy(PipelineChat):
        briefs: list[str] = []  # noqa: RUF012

        async def __call__(self, messages, **kw):
            if kw.get("format"):
                self.briefs.append(messages[1]["content"])
            return await super().__call__(messages, **kw)

    w = World(tmp_path, auto=False, chat=Spy())
    assert w.run() == "awaiting_approval:story"
    runner.revise(w.state, w.film, "story", "make the ending quieter")
    assert not (w.film / "story" / "story.json").exists()
    assert w.run() == "awaiting_approval:story"
    assert "Owner's note: make the ending quieter" in Spy.briefs[-1]
    assert "Owner's note" not in Spy.briefs[0]


def test_resume_after_a_crash_in_shots_does_not_redo_finished_work(tmp_path):
    w = World(tmp_path)
    w.hub.fail_after_renders = 2  # the third render raises, like a killed process
    with pytest.raises(RuntimeError, match="simulated crash"):
        w.run()
    assert w.state.stage("shots").status == "running"  # what a crash leaves behind
    before = w.hub.names()
    assert before.count("render_shot") == 3 and before.count("speak") == 2
    w.hub.fail_after_renders = None
    assert w.run() == "finished"
    after = w.hub.names()[len(before) :]
    assert after.count("render_shot") == 2  # shots 3 and 4 only: 1 and 2 are kept
    assert "speak" not in after and "compose" not in after and "set_voice" not in after
    assert "describe_shot" in after
    assert w.state.stage("shots").attempts == 2


def test_a_finished_stage_whose_files_vanished_is_redone_and_later_ones_too(tmp_path):
    w = World(tmp_path)
    assert w.run() == "finished"
    (w.film / "shots" / "s01_sh02" / "shot.mp4").unlink()
    names_before = len(w.hub.names())
    assert w.run() == "finished"
    again = w.hub.names()[names_before:]
    assert again.count("render_shot") == 1  # only the missing one
    assert "assemble" in again and "check_film" in again  # edit and qa are stale after it
    assert "speak" not in again  # earlier stages were still fine


def test_a_stage_that_cannot_finish_fails_and_waits_for_the_owner(tmp_path):
    class Lazy(PipelineChat):
        async def __call__(self, messages, **kw):
            if kw.get("format"):
                return await super().__call__(messages, **kw)
            self.calls.append({"conversation": True})
            return says("I think it is fine.")  # never calls a tool

    w = World(tmp_path, chat=Lazy())
    assert w.run() == "failed:shots"
    assert "nudge" not in (w.state.stage("shots").last_error or "")
    assert (
        "not rendered" in w.state.stage("shots").last_error
        or "shot" in w.state.stage("shots").last_error
    )
    calls_before = len(w.chat.calls)
    assert w.run() == "failed:shots"  # no silent retry
    assert len(w.chat.calls) == calls_before
    runner.retry(w.state, w.film, "shots")
    w.chat = PipelineChat()
    assert w.run() == "finished"


def test_a_refused_scaffold_step_is_reported_to_the_model_not_hidden(tmp_path):
    w = World(tmp_path)
    w.hub.refuse = {"apply_motion": ["refused: wave needs a side"]}
    briefs: list[str] = []

    class Spy(PipelineChat):
        async def __call__(self, messages, **kw):
            if not kw.get("format"):
                briefs.append(messages[1]["content"])
            return await super().__call__(messages, **kw)

    w.chat = Spy()
    # the refused call was kit's blink: the rule in code notices it is missing
    assert w.run() == "failed:shots"
    assert "REFUSED when building" in briefs[0] and "wave needs a side" in briefs[0]
    assert "kit needs blink" in w.state.stage("shots").last_error


def test_memory_guard_order_and_comfyui_conflict():
    log: list[str] = []
    state = {"comfy": "idle", "loaded": ["qwen3:14b"]}

    def unload(name):
        log.append(f"unload {name}")
        state["loaded"].remove(name)

    guard = MemoryGuard(
        "qwen3:14b",
        lambda: list(state["loaded"]),
        unload,
        lambda: state["comfy"],
        lambda: log.append("free comfy"),
    )

    async def enter(stage):
        async with guard.for_stage(stage):
            log.append(f"in {stage}")

    asyncio.run(enter("characters"))  # art stage: the chat model goes first
    asyncio.run(enter("shots"))  # LLM stage: ComfyUI is freed first
    assert log == ["unload qwen3:14b", "in characters", "free comfy", "in shots"]
    state["comfy"] = "busy"
    with pytest.raises(MemoryConflict):
        asyncio.run(enter("story"))


def test_a_busy_comfyui_fails_the_llm_stage_instead_of_loading_a_second_model(tmp_path):
    w = World(tmp_path)
    guard = MemoryGuard("m", lambda: [], lambda n: None, lambda: "busy", lambda: None)
    outcome = asyncio.run(runner.run_film("t1", Deps(w.chat, w.hub, guard, auto=True), w.films))
    assert outcome == "failed:story" and "ComfyUI is busy" in w.state.stage("story").last_error
    assert w.chat.calls == []


def test_the_story_plan_gets_one_retry_with_the_problems_listed(tmp_path):
    bad = json.loads(json.dumps(STORY))
    bad["scenes"][0]["seconds"] = 30  # the film would be 38 s, not 15
    replies = [says(json.dumps(bad)), says(json.dumps(STORY))]
    seen = []

    def spy(i):
        def f(messages, tools, fmt):
            seen.append([m["content"] for m in messages if m["role"] == "user"])
            return replies[i]

        return f

    w = World(tmp_path, chat=FakeChat([spy(0), spy(1)]))
    w.auto = False
    assert w.run() == "awaiting_approval:story"
    assert "scene seconds add up to 38" in seen[1][-1]
    assert w.chat.calls[1]["think"] is True and w.chat.calls[1]["format"]["required"][0] == "title"
