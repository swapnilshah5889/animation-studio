"""Fakes for the director tests: a scripted LLM and a fake MCP world that keeps a film folder.

`FakeHub` answers the tools the director uses and writes the files the real servers would, so the
stage checks (checks.py) look at a real folder. Nothing here starts Ollama, an MCP server or a GPU.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from director.chat import ChatReply, ToolCall
from director.hub import ToolInfo, ToolResult

MOTIONS = ["blink", "idle_breathe", "wave", "nod", "walk_cycle", "jump"]
SHOT_TOOLS = [
    "create_scene",
    "add_character",
    "apply_motion",
    "move_character",
    "set_expression",
    "apply_lipsync",
    "camera_move",
    "add_sound_effect",
    "set_music",
    "remove_from_shot",
    "describe_shot",
    "render_preview_frame",
    "render_shot",
    "check_frame",
]
OTHER_TOOLS = [
    "describe_film",
    "describe_audio",
    "describe_art",
    "check_safety",
    "set_voice",
    "speak",
    "compose",
    "find_sfx",
    "assemble",
    "render_film",
    "check_film",
    "design_character",
    "choose_design",
    "build_puppet",
    "generate_background",
    "choose_background",
    "split_depth_layers",
    "preview_background",
]

STORY = {
    "title": "Kit and Bo find a balloon",
    "logline": "Two friends find a red balloon and let it float away.",
    "characters": [
        {
            "id": "kit",
            "name": "Kit",
            "description": "a fox cub",
            "voice_hint": "child_high",
            "role": "curious",
        },
        {
            "id": "bo",
            "name": "Bo",
            "description": "a bear cub",
            "voice_hint": "child_low",
            "role": "kind",
        },
    ],
    "places": [{"id": "orchard", "description": "an apple orchard", "time_of_day": "day"}],
    "scenes": [
        {
            "id": "s01",
            "place": "orchard",
            "summary": "They find a balloon.",
            "seconds": 7,
            "characters": ["kit", "bo"],
            "mood": "playful",
            "energy": 0.4,
            "lines": [{"who": "kit", "text": "Look at the red balloon!"}],
        },
        {
            "id": "s02",
            "place": "orchard",
            "summary": "They let it go.",
            "seconds": 8,
            "characters": ["kit", "bo"],
            "mood": "calm",
            "energy": 0.2,
            "lines": [{"who": "bo", "text": "Bye bye, balloon."}],
        },
    ],
}


def shot(sid: str, scene: str, secs: float, line: dict | None = None) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "id": sid,
        "scene": scene,
        "seconds": secs,
        "beat": "a beat",
        "camera": "static",
        "characters": [
            {"id": "kit", "where": "left", "does": "wave", "expression": "happy"},
            {"id": "bo", "where": "right", "does": "nod", "expression": "happy"},
        ],
    }
    if line:
        plan["line"] = line
    return plan


def member(cid: str, where: str, does: str, emotion: str, expression: str, **more: Any) -> dict:
    return {
        "id": cid,
        "where": where,
        "does": does,
        "target": "",
        "emotion": emotion,
        "expression": expression,
        **more,
    }


def planned(sid, scene, secs, framing, camera, members, line=None, beat="a beat") -> dict:
    out = {
        "id": sid,
        "scene": scene,
        "seconds": secs,
        "beat": beat,
        "framing": framing,
        "camera": camera,
        "characters": members,
    }
    if line:
        out["line"] = line
    return out


# A plan that obeys the craft rules (taste.py): it opens wide, both friends are on screen when
# one speaks to the other, faces follow the feelings, the camera moves with a reason.
SHOTPLAN = {
    "shots": [
        planned(
            "s01_sh01",
            "s01",
            3,
            "wide",
            "static",
            [
                member("kit", "left", "look_around", "calm", "neutral"),
                member("bo", "right", "nod", "calm", "happy"),
            ],
        ),
        planned(
            "s01_sh02",
            "s01",
            4,
            "medium",
            "push_in",
            [
                member("kit", "left", "point", "wonder", "surprised", target="up"),
                member("bo", "right", "head_tilt", "curious", "surprised"),
            ],
            {"who": "kit", "to": "bo", "text": "Look at the red balloon!"},
        ),
        planned(
            "s02_sh01",
            "s02",
            4,
            "medium",
            "static",
            [
                member("kit", "left", "clap", "excited", "excited"),
                member("bo", "right", "jump", "joy", "happy"),
            ],
        ),
        planned(
            "s02_sh02",
            "s02",
            4,
            "medium",
            "pull_out",
            [
                member("kit", "left", "nod", "proud", "proud"),
                member("bo", "right", "talk_gesture", "calm", "happy"),
            ],
            {"who": "bo", "to": "kit", "text": "Bye bye, balloon."},
        ),
    ]
}


class FakeChat:
    """Plays a script. An item is a ChatReply or a function(messages, tools, format)."""

    def __init__(self, script: list[ChatReply | Callable[..., ChatReply]]) -> None:
        self.script, self.calls = list(script), []

    async def __call__(self, messages, *, tools=None, think=False, format=None) -> ChatReply:
        self.calls.append(
            {
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "format": format,
                "think": think,
            }
        )
        item = self.script.pop(0)
        return item(messages, tools, format) if callable(item) else item


def says(text: str = "") -> ChatReply:
    return ChatReply(content=text, prompt_tokens=10, output_tokens=5, seconds=0.1)


def calls(*pairs: tuple[str, Any]) -> ChatReply:
    return ChatReply(
        tool_calls=[ToolCall(n, a) for n, a in pairs],
        prompt_tokens=10,
        output_tokens=5,
        seconds=0.1,
    )


class PipelineChat:
    """Answers whatever the director asks, like a model that behaves: plans, then runs a shot."""

    def __init__(self, story: dict = STORY, plan: dict = SHOTPLAN) -> None:
        self.calls: list[dict] = []
        self._story, self._plan = story, plan

    async def __call__(self, messages, *, tools=None, think=False, format=None) -> ChatReply:
        self.calls.append({"n": len(messages), "format": bool(format), "tools": bool(tools)})
        if format and "scenes" in format["properties"]:
            return says(json.dumps(self._story))
        if format:
            return says(json.dumps(self._plan))
        tool_msgs = [m["tool_name"] for m in messages if m["role"] == "tool"]
        steps = ["describe_shot", "render_preview_frame", "check_frame", "render_shot"]
        step = steps[len(tool_msgs)] if len(tool_msgs) < len(steps) else None
        if step is None:
            return says("Rendered.")
        args: dict[str, Any] = (
            {"time_s": 1.0} if step in ("render_preview_frame", "check_frame") else {}
        )
        if step == "render_shot":
            args["quality"] = "preview"
        return calls((step, args))


def info(name: str, shot_scoped: bool = False) -> ToolInfo:
    props: dict[str, Any] = {"film": {"type": "string"}}
    if shot_scoped:
        props["shot_id"] = {"type": "string"}
    props.update(
        {
            k: {}
            for k in (
                "character_id",
                "time_s",
                "motion",
                "start_s",
                "quality",
                "expr",
                "duration_s",
            )
        }
    )
    return ToolInfo(
        "fake", name, f"{name} tool", {"type": "object", "properties": props, "required": ["film"]}
    )


def tools() -> dict[str, ToolInfo]:
    return {n: info(n, True) for n in SHOT_TOOLS} | {n: info(n) for n in OTHER_TOOLS}


def make_cast(films: Path, slug: str) -> Path:
    """A film folder that already has Kit, Bo and the orchard (the 'existing assets' path)."""
    film = films / slug
    face = {"face": {}}
    for cid in ("kit", "bo"):
        d = film / "characters" / cid
        d.mkdir(parents=True)
        (d / "rig.json").write_text(json.dumps({"views": {"front": face, "three_quarter": face}}))
    d = film / "backgrounds" / "orchard"
    d.mkdir(parents=True)
    (d / "layers.json").write_text(json.dumps({"layers": [{}, {}, {}]}))
    return film


class FakeHub:
    """The MCP side: returns what the real servers return and writes what they write."""

    def __init__(self, film: Path, refuse: dict[str, list[str]] | None = None) -> None:
        self.film = film
        self.tools = tools()
        self.log: list[tuple[str, dict]] = []
        self.refuse = {
            k: list(v) for k, v in (refuse or {}).items()
        }  # tool -> messages, one per call
        self.specs: dict[str, dict] = {}
        self.lines: dict[str, dict] = {}
        self.fail_after_renders: int | None = None  # simulate a crash: raise on this render

    def names(self) -> list[str]:
        return [n for n, _ in self.log]

    async def call(self, tool: str, args: dict[str, Any], on_progress=None) -> ToolResult:
        self.log.append((tool, args))
        if self.refuse.get(tool):
            return ToolResult(self.refuse[tool].pop(0), refused=True)
        data = getattr(self, f"do_{tool}", lambda a: {"ok": True})(args)
        return ToolResult(json.dumps(data), data=data)

    # --- read-only descriptions
    def do_describe_film(self, a):
        return {
            "motions": dict.fromkeys(MOTIONS, "x"),
            "expressions": ["neutral", "happy"],
            "camera_moves": ["static", "push_in"],
            "characters": [{"id": "kit", "name": "Kit"}, {"id": "bo", "name": "Bo"}],
            "backgrounds": [{"id": "orchard", "name": "Orchard"}],
        }

    def do_describe_audio(self, a):
        voiced = [{"id": c, "voice": {"voices": [{"id": "af_heart"}]}} for c in self.voiced()]
        return {
            "moods": {"playful": "x", "calm": "y"},
            "installed_voices": {"kokoro": ["af_heart", "am_puck", "af_bella"]},
            "characters": voiced,
        }

    def voiced(self) -> list[str]:
        return [c for c in ("kit", "bo") if (self.film / "characters" / c / "voice.json").is_file()]

    def do_describe_art(self, a):
        return {"characters": [], "backgrounds": []}

    def do_check_safety(self, a):
        assert "film" not in a, "the real tool refuses `film` without `shot_id`"
        return {"ok": True, "needs_human": False}

    # --- audio
    def do_set_voice(self, a):
        (self.film / "characters" / a["character_id"] / "voice.json").write_text("{}")
        return {"ok": True}

    def do_speak(self, a):
        out = []
        for ln in a["lines"]:
            lid = f"l{len(self.lines) + 1:03d}"
            self.lines[lid] = ln
            (self.film / "audio" / "lipsync").mkdir(parents=True, exist_ok=True)
            (self.film / "audio" / "lipsync" / f"{lid}.json").write_text("{}")
            out.append({"line_id": lid, "duration_s": 1.5})
        return {"lines": out}

    def do_compose(self, a):
        d = self.film / "audio" / "music"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{a['cue_id']}.wav").write_bytes(b"RIFF")
        return {"cue_id": a["cue_id"]}

    def do_find_sfx(self, a):
        return {"results": [{"sounds": [{"sound_id": "fsd50k_1"}]}]}

    # --- shots: keep a real, schema-valid shot.json
    def spec(self, a) -> dict:
        return self.specs[a["shot_id"]]

    def save(self, a) -> None:
        d = self.film / "shots" / a["shot_id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "shot.json").write_text(json.dumps(self.spec(a)))

    def do_create_scene(self, a):
        self.specs[a["shot_id"]] = {
            "schema_version": 1,
            "id": a["shot_id"],
            "duration_s": a["duration_s"],
            "background": a["background"],
            "characters": [],
            "dialogue": [],
            "camera": {"move": a.get("camera_move", "static")},
        }
        self.save(a)
        return {"ok": True}

    def do_add_character(self, a):
        self.spec(a)["characters"].append(
            {"id": a["character_id"], "position": a["position"], "actions": [], "expressions": []}
        )
        self.save(a)
        return {"ok": True}

    def member(self, a) -> dict:
        return next(c for c in self.spec(a)["characters"] if c["id"] == a["character_id"])

    def do_apply_motion(self, a):
        self.member(a)["actions"].append({"motion": a["motion"], "start_s": a["start_s"]})
        self.save(a)
        return {"ok": True}

    def do_set_expression(self, a):
        self.member(a)["expressions"].append({"expr": a["expr"], "start_s": a["start_s"]})
        self.save(a)
        return {"ok": True}

    def do_apply_lipsync(self, a):
        text = self.lines[a["line_id"]]["text"]
        self.spec(a)["dialogue"].append(
            {
                "character": a["character_id"],
                "line_id": a["line_id"],
                "text": text,
                "start_s": a["start_s"],
            }
        )
        self.save(a)
        return {"ok": True}

    def do_set_music(self, a):
        self.spec(a)["music_cue"] = a["cue_id"]
        self.save(a)
        return {"ok": True}

    def do_render_shot(self, a):
        if self.fail_after_renders is not None:
            if self.fail_after_renders == 0:
                raise RuntimeError("simulated crash")
            self.fail_after_renders -= 1
        (self.film / "shots" / a["shot_id"] / "shot.mp4").write_bytes(b"mp4")
        return {"path": "shot.mp4"}

    def do_check_frame(self, a):
        return {"time_s": a["time_s"], "ok": True, "code_findings": [], "problems": []}

    # --- edit and qa
    def do_assemble(self, a):
        (self.film / "edit").mkdir(exist_ok=True)
        clips = [
            {"kind": "shot", "shot": s, "file": f"shots/{s}/shot.mp4", "duration_s": 4}
            for s in a["shots"]
        ]
        (self.film / "edit" / "edit.json").write_text(json.dumps({"clips": clips}))
        return {"clips": clips}

    def do_render_film(self, a):
        (self.film / "edit" / "final.mp4").write_bytes(b"mp4")
        return {"checks_passed": True}

    def do_check_film(self, a):
        shots = [
            {
                "shot_id": s.name,
                "ok": True,
                "frames": [{"ok": True, "problems": [], "code_findings": []}],
            }
            for s in sorted((self.film / "shots").iterdir())
        ]
        return {"ok": True, "needs_human": False, "shots": shots, "summary": []}
