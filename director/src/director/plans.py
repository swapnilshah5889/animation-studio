"""Structured planning: the model writes a *plan* as JSON that must fit a schema; code checks sense.

Ollama's `format` makes decoding obey a JSON Schema, so the reply is always valid JSON of the right
shape (syntax). It cannot know that a scene's place exists or that the seconds add up (sense), so
after parsing, `check_story` / `check_shotplan` look at the content and name every problem. The
model gets those problems once, with thinking on; a second failure ends the stage (loop-free).
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from director.chat import ChatFn
from director.config import DURATION_TOLERANCE, SHOT_SECONDS
from director.log import EventFn
from director.state import Counters

ID = {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,19}$"}
WHERE = ["left", "center", "right"]
MAX_WORDS = 12


class PlanError(RuntimeError):
    """The model could not produce a plan that passes the checks."""


@dataclass
class Capabilities:
    """What the tools can do (describe_* results). A plan may only use these (D-065 part 4)."""

    motions: list[str] = field(default_factory=list)
    expressions: list[str] = field(default_factory=list)
    camera_moves: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)

    def planning_motions(self) -> list[str]:
        """blink and idle_breathe are added by code to every character: never the plan's choice."""
        return [m for m in self.motions if m not in ("blink", "idle_breathe")]


def story_schema(caps: Capabilities, max_scenes: int = 4) -> dict[str, Any]:
    line = {
        "type": "object",
        "required": ["who", "text"],
        "additionalProperties": False,
        "properties": {"who": ID, "text": {"type": "string", "minLength": 2, "maxLength": 90}},
    }
    scene = {
        "type": "object",
        "required": ["id", "place", "summary", "seconds", "characters", "lines", "mood", "energy"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "pattern": "^s[0-9]{2}$"},
            "place": ID,
            "summary": {"type": "string", "maxLength": 240},
            "seconds": {"type": "integer", "minimum": 4, "maximum": 40},
            "characters": {"type": "array", "items": ID, "minItems": 1, "maxItems": 3},
            "lines": {"type": "array", "items": line, "maxItems": 6},
            "mood": {"enum": caps.moods} if caps.moods else {"type": "string"},
            "energy": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    char = {
        "type": "object",
        "required": ["id", "name", "description", "voice_hint", "role"],
        "additionalProperties": False,
        "properties": {
            "id": ID,
            "name": {"type": "string", "maxLength": 20},
            "description": {"type": "string", "maxLength": 200},
            "voice_hint": {"enum": ["child_high", "child_low", "warm_adult", "gentle_adult"]},
            "role": {"type": "string", "maxLength": 80},
        },
    }
    place = {
        "type": "object",
        "required": ["id", "description", "time_of_day"],
        "additionalProperties": False,
        "properties": {
            "id": ID,
            "description": {"type": "string", "maxLength": 200},
            "time_of_day": {"enum": ["morning", "day", "afternoon", "sunset"]},
        },
    }
    return {
        "type": "object",
        "required": ["title", "logline", "characters", "places", "scenes"],
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string", "maxLength": 60},
            "logline": {"type": "string", "maxLength": 240},
            "characters": {"type": "array", "items": char, "minItems": 1, "maxItems": 3},
            "places": {"type": "array", "items": place, "minItems": 1, "maxItems": 2},
            "scenes": {"type": "array", "items": scene, "minItems": 1, "maxItems": max_scenes},
        },
    }


def words(text: str) -> int:
    return len(re.findall(r"[\w']+", text))


def norm(text: str) -> str:
    return " ".join(re.findall(r"[\w']+", text.lower()))


def check_story(
    story: dict[str, Any], target: int, blocked: Callable[[str], list[str]]
) -> list[str]:
    """Every problem with a story plan, each phrased as an instruction to the model."""
    out: list[str] = []
    chars = [c["id"] for c in story["characters"]]
    places = [p["id"] for p in story["places"]]
    scenes = story["scenes"]
    for kind, ids in (
        ("character", chars),
        ("place", places),
        ("scene", [s["id"] for s in scenes]),
    ):
        if len(set(ids)) != len(ids):
            out.append(f"{kind} ids must be unique, got {ids}.")
    total = sum(s["seconds"] for s in scenes)
    if abs(total - target) > DURATION_TOLERANCE * target:
        out.append(
            f"scene seconds add up to {total} but the film must be about {target} s "
            f"(within {round(DURATION_TOLERANCE * 100)}%). Change the scene seconds."
        )
    for s in scenes:
        if s["place"] not in places:
            out.append(f"scene {s['id']}: place {s['place']!r} is not in places {places}.")
        for c in s["characters"]:
            if c not in chars:
                out.append(f"scene {s['id']}: character {c!r} is not in characters {chars}.")
        for ln in s["lines"]:
            if ln["who"] not in s["characters"]:
                out.append(f"scene {s['id']}: {ln['who']!r} speaks but is not in the scene.")
            if words(ln["text"]) > MAX_WORDS:
                out.append(
                    f"scene {s['id']}: the line {ln['text']!r} has more than {MAX_WORDS} words."
                )
    used = {c for s in scenes for c in s["characters"]}
    out += [f"character {c!r} appears in no scene." for c in chars if c not in used]
    unused = [p for p in places if p not in {s["place"] for s in scenes}]
    out += [f"place {p!r} is used by no scene." for p in unused]
    text = " ".join(
        [story["title"], story["logline"]]
        + [c["description"] for c in story["characters"]]
        + [p["description"] for p in story["places"]]
        + [s["summary"] for s in scenes]
        + [ln["text"] for s in scenes for ln in s["lines"]]
    )
    if bad := blocked(text):
        out.append(
            f"these words are not allowed in a children's film: {sorted(set(bad))}. Rewrite."
        )
    return out


