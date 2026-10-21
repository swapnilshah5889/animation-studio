"""Schemas + semantic checks: the valid examples pass; each kind of mistake gets a precise issue."""

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest

from studio_core.config import REPO_ROOT
from studio_core.schema import Issue, validate

FIX = REPO_ROOT / "tests" / "fixtures" / "schemas"
EXAMPLES = {
    "rig": "rig_pip.json",
    "shot": "shot_s01_sh01.json",
    "shotlist": "shotlist_kite_day.json",
    "film": "film_kite_day.json",
}


def example(name: str) -> dict[str, Any]:
    return json.loads((FIX / EXAMPLES[name]).read_text())


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_examples_are_valid(name: str) -> None:
    assert validate(name, example(name)) == []


def front(rig: dict) -> dict:
    return rig["views"]["front"]


Mutation = Callable[[dict], None]
CASES: list[tuple[str, str, Mutation, str, str]] = [
    # (schema, case, mutation, expected path fragment, expected message fragment)
    ("rig", "bad id", lambda r: r.update(id="Pip!"), "id", "does not match"),
    (
        "rig",
        "missing front view",
        lambda r: r["views"].pop("front"),
        "views",
        "'front' is a required",
    ),
    ("rig", "extra field", lambda r: r.update(colour="red"), "", "Additional properties"),
    (
        "rig",
        "two roots",
        lambda r: front(r)["bones"]["head"].update(parent=None),
        "views.front.root",
        "exactly one bone",
    ),
    (
        "rig",
        "unknown parent",
        lambda r: front(r)["bones"]["forearm_l"].update(parent="elbow"),
        "forearm_l.parent",
        "unknown bone",
    ),
    (
        "rig",
        "joint on the wrong part",
        lambda r: front(r)["bones"]["forearm_l"]["attach"].update(part="torso"),
        "forearm_l.attach.part",
        "must attach to a part of the parent bone",
    ),
    (
        "rig",
        "joint outside the image",
        lambda r: front(r)["bones"]["head"]["attach"].update(at_px=[900, 18]),
        "head.attach.at_px",
        "outside",
    ),
    (
        "rig",
        "cycle",
        lambda r: (
            front(r)["bones"]["upper_arm_l"].update(parent="forearm_l"),
            front(r)["bones"]["upper_arm_l"]["attach"].update(part="forearm_l"),
        ),
        "upper_arm_l.parent",
        "cycle",
    ),
    (
        "rig",
        "draw order missing a part",
        lambda r: front(r)["draw_order"].remove("head"),
        "draw_order",
        "missing ['head']",
    ),
    (
        "rig",
        "face anchor off the head",
        lambda r: front(r)["face"]["mouth"].update(at_px=[110, 999]),
        "face.mouth.at_px",
        "outside",
    ),
    (
        "shot",
        "unknown motion",
        lambda s: s["characters"][0]["actions"][2].update(motion="wavee"),
        "actions[2].motion",
        "is not one of",
    ),
    (
        "shot",
        "unknown param",
        lambda s: s["characters"][0]["actions"][2]["params"].update(speed=2),
        "actions[2].params",
        "Additional",
    ),
    (
        "shot",
        "position far outside",
        lambda s: s["characters"][0].update(position=[3, 0.9]),
        "characters[0].position[0]",
        "maximum",
    ),
    ("shot", "bad shot id", lambda s: s.update(id="shot1"), "id", "does not match"),
    (
        "shot",
        "action after the end",
        lambda s: s["characters"][0]["actions"][2].update(start_s=12),
        "actions[2].start_s",
        "not inside",
    ),
    (
        "shot",
        "action runs past the end",
        lambda s: s["characters"][0]["actions"][2].update(duration_s=9.5),
        "actions[2].duration_s",
        "past the end",
    ),
    (
        "shot",
        "speaker not in shot",
        lambda s: s["dialogue"][0].update(character="bunny"),
        "dialogue[0].character",
        "not in this shot",
    ),
    (
        "shot",
        "camera past the end",
        lambda s: s["camera"].update(start_s=8, duration_s=4),
        "camera",
        "past the end",
    ),
    (
        "shotlist",
        "duplicate shot ids",
        lambda d: d["shots"][1].update(id="s01_sh01"),
        "shots",
        "used twice",
    ),
    (
        "shotlist",
        "bad shot inside list",
        lambda d: d["shots"][1]["characters"][0]["actions"][0].update(motion="dance"),
        "shots[1].characters[0].actions[0].motion",
        "is not one of",
    ),
    (
        "film",
        "bad stage status",
        lambda f: f["stages"].update(story="finished"),
        "stages.story",
        "is not one of",
    ),
]


@pytest.mark.parametrize(
    ("name", "case", "mutate", "path", "message"), CASES, ids=[c[1] for c in CASES]
)
def test_mistakes_are_reported_precisely(
    name: str, case: str, mutate: Mutation, path: str, message: str
) -> None:
    data = copy.deepcopy(example(name))
    mutate(data)
    issues = validate(name, data)
    assert issues, f"{case}: expected an issue"
    assert any(path in i.path and message in i.message for i in issues), [str(i) for i in issues]


def test_issue_text_is_readable() -> None:
    assert str(Issue("characters[0].position", "too big")) == "characters[0].position: too big"
    assert str(Issue("", "not valid JSON")) == "(root): not valid JSON"


def test_unknown_schema_name() -> None:
    with pytest.raises(ValueError):
        validate("storyboard", {})
