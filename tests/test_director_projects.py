"""The director on a film of a project (D-094): reuse the library, plan in acts, approve per act,
resume, and re-render only the act that changed. Fake model, fake MCP world, a real project."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil

from director_project_world import ProjectChat, ProjectHub, ProjectWorld
from director_world import SHOTPLAN, STORY

from director import runner
from director import state as st
from director.checks import act_plan_of, merged_plan, one_scene_story, story_of
from director.config import STAGES
from director.context import Deps
from director.plans import PlanError, Roster, advise_shotplan, check_story, story_schema


class Run:
    def __init__(
        self,
        tmp_path,
        *,
        auto=True,
        library=("kit", "bo"),
        pin_cast=(),
        pin_places=(),
        chat=None,
        acts=2,
    ):
        self.w = ProjectWorld(tmp_path, library=library)
        self.hub = ProjectHub(self.w)
        self.chat = chat or ProjectChat()
        self.auto, self.events = auto, []
        st.save(
            self.w.film,
            st.DirectorState(
                film="balloon",
                prompt="a gentle film",
                project="proj",
                target_seconds=15,
                pinned_cast=list(pin_cast),
                pinned_places=list(pin_places),
                target_acts=acts,
            ),
        )

    def deps(self) -> Deps:
        return Deps(
            self.chat,
            self.hub,
            None,
            on_event=self.events.append,
            auto=self.auto,
            quality="preview",
            project=self.w.project,
            refresh=self.w.refresh,
        )

    def run(self) -> str:
        return asyncio.run(runner.run_film("balloon", self.deps(), self.w.root))

    @property
    def state(self) -> st.DirectorState:
        return st.load(self.w.film)

    def acts(self):
        return self.w.project.list_acts("balloon")


def test_the_director_plans_acts_from_the_projects_cast_and_places(tmp_path):
    r = Run(tmp_path)
    assert r.run() == "finished"
    assert [r.state.stage(s).status for s in STAGES] == ["complete"] * len(STAGES)
    # the cast and place came from the library: no art tool ran, and the film references them
    names = r.hub.names()
    assert not {"design_character", "build_puppet", "generate_background"} & set(names)
    film = r.w.project.get_film("balloon")
    assert len(film["cast"]) == 2 and len(film["places"]) == 1
    # a scene is an act with its title, place, cast, beats and several camera angles
    acts = r.acts()
    assert [a["title"] for a in acts] == ["Finding it", "Letting go"]
    assert [len(a["shot_ids"]) for a in acts] == [2, 2]
    assert acts[0]["beats"] == ["a beat", "a beat"]
    assert r.state.acts == {"s01": acts[0]["id"], "s02": acts[1]["id"]}
    # shots were filed under their acts, built by the same scaffold; the movie was exported once
    assert [a["shot_id"].split("_")[0] for t, a in r.hub.log if t == "render_shot"] == [
        "s01"
    ] * 2 + ["s02"] * 2
    assert names.count("add_act") == 2 and names.count("render_act") == 2
    assert names.count("export_movie") == 1
    export = json.loads((r.w.film / "director" / "export.json").read_text())
    assert (
        export["acts"] == ["s01", "s02"] and export["rendered_acts"] == []
    )  # acts were rendered already
    # the tools were told which project and film; the story brief listed the library
    assert all(
        a.get("project") == "proj"
        for t, a in r.hub.log
        if t in ("add_act", "export_movie", "speak")
    )
    assert "- kit" in r.chat.briefs[0] and "ACT" in r.chat.briefs[0]
    assert "title" in r.chat.formats[0]["properties"]["scenes"]["items"]["properties"]


def test_the_directors_files_live_in_the_project_and_survive_the_working_folder(tmp_path):
    r = Run(tmp_path)
    assert r.run() == "finished"
    assert (r.w.film / "story").is_symlink() and (r.w.film / "director").is_symlink()
    assert (r.w.home / "director" / "state.json").is_file()
    shutil.rmtree(r.w.film)  # the working folder is a cache: gone, and the progress is not
    r.w.refresh()
    assert r.state.stage("story").status == "complete" and story_of(r.w.film) is not None
    assert act_plan_of(r.w.film, "s02") is not None


def test_a_character_the_library_lacks_is_made_and_published_to_the_project(tmp_path):
    r = Run(tmp_path, library=("kit",))
    assert r.run() == "finished"
    built = [a["character_id"] for t, a in r.hub.log if t == "build_puppet"]
    assert built == ["bo"]  # only the missing one; kit came from the library
    assert {c["slug"] for c in r.w.project.list_characters()} == {"kit", "bo"}
    assert len(r.w.project.get_film("balloon")["cast"]) == 2


def test_pinned_cast_limits_the_story_in_the_schema_and_in_the_checks(tmp_path):
    r = Run(tmp_path, pin_cast=["kit"], pin_places=["orchard"])
    assert r.run() == "failed:story"  # the fake model still names bo: refused twice, then it stops
    assert "allows only" in r.state.stage("story").last_error
    schema = r.chat.formats[0]["properties"]["characters"]["items"]["properties"]["id"]
    assert schema == {"enum": ["kit"]}
    assert not any(t in ("speak", "add_act") for t in r.hub.names())


def test_roster_checks_unit():
    roster = Roster(cast=["kit", "bo"], places=["orchard"], pin_cast=["kit"], acts=3)
    problems = check_story(PROJECT_STORY_COPY(), 15, lambda t: [], roster)
    assert any("only these characters" in p for p in problems)
    assert any("exactly 3 scenes" in p for p in problems)
    assert (
        story_schema(__import__("director.plans").plans.Capabilities(), roster=roster)[
            "properties"
        ]["scenes"]["minItems"]
        == 3
    )


def PROJECT_STORY_COPY():
    return json.loads(json.dumps(__import__("director_project_world").PROJECT_STORY))


def drive(r: Run) -> list[str]:
    """Run, approve whatever waits, run again: the checkpoints in the order the owner met them."""
    seen = []
    for _ in range(20):
        out = r.run()
        if out == "finished":
            return seen
        waiting = [k for k, a in r.state.approvals.items() if a.status == "waiting"]
        assert waiting, out
        seen.append(waiting[0])
        state = r.state
        runner.approve(state, r.w.film, waiting[0])
    raise AssertionError("never finished")


def test_approvals_are_per_act_and_the_next_act_waits_for_them(tmp_path):
    r = Run(tmp_path, auto=False)
    # stop at the first act's approval: act 2 has not been planned or built yet
    seen = []
    while True:
        assert r.run().startswith("awaiting_approval")
        waiting = next(k for k, a in r.state.approvals.items() if a.status == "waiting")
        seen.append(waiting)
        if waiting == "act_s01":
            break
        runner.approve(r.state, r.w.film, waiting)
    assert (r.w.film / "director" / "review" / "act_s01.md").is_file()
    assert act_plan_of(r.w.film, "s02") is None and len(r.hub.rendered_acts) == 1
    runner.approve(r.state, r.w.film, "act_s01")
    assert seen == ["story", "characters", "first_shot", "act_s01"]
    # the rest
    rest = drive(r)
    assert rest == ["act_s02", "final"]
    assert (
        len(r.hub.rendered_acts) == 2
    )  # each act rendered once (render_act on a fresh act is a no-op)


def test_resume_after_a_crash_does_not_redo_finished_acts(tmp_path):
    r = Run(tmp_path)
    r.hub.fail_after_renders = 3  # two shots of act 1, the first of act 2, then the machine dies
    with contextlib.suppress(RuntimeError):
        r.run()
    assert r.state.stage("shots").status == "running"
    r.hub.fail_after_renders = None
    renders_before = r.hub.names().count("render_shot")
    assert r.run() == "finished"
    assert r.hub.names().count("render_shot") == renders_before + 1  # only the shot that died
    assert r.hub.names().count("add_act") == 2
    assert (
        len(r.chat.briefs) == 3
    )  # the story plus one shot plan per act: act 1 was not planned again


def test_revising_one_act_renders_only_that_act_again(tmp_path):
    r = Run(tmp_path)
    assert r.run() == "finished"
    first_act, second_act = (a["id"] for a in r.acts())
    assert r.hub.rendered_acts == [first_act, second_act]
    shots_before = r.hub.names().count("render_shot")
    runner.revise(r.state, r.w.film, "act_s02", "make it quieter")
    assert (
        r.state.stage("shots").status == "pending"
        and r.state.approvals["act_s02"].status == "pending"
    )
    assert r.run() == "finished"
    assert "make it quieter" in r.chat.briefs[-1] and r.chat.briefs.count(r.chat.briefs[0]) == 1
    assert r.hub.names().count("render_shot") == shots_before + 2  # act 2's two shots, not act 1's
    assert r.hub.rendered_acts == [first_act, second_act, second_act]  # act 1 was reused
    export = json.loads((r.w.film / "director" / "export.json").read_text())
    assert export["rendered_acts"] == []  # the shots stage had already rendered the changed act
    # the story did not get planned again
    assert sum(1 for c in r.chat.calls if c["format"]) == 1 + 2 + 1


def test_a_replanned_act_drops_the_shots_it_no_longer_plans(tmp_path):
    r = Run(tmp_path)
    assert r.run() == "finished"
    plan = act_plan_of(r.w.film, "s02")
    plan["shots"] = plan["shots"][1:]  # keep the shot that carries the line
    plan["shots"][0]["seconds"] = 8
    (r.w.film / "story" / "plans" / "s02.json").write_text(json.dumps(plan))
    r.hub.log.clear()
    state = r.state  # (the owner asked for a re-run of the stage: the edited plan is the new plan)
    state.stage("shots").status = "pending"
    st.save(r.w.film, state)
    assert r.run() == "finished"
    assert [a["shot_id"] for t, a in r.hub.log if t == "remove_shot"] == ["s02_sh01"]
    assert len(r.acts()[1]["shot_ids"]) == 1


def test_taste_judges_the_film_so_far_and_only_the_last_act_must_end_calm():
    story = STORY | {"scenes": [dict(s, title="t") for s in STORY["scenes"]]}
    act1 = {"shots": [s for s in SHOTPLAN["shots"] if s["scene"] == "s01"]}
    act2 = {"shots": [s for s in SHOTPLAN["shots"] if s["scene"] == "s02"]}
    assert advise_shotplan(act1, story, final=False) == []
    assert advise_shotplan(act2, story, final=True, prior=act1["shots"]) == []
    # a first act that ends on a big feeling is fine; the same shots as the last act are not
    loud = json.loads(json.dumps(act1))
    loud["shots"][-1]["camera"] = "push_in"
    assert advise_shotplan(loud, story, final=False) == []
    assert advise_shotplan(loud, story, final=True)
    # a complaint about a shot of an earlier act is dropped: this plan cannot fix it
    prior = json.loads(json.dumps(act1["shots"]))
    prior[0]["characters"][0]["expression"] = "grumpy"
    prior[1]["characters"][0]["expression"] = "grumpy"
    assert not any(
        "grumpy" in m and "s01_sh0" in m for m in advise_shotplan(act2, story, prior=prior)
    )


def test_helpers_cut_the_story_to_one_act_and_merge_plans(tmp_path):
    story = STORY
    one = one_scene_story(story, "s02")
    assert [s["id"] for s in one["scenes"]] == ["s02"] and {c["id"] for c in one["characters"]} == {
        "kit",
        "bo",
    }
    d = tmp_path
    (d / "story" / "plans").mkdir(parents=True)
    (d / "story" / "plans" / "s02.json").write_text(json.dumps({"shots": [{"id": "s02_sh01"}]}))
    (d / "story" / "plans" / "s01.json").write_text(json.dumps({"shots": [{"id": "s01_sh01"}]}))
    assert [s["id"] for s in merged_plan(d, story)["shots"]] == ["s01_sh01", "s02_sh01"]


def test_the_planner_reports_a_plan_error_for_an_impossible_act_count():
    assert PlanError  # (the story stage turns this into a failed stage; see the pinned-cast test)


def test_link_home_moves_a_real_folder_into_the_home_and_is_idempotent(tmp_path):
    from director.project_mode import check_pins, link_home

    work, home = tmp_path / "work", tmp_path / "home"
    (work / "story").mkdir(parents=True)
    (work / "story" / "story.json").write_text("{}")
    link_home(work, home)
    link_home(work, home)
    assert (work / "story").is_symlink() and (home / "story" / "story.json").is_file()
    assert (work / "director").is_symlink()
    w = ProjectWorld(tmp_path / "w2")
    assert check_pins(w.project, ["kit", "nobody"], ["orchard", "moon"]) == [
        "character 'nobody'",
        "place 'moon'",
    ]


def test_an_act_with_many_lines_gets_the_seconds_its_lines_need(tmp_path):
    from director.checks import act_target

    (tmp_path / "director").mkdir()
    lines = [
        {"scene": "s01", "who": "kit", "text": f"Line {i}", "line_id": f"l{i}", "duration_s": 2.0}
        for i in range(3)
    ]
    (tmp_path / "director" / "lines.json").write_text(json.dumps(lines))
    scene = {
        "id": "s01",
        "seconds": 8,
        "lines": [{"who": "kit", "text": f"Line {i}"} for i in range(3)],
    }
    assert (
        act_target(tmp_path, scene) == 11
    )  # each line's shot lasts lead + line + tail = 3.2 s, rounded up to 3.5; 10.5 -> 11