def shotplan_schema(story: dict[str, Any], caps: Capabilities) -> dict[str, Any]:
    """Enums are built at run time from the capability list: the model can only name motions,
    expressions and camera moves that exist, and only characters that are in the story."""
    cast = [c["id"] for c in story["characters"]]
    member = {
        "type": "object",
        "required": ["id", "where", "does", "expression"],
        "additionalProperties": False,
        "properties": {
            "id": {"enum": cast},
            "where": {"enum": WHERE},
            "moves_to": {"enum": WHERE},
            "does": {"enum": caps.planning_motions() or ["nod"]},
            "expression": {"enum": caps.expressions or ["neutral"]},
        },
    }
    line = {
        "type": "object",
        "required": ["who", "text"],
        "additionalProperties": False,
        "properties": {"who": {"enum": cast}, "text": {"type": "string"}},
    }
    shot = {
        "type": "object",
        "required": ["id", "scene", "seconds", "beat", "characters", "camera"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "pattern": "^s[0-9]{2}_sh[0-9]{2}$"},
            "scene": {"enum": [s["id"] for s in story["scenes"]]},
            "seconds": {"type": "number", "minimum": SHOT_SECONDS[0], "maximum": SHOT_SECONDS[1]},
            "beat": {"type": "string", "maxLength": 160},
            "characters": {"type": "array", "items": member, "minItems": 1, "maxItems": 3},
            "line": line,
            "camera": {"enum": caps.camera_moves or ["static"]},
            "sfx": {"type": "string", "maxLength": 60},
        },
    }
    return {
        "type": "object",
        "required": ["shots"],
        "additionalProperties": False,
        "properties": {"shots": {"type": "array", "items": shot, "minItems": 1, "maxItems": 16}},
    }


def check_shotplan(plan: dict[str, Any], story: dict[str, Any], target: int) -> list[str]:
    out: list[str] = []
    shots = plan["shots"]
    ids = [s["id"] for s in shots]
    if len(set(ids)) != len(ids):
        out.append("shot ids must be unique.")
    total = sum(s["seconds"] for s in shots)
    if abs(total - target) > DURATION_TOLERANCE * target:
        out.append(
            f"shot seconds add up to {round(total, 1)} but the film must be about {target} s "
            f"(within {round(DURATION_TOLERANCE * 100)}%). Change shots or seconds."
        )
    scenes = {s["id"]: s for s in story["scenes"]}
    placed: dict[tuple[str, str], int] = {}
    for sh in shots:
        scene = scenes.get(sh["scene"])
        if scene is None:
            continue
        if not sh["id"].startswith(sh["scene"] + "_"):
            out.append(f"shot {sh['id']} must start with its scene id, e.g. {sh['scene']}_sh01.")
        who = [m["id"] for m in sh["characters"]]
        for m in who:
            if m not in scene["characters"]:
                out.append(f"shot {sh['id']}: {m!r} is not in scene {scene['id']}.")
        if len(set(who)) != len(who):
            out.append(f"shot {sh['id']}: a character appears twice.")
        if ln := sh.get("line"):
            key = (scene["id"], norm(ln["text"]))
            if key not in {(scene["id"], norm(x["text"])) for x in scene["lines"]}:
                out.append(
                    f"shot {sh['id']}: {ln['text']!r} is not one of scene {scene['id']}'s lines. "
                    "Copy a line exactly."
                )
            elif ln["who"] not in who:
                out.append(f"shot {sh['id']}: {ln['who']!r} speaks but is not in the shot.")
            placed[key] = placed.get(key, 0) + 1
    for scene in scenes.values():
        if not any(s["scene"] == scene["id"] for s in shots):
            out.append(f"scene {scene['id']} has no shots.")
        for x in scene["lines"]:
            if placed.get((scene["id"], norm(x["text"]))) != 1:
                out.append(
                    f"the line {x['text']!r} (scene {scene['id']}) must be in exactly one shot."
                )
    return out


async def plan_json(
    chat: ChatFn,
    system: str,
    user: str,
    schema: dict[str, Any],
    check: Callable[[dict[str, Any]], list[str]],
    *,
    on_event: EventFn,
    counters: Counters,
    retries: int = 1,
) -> dict[str, Any]:
    """One schema-forced planning call, with `retries` rounds of "these problems: fix them".
    Thinking is on: planning is where a 14B model needs it (design §2)."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    problems: list[str] = []
    for attempt in range(retries + 1):
        reply = await chat(messages, think=True, format=copy.deepcopy(schema))
        counters.model_calls += 1
        counters.prompt_tokens += reply.prompt_tokens
        counters.output_tokens += reply.output_tokens
        counters.llm_seconds += reply.seconds
        on_event(
            {
                "kind": "model",
                "seconds": round(reply.seconds, 1),
                "text": reply.content[:200],
                "tool_calls": 0,
                "prompt_tokens": reply.prompt_tokens,
                "output_tokens": reply.output_tokens,
                "plan_attempt": attempt,
            }
        )
        try:
            plan = json.loads(reply.content)
        except json.JSONDecodeError as err:
            problems = [f"the reply was not valid JSON ({err.msg})."]
        else:
            problems = check(plan)
            if not problems:
                return plan
        messages += [
            {"role": "assistant", "content": reply.content},
            {
                "role": "user",
                "content": "Fix these problems and answer again with the whole plan:\n- "
                + "\n- ".join(problems),
            },
        ]
    raise PlanError("; ".join(problems))
