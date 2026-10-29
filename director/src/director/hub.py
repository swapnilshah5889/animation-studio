"""The MCP client wrapper: starts the five servers named in .mcp.json and calls their tools.

The director talks to the same servers a coding agent or the Inspector does, over stdio, so a tool
schema change is seen by the model and nothing is hidden behind a Python import (design §2).
A *refused* call (the server's is_error result, D-034) comes back as data, never as an exception:
the loop feeds its message to the model.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from mcp import Client, StdioServerParameters

from director.config import MAX_RESULT_CHARS

ProgressFn = Callable[[str], None]


@dataclass
class ToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolResult:
    text: str  # what the model reads: compact JSON or the refusal message, truncated
    data: dict[str, Any] | None = None  # the full structured result, for code
    refused: bool = False
    seconds: float = 0.0
    progress_notes: int = 0


class ToolDispatcher(Protocol):
    """What loop.py needs from the MCP side. McpHub is the real one; tests pass a fake."""

    tools: dict[str, ToolInfo]

    async def call(
        self, tool: str, args: dict[str, Any], on_progress: ProgressFn | None = None
    ) -> ToolResult: ...


def compact(data: Any, limit: int = MAX_RESULT_CHARS) -> str:
    """Tool results go to the model short: compact JSON, cut with a note when too long."""
    text = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"), default=str)
    if len(text) > limit:
        text = text[:limit] + f"...[cut: {len(text)} characters in all]"
    return text


@dataclass
class McpHub:
    repo_root: Path
    servers: list[str] = field(default_factory=list)
    tools: dict[str, ToolInfo] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)  # server -> why it did not start
    _stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    _clients: dict[str, Client] = field(default_factory=dict)
    _owner: dict[str, str] = field(default_factory=dict)  # tool -> server

    async def __aenter__(self) -> McpHub:
        await self.start(self.servers)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    def params(self, name: str) -> StdioServerParameters:
        spec = json.loads((self.repo_root / ".mcp.json").read_text())["mcpServers"][name]
        return StdioServerParameters(command=spec["command"], args=spec["args"], cwd=self.repo_root)

    async def start(self, names: list[str]) -> None:
        """Start each server and list its tools once. A server that fails to start is skipped
        (recorded in `skipped`), so a stage that does not need it still runs."""
        for name in names:
            try:
                client = await self._stack.enter_async_context(Client(self.params(name)))
                listed = await client.list_tools()
            except Exception as err:
                self.skipped[name] = f"{type(err).__name__}: {err}"
                continue
            self._clients[name] = client
            for t in listed.tools:
                if t.name in self.tools:
                    raise RuntimeError(f"tool {t.name} is on both {self._owner[t.name]} and {name}")
                self.tools[t.name] = ToolInfo(name, t.name, t.description or "", t.input_schema)
                self._owner[t.name] = name

    async def call(
        self, tool: str, args: dict[str, Any], on_progress: ProgressFn | None = None
    ) -> ToolResult:
        """Run one tool. Art tools take minutes, so there is no timeout; progress notes go to
        `on_progress` as they arrive (and count towards "this call was not silent")."""
        info = self.tools.get(tool)
        if info is None:
            return ToolResult(f"unknown tool {tool}", refused=True)
        notes = 0

        async def progress(_value: float, _total: float | None, message: str | None) -> None:
            nonlocal notes
            notes += 1
            if on_progress and message:
                on_progress(message)

        t0 = time.monotonic()
        try:
            res = await self._clients[info.server].call_tool(tool, args, progress_callback=progress)
        except Exception as err:
            return ToolResult(
                f"{tool} failed: {type(err).__name__}: {err}",
                refused=True,
                seconds=time.monotonic() - t0,
                progress_notes=notes,
            )
        data = res.structured_content
        text = res.content[0].text if res.content else ""
        return ToolResult(
            text=compact(data if data is not None and not res.is_error else text),
            data=data,
            refused=bool(res.is_error),
            seconds=time.monotonic() - t0,
            progress_notes=notes,
        )


async def call_data(
    hub: ToolDispatcher, tool: str, args: dict[str, Any], on_progress: ProgressFn | None = None
) -> dict[str, Any]:
    """For code-driven stages: run a tool and return its structured result, or raise with the
    server's message. (The LLM-driven loop never raises; it feeds refusals back.)"""
    res = await hub.call(tool, args, on_progress)
    if res.refused:
        raise ToolRefused(tool, res.text)
    return res.data or {}


class ToolRefused(RuntimeError):
    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool} refused: {message}")
        self.tool, self.message = tool, message
