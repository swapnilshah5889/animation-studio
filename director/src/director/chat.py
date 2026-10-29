"""One model call, behind a tiny interface the loop and the tests share.

`ChatFn` is what loop.py needs from an LLM: messages (+ optional tools or a JSON schema) in, a
`ChatReply` out. `OllamaChat` is the real one (Ollama's /api/chat via studio_core); tests pass a
scripted fake with the same call signature, so the whole director runs offline.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio

from director.config import KEEP_ALIVE, MODEL, NUM_CTX


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] | str  # Ollama gives a dict; a sloppy model may give a string


@dataclass
class ChatReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    thinking: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


class ChatFn(Protocol):
    async def __call__(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
        format: dict[str, Any] | None = None,
    ) -> ChatReply: ...


def assistant_message(reply: ChatReply) -> dict[str, Any]:
    """The reply as a history entry. Thinking is kept out of history on purpose: it is long and
    the next call does not need it (Qwen3 is trained to see only past final answers)."""
    msg: dict[str, Any] = {"role": "assistant", "content": reply.content}
    if reply.tool_calls:
        msg["tool_calls"] = [
            {
                "function": {
                    "name": c.name,
                    "arguments": c.arguments if isinstance(c.arguments, dict) else {},
                }
            }
            for c in reply.tool_calls
        ]
    return msg


class OllamaChat:
    """qwen3:14b through Ollama. `keep_alive` keeps it loaded between LLM stages; the memory
    guard unloads it before art work."""

    def __init__(self, ollama: Any, model: str = MODEL, num_ctx: int = NUM_CTX) -> None:
        self.ollama, self.model, self.num_ctx = ollama, model, num_ctx

    async def __call__(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
        format: dict[str, Any] | None = None,
    ) -> ChatReply:
        t0 = time.monotonic()
        raw = await anyio.to_thread.run_sync(lambda: self._chat(messages, tools, think, format))
        msg = raw.get("message", {})
        calls = [
            ToolCall(c["function"]["name"], c["function"].get("arguments", {}))
            for c in msg.get("tool_calls") or []
        ]
        return ChatReply(
            content=msg.get("content") or "",
            tool_calls=calls,
            thinking=msg.get("thinking") or "",
            prompt_tokens=raw.get("prompt_eval_count", 0),
            output_tokens=raw.get("eval_count", 0),
            seconds=time.monotonic() - t0,
        )

    def _chat(self, messages: list, tools: list | None, think: bool, fmt: dict | None) -> dict:
        return self.ollama.chat(
            self.model,
            messages,
            tools=tools,
            think=think,
            keep_alive=KEEP_ALIVE,
            options={"num_ctx": self.num_ctx, "temperature": 0.3},
            format=fmt,
        )


def parse_json(text: str) -> Any:
    """A `format`-constrained reply is JSON text; this is the one place that parses it."""
    return json.loads(text)
