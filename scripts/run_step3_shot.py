"""Step 3's done-when: a shot with voiced, lip-synced dialogue, music and a sound effect, built
only through the two MCP servers (task 3.8).

    uv run scripts/make_demo_film.py      # once: the demo assets (Pip, Bunny, the meadow)
    uv run scripts/run_step3_shot.py

A scripted MCP client starts both servers exactly as `.mcp.json` says (stdio) and makes every
step a tool call, the way the director will in Step 5:

  audio_mcp:   describe_audio → speak (Pip, then Bunny, in their cast voices, with mouth cues)
               → compose (the music) → find_sfx (birdsong)
  synfig_mcp:  create_scene → add_character (both) → apply_motion / set_expression → apply_lipsync
               (both) → add_sound_effect → set_music → describe_shot → render_preview_frame
  audio_mcp:   preview_mix
  synfig_mcp:  render_shot (1080p)

Line timing uses the durations speak returns: Bunny answers 0.4 s after Pip stops. Every call
and its result goes to docs/learning/mcp-step3-shot.md, and the done-when is checked at the end
(exit 1 if any check fails). The film folder films/step3-demo/ is rebuilt each run.
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

from studio_core.audio import ffmpeg
from studio_core.config import REPO_ROOT, load_config

FILM = "step3-demo"
SHOT = "s01_sh01"
DURATION = 10.0
TRANSCRIPT = REPO_ROOT / "docs" / "learning" / "mcp-step3-shot.md"
PIP_LINE = "Bunny, look! I found a red kite in the tall grass!"
BUNNY_LINE = "Wow, Pip! Let's fly it together!"


def server_params(name: str) -> StdioServerParameters:
    """The launch command from .mcp.json, as Claude Code and the Inspector use it."""
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
    async with (
        Client(server_params("audio_mcp")) as audio,
        Client(server_params("synfig_mcp")) as anim,
    ):
        a = lambda tool, **args: rec.call(audio, "audio_mcp", tool, args)  # noqa: E731
        s = lambda tool, **args: rec.call(anim, "synfig_mcp", tool, args)  # noqa: E731
        film, shot = {"film": FILM}, {"film": FILM, "shot_id": SHOT}

        await a("describe_audio", **film)
        pip = (await a("speak", **film, character_id="pip", lines=[{"text": PIP_LINE}]))["lines"]
        bunny = await a("speak", **film, character_id="bunny", lines=[{"text": BUNNY_LINE}])
        bunny = bunny["lines"]
        await a("compose", **film, cue_id="m01", mood="playful", duration_s=DURATION, energy=0.5)
        birds = await a(
            "find_sfx", queries=["birds singing in the morning"], k=3, avoid=["traffic", "vehicle"]
        )
        bird_id = birds["results"][0]["sounds"][0]["sound_id"]

        pip_start = 0.6
        bunny_start = round(pip_start + pip[0]["duration_s"] + 0.4, 2)
        bunny_end = bunny_start + bunny[0]["duration_s"]
        await s("create_scene", **shot, duration_s=DURATION, background="meadow",
                camera_move="slow_pan_right")  # fmt: skip
        await s("add_character", **shot, character_id="pip", position=[0.34, 0.92])
        await s("add_character", **shot, character_id="bunny", position=[0.68, 0.92],
                facing="left")  # fmt: skip
        for who in ("pip", "bunny"):
            c = {**shot, "character_id": who}
            await s("apply_motion", **c, motion="blink", start_s=0, duration_s=DURATION)
            await s("apply_motion", **c, motion="idle_breathe", start_s=0)
            await s("set_expression", **c, expr="happy", start_s=0)
        await s("apply_motion", **shot, character_id="pip", motion="wave", start_s=0.3,
                side="left", energy=0.6, cycles=2)  # fmt: skip
        await s("apply_motion", **shot, character_id="pip", motion="talk_gesture",
                start_s=pip_start + 1.6, side="right", duration_s=1.5)  # fmt: skip
        await s("apply_motion", **shot, character_id="bunny", motion="jump",
                start_s=round(bunny_end + 0.2, 2), energy=0.7)  # fmt: skip
        await s(
            "set_expression", **shot, character_id="bunny", expr="surprised", start_s=bunny_start
        )
        await s("set_expression", **shot, character_id="bunny", expr="happy",
                start_s=round(bunny_start + 1.0, 2))  # fmt: skip
        await s("apply_lipsync", **shot, character_id="pip", line_id=pip[0]["line_id"],
                start_s=pip_start)  # fmt: skip
        await s("apply_lipsync", **shot, character_id="bunny", line_id=bunny[0]["line_id"],
                start_s=bunny_start)  # fmt: skip
        await s("add_sound_effect", **shot, sound_id=bird_id, start_s=0.0, volume=0.35,
                query="birds singing in the morning")  # fmt: skip
        await s("set_music", **shot, cue_id="m01", volume=0.45)
        await s("describe_shot", **shot)
        await s("render_preview_frame", **shot, time_s=round(pip_start + 1.0, 2))
        await a("preview_mix", **shot)
        await s("render_shot", **shot, quality="final")


def checks() -> list[tuple[bool, str]]:
    cfg = load_config()
    folder = REPO_ROOT / "films" / FILM / "shots" / SHOT
    spec = json.loads((folder / "shot.json").read_text())
    sif = (folder / "scene.sif").read_text()
    mp4 = folder / "shot.mp4"
    out: list[tuple[bool, str]] = []
    lines = spec.get("dialogue", [])
    cued = [
        d
        for d in lines
        if (REPO_ROOT / "films" / FILM / "audio" / "lipsync" / f"{d['line_id']}.json").is_file()
    ]
    out.append((len(cued) == len(lines) >= 1, f"{len(lines)} voiced lines, each with mouth cues"))
    mouth_keys = len(re.findall(r'<waypoint time="\d+f"[^>]*>\s*<string>[A-HX]</string>', sif))
    out.append((mouth_keys > 10, f"mouth switch animated in scene.sif ({mouth_keys} keys)"))
    out.append((spec.get("music_cue") == "m01", "music cue set"))
    out.append((any("sound" in e for e in spec.get("sfx", [])), "a sound effect placed"))
    probe = subprocess.run(
        [str(cfg.path("tools", "ffprobe")), "-v", "error", "-show_entries",
         "stream=codec_type,width,height,nb_frames", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    streams = {st["codec_type"]: st for st in json.loads(probe.stdout)["streams"]}
    v = streams.get("video", {})
    out.append((v.get("width") == 1920 and v.get("nb_frames") == "240", "1080p video, 240 frames"))
    loud = ffmpeg.measure(folder / "mix.wav", cfg)
    out.append(
        (
            "audio" in streams and abs(loud.integrated_lufs + 14) <= 1 and loud.true_peak_db <= -1,
            f"mixed soundtrack: {loud.integrated_lufs:.1f} LUFS, {loud.true_peak_db:.1f} dBTP",
        )
    )
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
            "# Step 3's done-when shot, through both MCP servers",
            "",
            "Generated by `uv run scripts/run_step3_shot.py` (task 3.8). A scripted MCP client",
            "starts `audio_mcp` and `synfig_mcp` from `.mcp.json` and builds the shot only with",
            "tool calls: two voiced, lip-synced lines in the characters' cast voices, a composed",
            "music cue, a sound effect found by description, then a 1080p render.",
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
    for part in ("characters", "backgrounds"):
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
