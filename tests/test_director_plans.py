"""The deterministic parts of the director: plan checks, schemas, scaffolding, state, craft."""

from __future__ import annotations

import copy
import json

import pytest
from director_world import SHOTPLAN, STORY, info, make_cast, shot

from director import craft
from director import state as st
from director.assets import import_assets
from director.checks import shot_missing, stage_complete
from director.hub import compact
from director.plans import (
    Capabilities,
    check_shotplan,
    check_story,
    shotplan_schema,
    story_schema,
    words,
)
from director.stages.audio import pick_voice
from director.stages.shots import fit_lines, positions, scaffold_steps
from director.toolview import ToolView
from studio_core import safety

CAPS = Capabilities(
    motions=["blink", "idle_breathe", "wave", "nod"],
    expressions=["neutral", "happy"],
    camera_moves=["static", "push_in"],
    moods=["playful", "calm"],
)


def story(**changes):
    s = copy.deepcopy(STORY)
    s.update(changes)
    return s


def test_a_good_story_has_no_problems():
    assert check_story(STORY, 15, safety.blocked_words) == []


@pytest.mark.parametrize(
    ("mutate", "expect"),
    [
        (lambda s: s["scenes"][0].update(seconds=20), "add up to 28"),
        (lambda s: s["scenes"][0].update(id="s15"), "scene ids must be ['s01', 's02']"),
        (lambda s: s["scenes"][0].update(place="moon"), "place 'moon' is not in places"),
        (
            lambda s: s["scenes"][0].update(characters=["kit", "ghost"]),
            "'ghost' is not in characters",
        ),
        (
            lambda s: s["scenes"][0]["lines"][0].update(text=" ".join(["la"] * 13)),
            "more than 12 words",
        ),
        (lambda s: s["characters"].append(copy.deepcopy(s["characters"][0])), "ids must be unique"),
        (
            lambda s: s["scenes"][1].update(characters=["kit"]),
            "'bo' speaks but is not in the scene",
        ),
        (lambda s: s["scenes"][0].update(summary="A bloody fight."), "not allowed"),
    ],
)
def test_story_problems_are_named(mutate, expect):
    s = story()
    mutate(s)
    problems = check_story(s, 15, safety.blocked_words)
    assert any(expect in p for p in problems), problems


def test_a_character_in_no_scene_and_a_long_film_are_caught():
    s = story()
    s["characters"].append({**s["characters"][0], "id": "pim"})
    assert any("'pim' appears in no scene" in p for p in check_story(s, 15, safety.blocked_words))
    assert any("must be about 60" in p for p in check_story(STORY, 60, safety.blocked_words))


def test_the_story_schema_only_allows_known_moods():
    schema = story_schema(CAPS)
    assert schema["properties"]["scenes"]["items"]["properties"]["mood"] == {
        "enum": ["playful", "calm"]
    }
    assert schema["properties"]["characters"]["maxItems"] == 3


def test_the_shotplan_schema_is_built_from_what_the_tools_can_do():
    schema = shotplan_schema(STORY, CAPS)
    member = schema["properties"]["shots"]["items"]["properties"]["characters"]["items"][
        "properties"
    ]
    assert member["does"]["enum"] == ["wave", "nod"]  # blink and idle are never the plan's choice
    assert member["id"]["enum"] == ["kit", "bo"] and member["expression"]["enum"] == [
        "neutral",
        "happy",
    ]
    assert schema["properties"]["shots"]["items"]["properties"]["camera"]["enum"] == [
        "static",
        "push_in",
    ]


def test_a_good_shotplan_has_no_problems_and_bad_ones_are_named():
    assert check_shotplan(SHOTPLAN, STORY, 15) == []
    bad = copy.deepcopy(SHOTPLAN)
    bad["shots"][1]["line"]["text"] = "Something else entirely"
    bad["shots"][2]["characters"][0]["id"] = "pim"
    bad["shots"][3]["id"] = "s01_sh09"
    problems = " | ".join(check_shotplan(bad, STORY, 15))
    assert "is not one of scene s01's lines" in problems and "'pim' is not in scene s02" in problems
    assert "must start with its scene id" in problems and "is in 0 shots" in problems
    short = copy.deepcopy(SHOTPLAN)
    short["shots"] = short["shots"][:2]
    assert any("add up to" in p for p in check_shotplan(short, STORY, 15))
    assert any("scene s02 has no shots" in p for p in check_shotplan(short, STORY, 15))


