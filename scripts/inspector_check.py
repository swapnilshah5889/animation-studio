"""Call every synfig_mcp tool through the MCP Inspector's CLI, using the project's .mcp.json.

    uv run scripts/inspector_check.py           # needs films/step2-demo (scripts/make_demo_film.py)

This exercises the server the way an outside client does: the Inspector starts it from
.mcp.json over stdio, lists the tools, and calls each one, plus a few calls that must be
refused with a fixable message. It works on a scratch copy, films/inspector-check/, made fresh
on every run (films/ is git-ignored). Prints one line per call; exits 1 if any call didn't do
what was expected. The Inspector is pinned (INSPECTOR) and fetched by npx on first use.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any

from studio_core.config import REPO_ROOT

INSPECTOR = "@modelcontextprotocol/inspector@2.9.0"
FILM = "inspector-check"
SHOT = {"film": FILM, "shot_id": "s01_sh01"}
PIP = {**SHOT, "character_id": "pip"}

# (tool, arguments, expect an error?)
CALLS: list[tuple[str, dict[str, Any], bool]] = [
    ("describe_film", {"film": FILM}, False),
    ("build_rig", {"film": FILM, "character_id": "bunny"}, False),
    ("create_scene", {**SHOT, "duration_s": 4, "background": "meadow"}, False),
    ("add_parallax_background", {**SHOT, "background_id": "meadow"}, False),
    ("add_character", {**PIP, "position": [0.4, 0.92]}, False),
    ("apply_motion", {**PIP, "motion": "blink", "start_s": 0, "duration_s": 4}, False),
    ("apply_motion", {**PIP, "motion": "wave", "start_s": 0.5, "side": "left"}, False),
    ("set_expression", {**PIP, "expr": "happy", "start_s": 0}, False),
    ("apply_lipsync", {**PIP, "line_id": "l001", "start_s": 0.2}, False),
    ("pose_at", {**PIP, "time_s": 3.5, "bone_angles": {"head": 8}}, False),
    ("camera_move", {**SHOT, "move": "push_in"}, False),
    ("remove_from_shot", {**PIP, "kind": "pose", "index": 0}, False),
    ("describe_shot", SHOT, False),
    ("render_preview_frame", {**SHOT, "time_s": 1.0}, False),
    ("render_shot", {**SHOT, "quality": "preview"}, False),
    # refusals the model must be able to act on
    ("apply_motion", {**PIP, "motion": "wavee", "start_s": 1}, True),
    ("pose_at", {**PIP, "time_s": 1, "bone_angles": {"tail": 5}}, True),
    ("add_character", {**SHOT, "character_id": "kit", "position": [0.5, 0.9]}, True),
]


def call(tool: str | None, args: dict[str, Any]) -> dict[str, Any]:
    cmd = [
        "npx",
        "-y",
        INSPECTOR,
        "--cli",
        "--config",
        ".mcp.json",
        "--server",
        "synfig_mcp",
        "--cwd",
        str(REPO_ROOT),
    ]
    if tool is None:
        cmd += ["--method", "tools/list"]
    else:
        cmd += ["--method", "tools/call", "--tool-name", tool, "--tool-arg"]
        cmd += [f"{k}={v if isinstance(v, str) else json.dumps(v)}" for k, v in args.items()]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    out = proc.stdout + proc.stderr  # the Inspector's JSON, after any npm warnings
    start = out.find("{")
    try:  # a tool error still prints the result (isError: true), with a non-zero exit code
        return json.JSONDecoder().raw_decode(out[start:])[0]
    except ValueError:
        return {"isError": True, "content": [{"text": out.strip()[-500:]}]}


def summary(result: dict[str, Any]) -> str:
    data = result.get("structuredContent")
    if result.get("isError") or not data:
        text = result["content"][0]["text"].replace("Error executing tool ", "")
        return " ".join(text.split())[:150]
    for key in ("change", "video_path", "image_path", "rig_path"):
        if key in data:
            return str(data[key]).replace(str(REPO_ROOT) + "/", "")
    if "spec" in data:
        return f"{data['n_frames']} frames, errors {data['errors']}, warnings {data['warnings']}"
    if "characters" in data:
        chars = [c["id"] for c in data["characters"]]
        return f"characters {chars}, lines {len(data['dialogue_lines'])}"
    return json.dumps(data)[:150]


def main() -> int:
    films = REPO_ROOT / "films"
    if not (films / "step2-demo").is_dir():
        sys.exit("films/step2-demo is missing: run scripts/make_demo_film.py first")
    shutil.rmtree(films / FILM, ignore_errors=True)
    shutil.copytree(films / "step2-demo", films / FILM, ignore=shutil.ignore_patterns("shots"))

    tools = call(None, {}).get("tools", [])
    print(f"tools/list: {len(tools)} tools: {', '.join(t['name'] for t in tools)}")
    failures = 0 if len(tools) == 14 else 1
    for tool, args, want_error in CALLS:
        result = call(tool, args)
        got_error = bool(result.get("isError"))
        good = got_error == want_error
        failures += not good
        mark = "ok " if good else "BAD"
        kind = "refused" if got_error else "done"
        print(f"{mark} {tool:24} {kind:8} {summary(result)}")
    print(f"\n{len(CALLS) + 1 - failures}/{len(CALLS) + 1} as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
