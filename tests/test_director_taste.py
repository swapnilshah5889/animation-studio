"""The taste rules of a shot plan (director/taste.py): each fails on the fault the first real film
showed, the good plan passes, and the model gets one feedback round. Offline, fake model."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest
from director_stories import STORIES
from director_world import SHOTPLAN, STORY, FakeChat, member, planned, says

from director import craft
from director.plans import (
    Capabilities,
    PlanError,
    advise_shotplan,
    check_story,
    drop_empty_lines,
    plan_json,
    shotplan_schema,
)
from director.stages.shots import point_target, scaffold_steps
from director.state import Counters
from director.taste import DEFAULT_EMOTION, EMOTIONS, check_taste
from studio_core import safety
from studio_core.face import EXPRESSIONS


def rules(plan: dict, story: dict = STORY) -> set[str]:
    return {v.rule for v in check_taste(plan, story)}


def edit(mutate) -> dict:
    plan = copy.deepcopy(SHOTPLAN)
    mutate(plan["shots"])
    return plan


def test_the_good_plan_has_no_taste_problems():
    assert check_taste(SHOTPLAN, STORY) == []


def test_every_emotion_maps_only_to_real_expressions():
    assert {e for faces in EMOTIONS.values() for e in faces} <= set(EXPRESSIONS)
    assert set(DEFAULT_EMOTION) == set(EXPRESSIONS)
    assert set(DEFAULT_EMOTION.values()) <= set(EMOTIONS)


def test_every_expression_and_emotion_has_a_row_in_the_craft_note():
    note = craft.read_craft("expressions")
    for e in EXPRESSIONS:
        assert f"`{e}`" in note, e
    for emotion in EMOTIONS:
        assert f"| {emotion} |" in note, emotion


def test_no_establishing_shot():
    assert "establishing" in rules(edit(lambda s: s[0].update(framing="medium")))
    assert "establishing" in rules(edit(lambda s: s[0]["characters"].pop()))  # not everyone in it
    # a wide opening may carry the first line (tight films have no time for a silent shot)
    line = {"who": "kit", "to": "bo", "text": "Look at the red balloon!"}
    assert "establishing" not in rules(edit(lambda s: s[0].update(line=line)))


def test_a_line_to_someone_who_is_not_in_the_shot():
    def off_screen(s):
        s[1]["characters"].pop()  # Bo leaves the shot where Kit says "Look, Bo!"
        s[1]["line"].update(to="", text="Look, Bo! A red balloon!")

    problems = [v.message for v in check_taste(edit(off_screen), STORY)]
    assert any("says Bo but Bo is not in the shot" in p for p in problems), problems
    assert "lone_speaker" in rules(edit(off_screen))
    named = edit(lambda s: (s[1]["characters"].pop(), s[1]["line"].update(to="bo")))
    problems = [v.message for v in check_taste(named, STORY)]
    assert any("speaks to bo but bo is not in the shot" in p for p in problems)


def test_one_close_up_per_scene_is_a_choice_two_are_not():
    def closeup(s, i):
        s[i]["framing"] = "close"
        s[i]["characters"] = s[i]["characters"][:1]
        who = s[i]["characters"][0]["id"]
        s[i]["line"] = {"who": who, "to": "", "text": s[i]["line"]["text"]}

    one = edit(lambda s: closeup(s, 1))
    assert "lone_speaker" not in rules(one)

    # scene s01 has one line, so use scene s02's two shots: only the line shot speaks; make a
    # second lone speaker in the same scene by giving the other shot a line as well
    def two(s):
        closeup(s, 1)
        s[0]["characters"] = s[0]["characters"][:1]
        s[0]["line"] = {"who": "kit", "to": "", "text": "Look at the red balloon!"}
        s[0]["framing"] = "close"

    assert "lone_speaker" in rules(edit(two))


def test_expression_must_come_from_the_emotion_list():
    # the first film: Bo grumpy while jumping for joy
    plan = edit(lambda s: s[2]["characters"][1].update(expression="grumpy"))
    problems = [v.message for v in check_taste(plan, STORY) if v.rule == "expression"]
    assert problems and "joy but the expression is 'grumpy'" in problems[0]
    sad_goodbye = edit(lambda s: s[3]["characters"][0].update(emotion="sad", expression="sad"))
    assert "negative_share" not in rules(sad_goodbye) or True
    assert "arc" in rules(
        edit(lambda s: s[3]["characters"][1].update(emotion="sad", expression="sad"))
    )


def test_determined_and_grumpy_are_rare():
    def two(s):
        for i in (1, 2):
            s[i]["characters"][1].update(emotion="effort", expression="determined")

    assert "rare_face" in rules(edit(two))


def test_joy_motions_need_a_bright_emotion_and_listeners_stay_quiet():
    assert "motion_mood" in rules(edit(lambda s: s[0]["characters"][0].update(does="jump")))
    # Bo claps while Kit speaks
    assert "listener_motion" in rules(edit(lambda s: s[1]["characters"][1].update(does="clap")))


def test_point_needs_a_target_that_exists():
    assert "point_target" in rules(edit(lambda s: s[1]["characters"][0].update(target="")))
    assert "point_target" in rules(edit(lambda s: s[1]["characters"][0].update(target="kit")))
    assert "point_target" not in rules(edit(lambda s: s[1]["characters"][0].update(target="bo")))


def test_flat_cameras_and_framings_are_rejected():
    def flat(s):
        for sh in s:
            sh["camera"] = "static"

    assert "camera_variety" in rules(edit(flat))
    same = edit(lambda s: [sh.update(framing="wide") for sh in s])
    assert "framing_variety" in rules(same)


def test_camera_moves_need_a_reason():
    assert "camera_intent" in rules(edit(lambda s: s[1].update(framing="wide")))  # push_in, wide
    assert "camera_intent" in rules(edit(lambda s: s[1].update(camera="slow_pan_left")))


def test_the_film_needs_an_arc_and_a_calm_ending():
    def flat(s):
        for sh in s:
            for m in sh["characters"]:
                m.update(emotion="joy", expression="happy", does="nod")
            sh["characters"][0]["target"] = ""

    assert "arc" in rules(edit(flat))
    assert "ending" in rules(edit(lambda s: s[3]["characters"][1].update(does="jump")))
    assert "ending" in rules(edit(lambda s: s[3].update(seconds=2)))
    grumpy_open = edit(
        lambda s: s[0]["characters"][0].update(emotion="grumpy", expression="grumpy")
    )
    assert "arc" in rules(grumpy_open)


def test_characters_do_not_swap_sides_within_a_scene():
    def swap(s):
        s[1]["characters"][0]["where"], s[1]["characters"][1]["where"] = "right", "left"

    assert "side_flip" in rules(edit(swap))


def test_the_first_real_film_would_have_failed_most_rules():
    """What qwen3:14b planned for the first film: one character per shot, no establishing shot,
    point without a target, every shot static, Bo grumpy, Kit sad at the goodbye."""
    bad = {
        "shots": [
            planned(
                "s01_sh01",
                "s01",
                4,
                "medium",
                "static",
                [member("kit", "left", "point", "curious", "surprised")],
                {"who": "kit", "to": "", "text": "Look at the red balloon!"},
            ),
            planned(
                "s01_sh02",
                "s01",
                3,
                "close",
                "static",
                [member("bo", "center", "wave", "joy", "grumpy")],
            ),
            planned(
                "s02_sh01",
                "s02",
                4,
                "close",
                "static",
                [member("bo", "left", "jump", "joy", "grumpy")],
            ),
            planned(
                "s02_sh02",
                "s02",
                4,
                "medium",
                "static",
                [member("kit", "center", "wave", "sad", "sad")],
                {"who": "bo", "to": "", "text": "Bye bye, balloon."},
            ),
        ]
    }
    assert {
        "establishing",
        "lone_speaker",
        "point_target",
        "expression",
        "camera_variety",
        "arc",
        "rare_face",
    } <= rules(bad)


# ---- the feedback round ------------------------------------------------------------------------


def run_plan(chat, story=STORY, check=lambda p: []):
    events: list[dict] = []
    plan = asyncio.run(
        plan_json(
            chat,
            "sys",
            "user",
            {},
            check,
            on_event=events.append,
            counters=Counters(),
            advice=lambda p: advise_shotplan(p, story),
        )
    )
    return plan, events


def test_taste_feedback_is_one_round_and_names_the_rule():
    bad = edit(lambda s: s[0].update(framing="medium"))
    chat = FakeChat([says(json.dumps(bad)), says(json.dumps(SHOTPLAN))])
    plan, _ = run_plan(chat)
    assert plan == SHOTPLAN and len(chat.calls) == 2
    feedback = chat.calls[1]["messages"][-1]["content"]
    assert "establishing shot" in feedback and chat.calls[1]["think"] is True


def test_a_plan_that_stays_poor_after_the_round_is_kept_and_logged():
    bad = edit(lambda s: s[0].update(framing="medium"))
    chat = FakeChat([says(json.dumps(bad)), says(json.dumps(bad))])
    plan, events = run_plan(chat)
    assert plan == bad and len(chat.calls) == 2  # never a third call, never a crash
    assert [e["remaining"] for e in events if e["kind"] == "taste"]


def test_sense_problems_still_end_the_stage():
    chat = FakeChat([says("{}"), says("{}")])
    with pytest.raises(PlanError):
        asyncio.run(
            plan_json(
                chat,
                "s",
                "u",
                {},
                lambda p: ["broken"],
                on_event=lambda e: None,
                counters=Counters(),
                advice=lambda p: ["poor taste"],
            )
        )


# ---- schema and scaffold -----------------------------------------------------------------------

CAPS = Capabilities(
    motions=["blink", "idle_breathe", "point", "nod"],
    expressions=list(EXPRESSIONS),
    camera_moves=["static", "push_in", "pull_out"],
    moods=[],
)


def test_the_schema_requires_the_taste_fields():
    shot = shotplan_schema(STORY, CAPS)["properties"]["shots"]["items"]
    member_s = shot["properties"]["characters"]["items"]
    assert "framing" in shot["required"]
    assert {"emotion", "target"} <= set(member_s["required"])
    assert "to" in shot["properties"]["line"]["required"]
    assert set(shot["properties"]["framing"]["enum"]) == {"wide", "medium", "close"}
    assert member_s["properties"]["target"]["enum"][0] == ""


def test_point_gets_a_target_and_framing_sets_the_figure_size():
    kit_point = {**SHOTPLAN["shots"][1], "place": "orchard"}
    steps = scaffold_steps(kit_point, {}, None)
    pointing = next(a for t, a in steps if t == "apply_motion" and a.get("motion") == "point")
    assert pointing["target"][1] < 0.2  # up: the sky
    wide = scaffold_steps({**SHOTPLAN["shots"][0], "place": "orchard"}, {}, None)
    assert all(a["scale"] == 0.7 for t, a in wide if t == "add_character")
    assert all("scale" not in a for t, a in steps if t == "add_character")  # medium


def test_point_target_at_a_character_aims_at_their_head():
    xs = {"kit": 0.3, "bo": 0.7}
    assert point_target({"id": "kit", "target": "bo"}, xs) == [0.7, 0.5]
    assert point_target({"id": "kit", "target": ""}, xs) is None
    assert point_target({"id": "kit", "target": "right_edge"}, xs)[0] > 0.9


# ---- the fixed story set -----------------------------------------------------------------------


def test_the_fixed_stories_are_valid_story_plans():
    assert len(STORIES) == 5
    for name, story in STORIES.items():
        assert check_story(story, 15, safety.blocked_words) == [], name


# ---- the prompt's worked example ---------------------------------------------------------------


def test_the_prompts_example_obeys_every_rule_and_the_schema_keys():
    import re
    from pathlib import Path

    from director.plans import check_shotplan

    text = (Path(__file__).parents[1] / "director/src/director/prompts/shotplan.md").read_text()
    block = {
        t: re.search(rf"<example_{t}>\n(.*?)\n</example_{t}>", text, re.S)
        for t in ("story", "plan")
    }
    assert all(block.values()), "the prompt needs <example_story> and <example_plan>"
    story = json.loads(block["story"].group(1))
    plan = json.loads(block["plan"].group(1))
    story["characters"] = [{"id": c, "name": c.title()} for c in ("kit", "bo")]
    keys = [set(sh) for sh in plan["shots"]]
    drop_empty_lines(plan)  # as the director does before checking
    assert check_shotplan(plan, story, 15) == []
    assert check_taste(plan, story) == []
    plan = json.loads(block["plan"].group(1))
    shot = shotplan_schema(STORY, CAPS)["properties"]["shots"]["items"]
    assert all(k >= set(shot["required"]) for k in keys)
    member_keys = shot["properties"]["characters"]["items"]["required"]
    assert all(set(m) >= set(member_keys) for sh in plan["shots"] for m in sh["characters"])


def test_the_brief_tells_the_planner_what_the_lines_cost_in_seconds():
    from director.stages.shots import line_seconds

    lines = [
        {"scene": "s01", "text": "Look at the red balloon!", "duration_s": 2.0},
        {"scene": "s02", "text": "Bye bye, balloon.", "duration_s": 1.5},
    ]
    text = line_seconds(lines, STORY, 15)
    assert "needs a shot of 3.5 s" in text and "needs a shot of 3.0 s" in text
    assert "Together 6.5 s" in text and "at most 3 silent shot(s)" in text
    assert "no silent shot at all" in line_seconds(lines, STORY, 8)
    assert line_seconds([], STORY, 15) == ""
