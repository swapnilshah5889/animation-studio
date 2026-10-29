"""Minimal Ollama HTTP client (standard library only).

Deliberately thin: it shows exactly what goes over the wire to Ollama's REST API
(https://github.com/ollama/ollama/blob/main/docs/api.md), which matters when we hand-write the
director's agent loop in Step 5. Durations in Ollama responses are nanoseconds.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_URL = "http://127.0.0.1:11434"


@dataclass
class Timings:
    """Speed numbers Ollama reports with every non-streaming response."""

    load_s: float
    prompt_tokens: int
    prompt_tps: float
    gen_tokens: int
    gen_tps: float
    total_s: float

    @classmethod
    def from_response(cls, resp: dict[str, Any]) -> Timings:
        def rate(count: int, ns: int) -> float:
            return count / (ns / 1e9) if ns else 0.0

        return cls(
            load_s=resp.get("load_duration", 0) / 1e9,
            prompt_tokens=resp.get("prompt_eval_count", 0),
            prompt_tps=rate(resp.get("prompt_eval_count", 0), resp.get("prompt_eval_duration", 0)),
            gen_tokens=resp.get("eval_count", 0),
            gen_tps=rate(resp.get("eval_count", 0), resp.get("eval_duration", 0)),
            total_s=resp.get("total_duration", 0) / 1e9,
        )


class Ollama:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 600) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        think: bool | str | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str | int | None = None,
        format: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """One non-streaming /api/chat call. Returns the raw response dict. `format` is "json"
        or a JSON schema the reply must follow (constrained decoding)."""
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think  # bool for most models; "low"/"medium"/"high" for gpt-oss
        if options:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if format is not None:
            payload["format"] = format
        return self._request("/api/chat", payload)

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        images: list[str] | None = None,
        think: bool | str | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str | int | None = None,
        format: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """One non-streaming /api/generate call. `images` are base64-encoded PNG/JPEG strings;
        `format` is "json" or a JSON schema the answer must follow."""
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if images:
            payload["images"] = images
        if think is not None:
            payload["think"] = think
        if options:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if format is not None:
            payload["format"] = format
        return self._request("/api/generate", payload)

    def loaded(self) -> list[dict[str, Any]]:
        """Models currently in memory (/api/ps)."""
        return self._request("/api/ps").get("models", [])

    def load(self, model: str, keep_alive: str | int = "5m") -> float:
        """Load a model into memory without generating. Returns wall-clock seconds."""
        start = time.perf_counter()
        self._request("/api/generate", {"model": model, "keep_alive": keep_alive})
        return time.perf_counter() - start

    def unload(self, model: str, wait_s: float = 60) -> float:
        """Unload a model (keep_alive=0) and wait until /api/ps no longer lists it.

        Returns wall-clock seconds until the memory is actually released. This is the call every
        pipeline stage makes before handing the GPU to ComfyUI (Mac memory rule, one big model).
        """
        start = time.perf_counter()
        self._request("/api/generate", {"model": model, "keep_alive": 0})
        deadline = start + wait_s
        while time.perf_counter() < deadline:
            if not any(m["name"] == model for m in self.loaded()):
                return time.perf_counter() - start
            time.sleep(0.05)
        raise TimeoutError(f"{model} still loaded after {wait_s}s")
