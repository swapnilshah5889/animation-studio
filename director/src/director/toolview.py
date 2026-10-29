"""Which tools the model sees, per stage, and in what form.

A model with 60 tools picks worse than one with 15, so each LLM stage gets an allowlist. Two more
things are done here so the model cannot get them wrong: arguments the code already knows (`film`,
`shot_id`) are *hidden* from the schema the model sees and injected on every call (dispatch.py).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from director.hub import ToolInfo

# Only the shots stage is operated by the model through tools; the other stages are planned by the
# model (schema-forced JSON, plans.py) and executed by code (D-079 answers: art stages code-driven).
STAGE_TOOLS: dict[str, tuple[str, ...]] = {
    "shots": (
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
        "read_craft",
    ),
}

LOCAL_TOOLS: dict[str, dict[str, Any]] = {
    "read_craft": {
        "description": "Read one craft note (a veteran animator's rules of thumb) by topic name. "
        "The system prompt lists the topics.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "A topic name from the index"}
            },
            "required": ["topic"],
        },
    }
}


@dataclass
class ToolView:
    """The tools one conversation may use."""

    tools: dict[str, ToolInfo] = field(default_factory=dict)
    hidden: tuple[str, ...] = ("film", "shot_id")  # filled in by code, not by the model

    @classmethod
    def for_stage(
        cls,
        stage: str,
        available: dict[str, ToolInfo],
        hidden: tuple[str, ...] = ("film", "shot_id"),
    ) -> ToolView:
        allowed = STAGE_TOOLS.get(stage, ())
        picked = {n: available[n] for n in allowed if n in available}
        for n in allowed:
            if n in LOCAL_TOOLS:
                picked[n] = ToolInfo(
                    "local", n, LOCAL_TOOLS[n]["description"], LOCAL_TOOLS[n]["parameters"]
                )
        return cls(picked, hidden)

    def __contains__(self, name: str) -> bool:
        return name in self.tools

    def names(self) -> list[str]:
        return sorted(self.tools)

    def schema(self, name: str) -> dict[str, Any]:
        """The full schema (with film/shot_id): what a call is validated against."""
        return self.tools[name].input_schema

    def ollama_tools(self) -> list[dict[str, Any]]:
        """Ollama's tool format, with the hidden arguments removed from what the model sees."""
        out = []
        for info in self.tools.values():
            params = copy.deepcopy(info.input_schema)
            for key in self.hidden:
                params.get("properties", {}).pop(key, None)
                if key in params.get("required", []):
                    params["required"].remove(key)
            _strip_titles(params)
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": info.name,
                        "description": info.description,
                        "parameters": params,
                    },
                }
            )
        return out


def _strip_titles(node: Any) -> None:
    """JSON Schema `title` keys only cost tokens."""
    if isinstance(node, dict):
        node.pop("title", None)
        for v in node.values():
            _strip_titles(v)
    elif isinstance(node, list):
        for v in node:
            _strip_titles(v)
