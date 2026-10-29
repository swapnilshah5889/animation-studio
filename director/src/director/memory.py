"""One large model in memory at a time (Mac rule, AGENTS.md): who may be loaded in which stage.

LLM stages (story, shots): free ComfyUI first, then the chat model loads on its first call.
Every other stage (art, audio, edit, qa): unload the chat model first and check it is gone.
All three actions are injected, so the order is unit-tested without Ollama or ComfyUI.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

LLM_STAGES = ("story", "shots")
# `compose` (the music model) refuses while ComfyUI is running, so this stage needs it stopped.
NO_COMFY_STAGES = ("audio",)


class MemoryConflict(RuntimeError):
    """A big model is in the way and cannot be moved: the stage must not start."""


@dataclass
class MemoryGuard:
    model: str
    loaded: Callable[[], list[str]]  # names of models Ollama holds in memory
    unload: Callable[[str], None]  # unload one and wait until it is gone
    comfy_state: Callable[[], Literal["down", "idle", "busy"]]
    comfy_free: Callable[[], None]
    comfy_stop: Callable[[], None] = lambda: None

    def release_llm(self) -> None:
        """Unload the chat model (and any other Ollama model) and verify it is gone."""
        for name in self.loaded():
            self.unload(name)
        if self.loaded():
            raise MemoryConflict(f"Ollama still holds {self.loaded()} after unloading")

    def claim_llm(self) -> None:
        """Make room for the chat model: ComfyUI must not be working; free what it holds."""
        state = self.comfy_state()
        if state == "busy":
            raise MemoryConflict("ComfyUI is busy with an art job; the LLM stage must wait")
        if state == "idle":
            self.comfy_free()

    def stop_comfy(self) -> None:
        """Stop an idle ComfyUI server (never one that is working) and check it is gone."""
        state = self.comfy_state()
        if state == "busy":
            raise MemoryConflict("ComfyUI is busy with an art job; the audio stage must wait")
        if state == "idle":
            self.comfy_stop()
            if self.comfy_state() != "down":
                raise MemoryConflict(
                    "ComfyUI is still running; stop it with scripts/comfy_server.sh --stop"
                )

    @asynccontextmanager
    async def for_stage(self, stage: str):
        if stage in LLM_STAGES:
            self.claim_llm()
        else:
            self.release_llm()
            if stage in NO_COMFY_STAGES:
                self.stop_comfy()
        yield


def comfy_state_via_http(url: str = "http://127.0.0.1:8188") -> Literal["down", "idle", "busy"]:
    import json

    try:
        with urllib.request.urlopen(f"{url}/queue", timeout=3) as resp:
            q = json.loads(resp.read())
    except OSError:
        return "down"
    return "busy" if q.get("queue_running") or q.get("queue_pending") else "idle"