def test_fit_lines_extends_a_shot_to_outlast_its_recording():
    plan = copy.deepcopy(SHOTPLAN)
    lines = [{"scene": "s01", "text": "Look at the red balloon!", "duration_s": 3.2}]
    fit_lines(plan, lines, {})
    assert plan["shots"][1]["seconds"] == 4.5  # 0.6 lead + 3.2 + 0.6 tail, rounded up to 0.5
    assert plan["shots"][0]["seconds"] == 3  # no line, untouched
    lines[0]["duration_s"] = 30
    fit_lines(plan, lines, {})
    assert plan["shots"][1]["seconds"] == 8  # never past the cap


def test_positions_and_scaffold_follow_the_rules():
    two = shot("s01_sh01", "s01", 4)["characters"]
    assert positions(two) == {"kit": 0.3, "bo": 0.7}
    same = [{**two[0], "where": "left"}, {**two[1], "where": "left"}]
    assert positions(same) == {"kit": 0.3, "bo": 0.7}  # a collision is spread out
    planned = {
        **shot("s01_sh02", "s01", 4, {"who": "kit", "text": "Look at the red balloon!"}),
        "place": "orchard",
    }
    steps = scaffold_steps(planned, {"look at the red balloon": "l001"}, "m01")
    tools = [t for t, _ in steps]
    assert tools[0] == "create_scene" and steps[0][1]["replace"] is True
    for who in ("kit", "bo"):
        motions = [
            a["motion"] for t, a in steps if t == "apply_motion" and a["character_id"] == who
        ]
        assert motions[:2] == ["blink", "idle_breathe"]  # every character, every shot
    facing = {a["character_id"]: a["facing"] for t, a in steps if t == "add_character"}
    assert facing == {"kit": "right", "bo": "left"}  # they face each other
    assert ("apply_lipsync", {"character_id": "kit", "line_id": "l001", "start_s": 0.6}) in steps
    assert steps[-1] == ("set_music", {"cue_id": "m01", "volume": 0.4})


def test_a_walking_character_gets_move_and_walk_cycle_over_the_same_span():
    planned = {"id": "s01_sh01", "seconds": 5, "place": "orchard", "camera": "static", "beat": "x"}
    planned["characters"] = [
        {"id": "kit", "where": "left", "moves_to": "right", "does": "wave", "expression": "happy"}
    ]
    steps = scaffold_steps(planned, {}, None)
    move = next(a for t, a in steps if t == "move_character")
    walk = next(a for t, a in steps if t == "apply_motion" and a["motion"] == "walk_cycle")
    assert (
        (move["start_s"], move["duration_s"]) == (walk["start_s"], walk["duration_s"]) == (0.4, 4.2)
    )
    assert not any(a.get("motion") == "wave" for _, a in steps)


def test_voices_are_distinct_and_must_be_installed():
    installed = ["af_heart", "am_puck", "af_nicole"]
    first = pick_voice("child_high", set(), installed)
    second = pick_voice("child_high", {first["id"]}, installed)
    assert first["id"] == "af_heart" and second["id"] == "af_nicole"
    assert (
        pick_voice("gentle_adult", set(), installed)["id"] == "af_heart"
    )  # nothing else installed


def test_state_is_saved_atomically_and_round_trips(tmp_path):
    state = st.DirectorState(film="f", prompt="p", target_seconds=60)
    state.stage("story").per_item["kit"] = "built"
    state.counters.model_calls = 3
    st.save(tmp_path, state)
    assert not list((tmp_path / "director").glob("*.tmp"))
    again = st.load(tmp_path)
    assert again == state and again.stage("story").per_item == {"kit": "built"}
    assert json.loads(st.state_file(tmp_path).read_text())["schema_version"] == 1
    a, b = st.Counters(model_calls=5, tool_calls=2), st.Counters(model_calls=2)
    assert st.counters_delta(a, b).model_calls == 3
    st.counters_add(b, a)
    assert b.model_calls == 7


