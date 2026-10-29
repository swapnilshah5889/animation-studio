"""The prompts, JSON schemas and answer parsing for the vision model's two jobs: judging a frame
against its shot spec, and judging text or a picture against a children's-content rubric.

Pure functions: no Ollama here, so the prompt text and the parsing are unit-tested. The model's
answers are advisory; `runner.py` combines them with the code checks (facts).
"""

from __future__ import annotations

import json
from typing import Any

# The fixed rubric (age 3-8). A category is only listed when it clearly or possibly applies.
SAFETY_CATEGORIES: dict[str, str] = {
    "violence": "hitting, fighting, weapons, injury, blood, cruelty",
    "fear": "frightening threats, being lost or hunted in a way a small child would find scary",
    "sexual_content": "nudity, romance beyond a hug or friendly kiss, innuendo",
    "hate": "insults, slurs, mocking people for who they are, stereotypes",
    "adult_themes": "drugs, alcohol, smoking, gambling, death or grief handled graphically",
    "dangerous_behaviour": "something a child could copy and get hurt (fire, climbing, medicine)",
    "scary_imagery": "monsters, gore, dark menacing scenes, distorted or creepy faces",
}


def rubric_text() -> str:
    return "\n".join(f"- {name}: {what}" for name, what in SAFETY_CATEGORIES.items())


SAFETY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {"type": "string", "enum": list(SAFETY_CATEGORIES)},
        },
        "reasons": {"type": "array", "items": {"type": "string"}},
        "unsure": {"type": "boolean"},
    },
    "required": ["categories", "reasons", "unsure"],
}


def safety_prompt(*, text: str | None = None, has_image: bool = False) -> str:
    what = []
    if text:
        what.append(f'this text:\n"""\n{text}\n"""')
    if has_image:
        what.append("the attached picture")
    return (
        "You check material for a children's animated film. The audience is children aged 3 to 8. "
        f"Judge {' and '.join(what)} against this rubric:\n{rubric_text()}\n\n"
        "List in `categories` every rubric category that applies, even mildly; leave it empty when "
        "the material is fine for a 3-year-old. Give one short reason per category in `reasons`. "
        "Set `unsure` to true when you cannot tell. Gentle cartoon silliness, friendly "
        "animals and mild peril that resolves at once are fine. Answer in JSON only."
    )


def frame_schema(character_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": character_ids},
                        "present": {"type": "boolean"},
                        "expression_plausible": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "present", "expression_plausible", "reason"],
                },
            },
            "background_present": {"type": "boolean"},
            "background_reason": {"type": "string"},
            "problems": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "description",
            "characters",
            "background_present",
            "background_reason",
            "problems",
        ],
    }


def active_at(actions: list[dict[str, Any]], t: float) -> list[str]:
    """Motions that are running at time t. An action without a duration counts from its start."""
    names = []
    for a in actions:
        start = float(a.get("start_s", 0))
        end = start + float(a["duration_s"]) if a.get("duration_s") else None
        if start <= t and (end is None or t < end):
            names.append(a["motion"])
    return names


def expression_at(expressions: list[dict[str, Any]], t: float) -> str:
    current = "neutral"
    for e in sorted(expressions, key=lambda e: e.get("start_s", 0)):
        if e.get("start_s", 0) <= t:
            current = e["expr"]
    return current


def shot_facts(shot: dict[str, Any], t: float) -> dict[str, Any]:
    """What the shot spec says should be on screen at time t, for the prompt and for tests."""
    chars = []
    for c in shot["characters"]:
        chars.append(
            {
                "id": c["id"],
                "facing": c.get("facing", "right"),
                "expression": expression_at(c.get("expressions", []), t),
                "motions": active_at(c.get("actions", []), t),
                "position": c["position"],
            }
        )
    return {
        "background": shot["background"],
        "camera": shot.get("camera", {}),
        "characters": chars,
    }


def frame_prompt(facts: dict[str, Any], t: float) -> str:
    lines = []
    for c in facts["characters"]:
        x, y = c["position"]
        lines.append(
            f"- {c['id']}: feet at ({x:.2f}, {y:.2f}) of the frame (0,0 = top left), facing "
            f"{c['facing']}, expression should be '{c['expression']}', doing "
            f"{', '.join(c['motions']) or 'nothing'}"
        )
    cam = facts["camera"]
    return (
        f"This is frame at {t:.1f}s of a 2D cut-out animation for children. The shot spec says:\n"
        f"- background: '{facts['background']}' (a painted place)\n"
        f"- camera: {cam.get('move', 'static')}\n"
        + "\n".join(lines)
        + "\n\nDescribe what you see in one or two sentences (`description`). For each listed "
        "character say whether it is `present` and fully visible, and whether its face "
        "`expression_plausible` for the expression named, with a short `reason`. Say whether the "
        "background is present. In `problems` list short strings for anything visibly wrong: "
        "holes or gaps in a character, missing or deformed body parts, a face in the wrong place, "
        "a character cropped by the frame edge, an unreadable pose. Leave `problems` empty when "
        "you see none. Do not invent problems. Answer in JSON only."
    )


class ModelAnswerError(ValueError):
    """The model's answer did not follow the schema."""


def parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ModelAnswerError(f"the model did not answer in JSON: {raw[:120]!r}") from e
    if not isinstance(data, dict):
        raise ModelAnswerError("the model's answer is not a JSON object")
    return data


def parse_safety(raw: str) -> tuple[list[str], list[str], bool]:
    """(categories, reasons, unsure), keeping only known categories."""
    data = parse_json(raw)
    cats = [c for c in data.get("categories", []) if c in SAFETY_CATEGORIES]
    reasons = [str(r) for r in data.get("reasons", [])]
    return sorted(set(cats)), reasons, bool(data.get("unsure", False))


def parse_frame(raw: str, character_ids: list[str]) -> dict[str, Any]:
    """The frame answer, completed: a character the model left out counts as not present."""
    data = parse_json(raw)
    seen = {c.get("id"): c for c in data.get("characters", []) if isinstance(c, dict)}
    chars = []
    for cid in character_ids:
        c = seen.get(cid)
        if c is None:
            chars.append(
                {
                    "id": cid,
                    "present": False,
                    "expression_plausible": False,
                    "reason": "the model did not mention it",
                }
            )
        else:
            chars.append(
                {
                    "id": cid,
                    "present": bool(c.get("present", False)),
                    "expression_plausible": bool(c.get("expression_plausible", False)),
                    "reason": str(c.get("reason", "")),
                }
            )
    return {
        "description": str(data.get("description", "")),
        "characters": chars,
        "background_present": bool(data.get("background_present", False)),
        "background_reason": str(data.get("background_reason", "")),
        "problems": [str(p) for p in data.get("problems", [])],
    }
