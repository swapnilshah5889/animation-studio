"""Step 2's done-when: an LLM directs a shot through synfig_mcp, as a scripted MCP client.

    uv run scripts/make_demo_film.py      # once: the demo assets (Pip, Bunny, the meadow)
    uv run scripts/run_first_shot.py

A scripted MCP client starts synfig_mcp exactly as `.mcp.json` says (stdio) and builds the shot
only with tool calls, the way the director will in Step 5:

  create_scene -> add_character (Pip) -> idle_breathe + blink + wave -> set_expression
  -> apply_lipsync (l001) -> describe_shot -> render_preview_frame -> render_shot (1080p)

The shot is a 10-second scene: Pip waves, blinks, breathes and speaks line l001 in the meadow
during a slow pan. Every call and its result goes to docs/learning/mcp-first-shot.md, and the
done-when is checked at the end (exit 1 if any check fails). The film folder films/first-shot/
is rebuilt each run. Safe to re-run; no Claude Code or API keys involved.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from typing import Any

from mcp import Client, StdioServerParameters

from studio_core.config import REPO_ROOT, load_config

FILM = "first-shot"
SHOT = "s01_sh01"
DURATION = 10.0
TRANSCRIPT = REPO_ROOT / "docs" / "learning" / "mcp-first-shot.md"


def server_params(name: str) -> StdioServerParameters:
    """The launch command from .mcp.json, as any MCP client uses it."""
    spec = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"][name]
    return StdioServerParameters(command=spec["command"], args=spec["args"], cwd=REPO_ROOT)


class Recorder:
    def __init__(self) -> None:
        self.steps: list[tuple[str, str, dict, Any, bool, float]] = []

    async def call(self, client: Client, server: str, tool: str, args: dict) -> dict:
        t0 = time.monotonic()
        result = await client.call_tool(tool, args)
        seconds = time.monotonic() - t0
        data = result.structured_content or {"text": result.content[0].text}
        self.steps.append((server, tool, args, data, bool(result.is_error), seconds))
        mark = "refused" if result.is_error else "ok"
        print(f"{server:10} {tool:22} {mark:8} {seconds:5.1f}s", flush=True)
        if result.is_error:
            raise SystemExit(f"{tool} failed: {result.content[0].text}")
        return data


async def build(rec: Recorder) -> None:
    async with Client(server_params("synfig_mcp")) as anim:
        s = lambda tool, **args: rec.call(anim, "synfig_mcp", tool, args)  # noqa: E731
        shot = {"film": FILM, "shot_id": SHOT}
        pip = {**shot, "character_id": "pip"}

        await s("create_scene", **shot, duration_s=DURATION, background="meadow",
                camera_move="slow_pan_right")  # fmt: skip
        await s("add_character", **shot, character_id="pip", position=[0.5, 0.92])
        await s("apply_motion", **pip, motion="idle_breathe", start_s=0)
        await s("apply_motion", **pip, motion="blink", start_s=0, duration_s=DURATION)
        await s("apply_motion", **pip, motion="wave", start_s=1.0,
                side="left", energy=0.7, cycles=3)  # fmt: skip
        await s("set_expression", **pip, expr="happy", start_s=0)
        await s("apply_lipsync", **pip, line_id="l001", start_s=1.5)
        await s("describe_shot", **shot)
        await s("render_preview_frame", **shot, time_s=3.0)
        await s("render_shot", **shot, quality="final")


def checks() -> list[tuple[bool, str]]:
    """Step 2's done-when, checked from the saved spec and the rendered video."""
    cfg = load_config()
    folder = REPO_ROOT / "films" / FILM / "shots" / SHOT
    out: list[tuple[bool, str]] = []
    spec_file = folder / "shot.json"
    if not spec_file.is_file():
        return [(False, "shot s01_sh01 was created")]
    spec = json.loads(spec_file.read_text())
    out.append((spec["duration_s"] == 10, f"10-second shot (got {spec['duration_s']} s)"))
    layers_file = REPO_ROOT / "films" / FILM / "backgrounds" / spec["background"] / "layers.json"
    layers = json.loads(layers_file.read_text())
    factors = sorted({layer["parallax"] for layer in layers["layers"]})
    moving = spec.get("camera", {}).get("move", "static") != "static"
    out.append((len(factors) > 1 and moving, f"parallax background {factors} with a camera move"))
    chars = spec["characters"]
    rigged = [
        c
        for c in chars
        if (REPO_ROOT / "films" / FILM / "characters" / c["id"] / "rig.json").is_file()
    ]
    motions = {a["motion"] for c in rigged for a in c.get("actions", [])}
    out.append(("wave" in motions, f"a rigged character waves (motions: {sorted(motions)})"))
    out.append(("blink" in motions, "and blinks"))
    lines = spec.get("dialogue", [])
    cued = [
        d for d in lines
        if (REPO_ROOT / "films" / FILM / "audio" / "lipsync" / f"{d['line_id']}.json").is_file()
    ]
    speakers = {d["character"] for d in cued}
    out.append(
        (bool(cued) and speakers <= {c["id"] for c in rigged}, f"mouth cue track: {len(cued)} line")
    )
    sif = (folder / "scene.sif").read_text()
    mouth_keys = len(re.findall(r'<waypoint time="\d+f"[^>]*>\s*<string>[A-HX]</string>', sif))
    out.append((mouth_keys > 0, f"mouth switch animated in scene.sif ({mouth_keys} keys)"))
    mp4 = folder / "shot.mp4"
    if mp4.is_file():
        probe = subprocess.run(
            [str(cfg.path("tools", "ffprobe")), "-v", "error", "-show_entries",
             "stream=codec_type,width,height,nb_frames", "-of", "json", str(mp4)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        streams = {s["codec_type"]: s for s in json.loads(probe.stdout)["streams"]}
        video = streams.get("video", {})
        size = f"{video.get('width')}x{video.get('height')}"
        out.append(
            (
                size == "1920x1080" and video.get("nb_frames") == "240" and "audio" in streams,
                f"rendered video: {size}, {video.get('nb_frames')} frames, audio: "
                f"{'audio' in streams}",
            )
        )
    else:
        out.append((False, "rendered video shot.mp4"))
    return out


def transcript(rec: Recorder, results: list[tuple[bool, str]], seconds: float) -> str:
    def short(value: Any) -> str:
        text = json.dumps(value, indent=1).replace(str(REPO_ROOT) + "/", "")
        return text if len(text) < 900 else text[:900] + "\n…"

    body = []
    for n, (server, tool, args, data, failed, secs) in enumerate(rec.steps, 1):
        body += [
            f"### {n}. `{server}.{tool}` ({secs:.1f} s{', refused' if failed else ''})",
            "",
            "```json",
            json.dumps(args, ensure_ascii=False),
            "```",
            "",
            "```",
            short(data),
            "```",
            "",
        ]
    return "\n".join(
        [
            "# Step 2's done-when shot, through synfig_mcp",
            "",
            "Generated by `uv run scripts/run_first_shot.py` (task 2.8). A scripted MCP client",
            "starts `synfig_mcp` from `.mcp.json` and builds the shot only with tool calls: a",
            "rigged character waving and blinking in front of a parallax background, with a",
            "mouth cue track driving the mouth, then a 1080p render.",
            "",
            f"- Date: {date.today().isoformat()}; {len(rec.steps)} tool calls; {seconds:.0f} s.",
            f"- Video: `films/{FILM}/shots/{SHOT}/shot.mp4` (git-ignored).",
            "",
            "## Checks",
            "",
            *[f"- [{'x' if ok else ' '}] {text}" for ok, text in results],
            "",
            "## Calls",
            "",
            *body,
        ]
    )


def main() -> int:
    demo, film = REPO_ROOT / "films" / "step2-demo", REPO_ROOT / "films" / FILM
    if not demo.is_dir():
        sys.exit("films/step2-demo is missing: run scripts/make_demo_film.py first")
    shutil.rmtree(film, ignore_errors=True)
    for part in ("characters", "backgrounds", "audio"):
        if (demo / part).is_dir():
            shutil.copytree(demo / part, film / part)
    t0 = time.monotonic()
    rec = Recorder()
    asyncio.run(build(rec))
    seconds = time.monotonic() - t0
    results = checks()
    TRANSCRIPT.write_text(transcript(rec, results, seconds))
    for ok, text in results:
        print(f"[{'x' if ok else ' '}] {text}")
    print(f"{len(rec.steps)} calls in {seconds:.0f} s → {TRANSCRIPT.relative_to(REPO_ROOT)}")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