def test_stage_checks_name_what_is_missing(tmp_path):
    film = make_cast(tmp_path, "f")
    assert "story.json is missing" in stage_complete("story", film, 15)
    (film / "story").mkdir()
    (film / "story" / "story.json").write_text(json.dumps(STORY))
    assert "outline.json is missing" in stage_complete("story", film, 15)
    for n in ("outline", "characters", "places"):
        (film / "story" / f"{n}.json").write_text("{}")
    assert "safety check" in stage_complete("story", film, 15)
    (film / "story" / "safety.json").write_text('{"ok": true}')
    assert stage_complete("story", film, 15) is None
    assert (
        stage_complete("characters", film, 15) is None
        and stage_complete("backgrounds", film, 15) is None
    )
    (film / "backgrounds" / "orchard" / "layers.json").write_text('{"layers": [{}]}')
    assert "1 parallax layers" in stage_complete("backgrounds", film, 15)
    (film / "characters" / "bo" / "rig.json").unlink()
    assert "bo has no rig.json" in stage_complete("characters", film, 15)
    assert "lines" in stage_complete("audio", film, 15) or "recorded" in stage_complete(
        "audio", film, 15
    )
    assert "shotplan.json is missing" in stage_complete("shots", film, 15)


def test_shot_missing_requires_blink_idle_the_line_and_a_render(tmp_path):
    film = make_cast(tmp_path, "f")
    planned = {"id": "s01_sh01", "line": {"who": "kit", "text": "Hi"}}
    assert "no shot.json" in shot_missing(film, planned)
    kit = {"id": "kit", "position": [0.5, 0.9], "actions": [{"motion": "blink", "start_s": 0}]}
    spec = {
        "schema_version": 1,
        "id": "s01_sh01",
        "duration_s": 4,
        "background": "orchard",
        "dialogue": [],
        "characters": [kit],
    }
    folder = film / "shots" / "s01_sh01"
    folder.mkdir(parents=True)
    (folder / "shot.json").write_text(json.dumps(spec))
    assert "kit needs idle_breathe" in shot_missing(film, planned)
    spec["characters"][0]["actions"].append({"motion": "idle_breathe", "start_s": 0})
    (folder / "shot.json").write_text(json.dumps(spec))
    assert "must have the line" in shot_missing(film, planned)
    spec["dialogue"] = [{"character": "kit", "line_id": "l001", "text": "Hi", "start_s": 0.6}]
    (folder / "shot.json").write_text(json.dumps(spec))
    assert "not rendered" in shot_missing(film, planned)
    (folder / "shot.mp4").write_bytes(b"x")
    assert shot_missing(film, planned) is None


def test_the_craft_index_and_notes(tmp_path):
    names = craft.topics()
    assert {"motion-choice", "blink-and-idle", "lip-sync", "what-fails"} <= set(names)
    assert all(names.values()), "every note has a '> one line' summary"
    assert "- staging: " in craft.index()
    assert craft.read_craft("Blink and idle").startswith("# Blink and idle")
    assert "Topics:" in craft.read_craft("juggling")
    big = tmp_path / "big.md"
    big.write_text("# Big\n> x\n" + "word " * 2000)
    assert len(craft.read_craft("big", tmp_path)) <= 2400


def test_tool_views_hide_what_code_fills_in_and_limit_the_list():
    available = {n: info(n, True) for n in ("create_scene", "render_shot", "speak", "check_frame")}
    view = ToolView.for_stage("shots", available)
    assert view.names() == ["check_frame", "create_scene", "read_craft", "render_shot"]  # not speak
    fn = {t["function"]["name"]: t["function"]["parameters"] for t in view.ollama_tools()}
    assert (
        "film" not in fn["create_scene"]["properties"]
        and "shot_id" not in fn["render_shot"]["properties"]
    )
    assert ToolView.for_stage("audio", available).names() == []


def test_long_tool_results_are_cut_for_the_model():
    assert compact({"a": 1}) == '{"a":1}'
    cut = compact("x" * 5000)
    assert len(cut) < 2500 and "5000 characters in all" in cut


def test_words_counts_contractions_as_one():
    assert words("Let's go, Bo!") == 3


def test_importing_assets_copies_a_puppet_and_registers_it(tmp_path):
    src = make_cast(tmp_path, "src")
    (tmp_path / "dst").mkdir()
    (tmp_path / "dst" / "film.json").write_text(json.dumps({"characters": []}))
    assert import_assets(tmp_path, "dst", "src:kit", "characters") == ["kit"]
    assert (tmp_path / "dst" / "characters" / "kit" / "rig.json").is_file()
    assert json.loads((tmp_path / "dst" / "film.json").read_text())["characters"] == ["kit"]
    assert import_assets(tmp_path, "dst", "src:orchard", "backgrounds") == [
        "orchard"
    ]  # repeat-safe
    assert import_assets(tmp_path, "dst", "src:kit", "characters") == ["kit"]
    with pytest.raises(FileNotFoundError):
        import_assets(tmp_path, "dst", "src:nobody", "characters")
    _ = src
