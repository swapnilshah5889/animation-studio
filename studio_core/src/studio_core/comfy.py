"""Minimal ComfyUI HTTP client (standard library only).

ComfyUI runs as a local server; a workflow saved in "API format" is a JSON dict of
{node_id: {"class_type": ..., "inputs": {...}}}. To run one we:

  1. optionally upload input images          POST /upload/image (multipart)
  2. queue the workflow                      POST /prompt {"prompt": workflow, "client_id": ...}
  3. wait until it shows up in the history   GET  /history/{prompt_id}
  4. download each output image              GET  /view?filename=...&subfolder=...&type=output

We poll instead of using the websocket to stay dependency-free; for a few images per minute the
difference is irrelevant. The comfy_mcp server (Step 4) builds on this.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8188"


class ComfyError(RuntimeError):
    pass


class Comfy:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    # ------------------------------------------------------------------ low level

    def _get(self, path: str) -> bytes:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=self.timeout) as resp:
            return resp.read()

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            # ComfyUI explains validation errors (missing model, bad input) in the body.
            raise ComfyError(f"{path} -> HTTP {exc.code}: {exc.read().decode()[:2000]}") from exc

    # ------------------------------------------------------------------ API

    def system_stats(self) -> dict[str, Any]:
        return json.loads(self._get("/system_stats"))

    def upload_image(self, path: Path, overwrite: bool = True) -> str:
        """Upload a local image into ComfyUI's input folder. Returns the name LoadImage expects."""
        boundary = uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
            f'filename="{path.name}"\r\nContent-Type: image/png\r\n\r\n'
        ).encode()
        body += path.read_bytes()
        body += (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\n'
            f"{'true' if overwrite else 'false'}\r\n--{boundary}--\r\n"
        ).encode()
        req = urllib.request.Request(
            f"{self.base_url}/upload/image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            info = json.loads(resp.read())
        return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]

    def queue(self, workflow: dict[str, Any]) -> str:
        """Queue an API-format workflow. Returns the prompt_id."""
        resp = self._post_json("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if resp.get("node_errors"):
            raise ComfyError(f"node errors: {json.dumps(resp['node_errors'])[:2000]}")
        return resp["prompt_id"]

    def wait(self, prompt_id: str, timeout_s: float = 1800, poll_s: float = 0.5) -> dict[str, Any]:
        """Block until the prompt finishes. Returns its history entry."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            history = json.loads(self._get(f"/history/{prompt_id}"))
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    messages = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                    raise ComfyError(f"execution error: {json.dumps(messages)[:2000]}")
                if status.get("completed", True):
                    return entry
            time.sleep(poll_s)
        raise TimeoutError(f"prompt {prompt_id} did not finish within {timeout_s}s")

    def download_outputs(self, entry: dict[str, Any], out_dir: Path) -> list[Path]:
        """Save every image a finished prompt produced into out_dir. Returns the local paths."""
        out_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for node_output in entry.get("outputs", {}).values():
            for image in node_output.get("images", []):
                query = urllib.parse.urlencode(
                    {
                        "filename": image["filename"],
                        "subfolder": image["subfolder"],
                        "type": image["type"],
                    }
                )
                target = out_dir / image["filename"]
                target.write_bytes(self._get(f"/view?{query}"))
                saved.append(target)
        return saved

    def run(
        self, workflow: dict[str, Any], out_dir: Path, timeout_s: float = 1800
    ) -> tuple[list[Path], float]:
        """Queue, wait, download. Returns (saved image paths, wall-clock seconds)."""
        start = time.perf_counter()
        entry = self.wait(self.queue(workflow), timeout_s=timeout_s)
        elapsed = time.perf_counter() - start
        return self.download_outputs(entry, out_dir), elapsed

    def free_memory(self) -> None:
        """Ask ComfyUI to unload models and free cached memory (Mac rule: before LLM work)."""
        self._post_json("/free", {"unload_models": True, "free_memory": True})
