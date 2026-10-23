"""Step 4's done-when: a new character and a new place made from words, then a shot with them,
built only through the three MCP servers (task 4.9).

    uv run scripts/run_step4_shot.py            # about 45-60 min: the art jobs dominate
    uv run scripts/run_step4_shot.py --resume   # keep the film; skip the art that is ready

A scripted MCP client starts the three servers exactly as `.mcp.json` says (stdio) and makes
every step a tool call, the way the director will in Step 5. Where the owner would look and
choose, the script takes the first candidate whose checks pass (another round if none does),
and if the built puppet's two views don't match (build_puppet's views_consistent), it builds
from the next passing sheet:

  audio_mcp:   describe_audio → compose (the music, first: it needs the GPU to itself)
  synfig_mcp:  build_rig (Pip, the reference puppet) → audio_mcp set_voice (Pip, as cast)
  comfy_mcp:   describe_art → design_character (Bo) → choose_design → build_puppet
               → generate_background (the orchard) → choose_background → split_depth_layers
  audio_mcp:   set_voice (Bo) → speak (Bo, then Pip) → find_sfx (birdsong)
  comfy_mcp:   preview_puppet (Bo in the orchard) → preview_background (the pan, hole check)
               → describe_art
  synfig_mcp:  create_scene → add_character (both) → motions, expressions, lip-sync, sound,
               music → describe_shot → render_preview_frame
  audio_mcp:   preview_mix
  synfig_mcp:  render_shot (1080p)

Outside MCP there are only two setup steps: the empty film (film.json in the storybook style;
no tool creates films yet) and stopping a ComfyUI left running by earlier work, so the music
model can load. Long calls print the server's progress notifications as they arrive. Every
call, its result and its progress count go to docs/learning/mcp-step4-shot.md (written even
when a call fails), and the done-when is checked at the end (exit 1 if any check fails).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from contextlib import AsyncExitStack
from datetime import date
from typing import Any

from mcp import Client, StdioServerParameters

from studio_core.audio import ffmpeg
from studio_core.config import REPO_ROOT, load_config
from studio_core.film import Film
from studio_core.models import load_manifest

FILM = "step4-proof"
SHOT = "s01_sh01"
DURATION = 8.0
TRANSCRIPT = REPO_ROOT / "docs" / "learning" / "mcp-step4-shot.md"
BO = {
    "id": "bo",
    "name": "Bo",
    "description": "a cheerful little brown bear cub wearing blue dungarees",
}
ORCHARD = {
    "id": "orchard",
    "description": "an apple orchard on gentle green hills with a little red barn far away",
}
SHEETS, DRAFTS, ROUNDS = 3, 2, 2  # candidates per round; rounds before giving up
BUILDS = 2  # puppets built from different sheets before giving up
# Pip as the owner cast him (casting page c12); Bo is cast here, a placeholder until casting.
PIP_VOICE = {"voices": [{"id": "af_heart"}], "speed": 1.08, "pitch_semitones": 2}
BO_VOICE = {
    "voices": [{"id": "am_puck"}],
    "speed": 1.0,
    "pitch_semitones": 2.5,
    "notes": "Placeholder from scripts/run_step4_shot.py; recast at casting.",
}
BO_LINE = "Hi Pip! The apples are ready. Shall we pick some?"
PIP_LINE = "Yes! Let's fill the basket!"
BO_AT, PIP_AT = [0.36, 0.92], [0.68, 0.92]
COMFY_TOOLS = {
    "describe_art", "design_character", "choose_design", "build_puppet", "preview_puppet",
    "generate_background", "choose_background", "split_depth_layers", "preview_background",
}  # fmt: skip


def server_params(name: str) -> StdioServerParameters:
    """The launch command from .mcp.json, as Claude Code and the Inspector use it."""
    spec = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"][name]
    return StdioServerParameters(command=spec["command"], args=spec["args"], cwd=REPO_ROOT)


class Recorder:
    def __init__(self) -> None:
        # (server, tool, args, result, refused, seconds, progress notifications, last message)
        self.steps: list[tuple[str, str, dict, Any, bool, float, int, str]] = []
        self.notes: list[str] = []
        self.t0 = time.monotonic()

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  note: {text}", flush=True)

    async def call(self, client: Client, server: str, tool: str, args: dict) -> dict:
        t0 = time.monotonic()
        heard: list[str] = []

        async def progress(value: float, total: float | None, message: str | None) -> None:
            heard.append(message or "")
            print(f"    … {message}", flush=True)

        result = await client.call_tool(tool, args, progress_callback=progress)
        seconds = time.monotonic() - t0
        data = result.structured_content or {"text": result.content[0].text}
        last = heard[-1] if heard else ""
        self.steps.append(
            (server, tool, args, data, bool(result.is_error), seconds, len(heard), last)
        )
        mark = "refused" if result.is_error else "ok"
        clock = (time.monotonic() - self.t0) / 60
        print(f"[{clock:5.1f} min] {server:10} {tool:22} {mark:8} {seconds:6.1f}s", flush=True)
        if result.is_error:
            raise RuntimeError(f"{tool} failed: {result.content[0].text}")
        return data


def first_ok(candidates: list[dict]) -> dict | None:
    return next((c for c in candidates if c["ok"]), None)


async def make_puppet(rec: Recorder, c: Any, bo: dict, known: dict | None) -> None:
    """Design rounds until a sheet passes its checks, then build from the passing sheets in
    order until one gives two consistent views (what the owner checks by eye). With `known`
    (resuming), sheets drawn before are tried first."""
    tried: set[str] = set()
    candidates = list(known["candidates"]) if known else []
    for round_no in range(ROUNDS + 1):
        for sheet in [x for x in candidates if x["ok"] and x["candidate_id"] not in tried]:
            if len(tried) == BUILDS:
                raise RuntimeError(f"no build of {BO['id']} gave consistent views in {BUILDS}")
            tried.add(sheet["candidate_id"])
            rec.note(f"chose {sheet['candidate_id']}: the next sheet whose checks passed")
            await c("choose_design", **bo, candidate_id=sheet["candidate_id"])
            built = await c("build_puppet", **bo, name=BO["name"])
            if built["views_consistent"]:
                return
            rec.note(f"{sheet['candidate_id']}'s views differ: {built['consistency_problems']}")
        if round_no == ROUNDS:
            break
        made = await c("design_character", **bo, description=BO["description"], n=SHEETS)
        candidates += made["candidates"]
    raise RuntimeError(f"no sheet of {BO['id']} passed its checks and built consistently")


async def build(rec: Recorder, resume: bool) -> None:
    async with AsyncExitStack() as stack:
        audio = await stack.enter_async_context(Client(server_params("audio_mcp")))
        anim = await stack.enter_async_context(Client(server_params("synfig_mcp")))
        art = await stack.enter_async_context(Client(server_params("comfy_mcp")))
        a = lambda tool, **args: rec.call(audio, "audio_mcp", tool, args)  # noqa: E731
        s = lambda tool, **args: rec.call(anim, "synfig_mcp", tool, args)  # noqa: E731
        c = lambda tool, **args: rec.call(art, "comfy_mcp", tool, args)  # noqa: E731
        film, shot = {"film": FILM}, {"film": FILM, "shot_id": SHOT}
        bo, pip = {**film, "character_id": BO["id"]}, {**film, "character_id": "pip"}
        place = {**film, "background_id": ORCHARD["id"]}

        # Sound that needs the GPU comes first, before the art jobs load their models.
        await a("describe_audio", **film)
        await a("compose", **film, cue_id="m01", mood="playful", duration_s=DURATION, energy=0.5)
        await s("build_rig", **pip)  # the reference puppet (the placeholder rig)
        await a("set_voice", **pip, **PIP_VOICE)

        state = await c("describe_art", **film)
        chars = {x["id"]: x for x in state["characters"]}
        places = {x["id"]: x for x in state["backgrounds"]}

        # The character: sheets → a choice → a rigged puppet whose two views match.
        known = chars.get(BO["id"])
        if resume and known and known["rig_path"] and known["built_from"] == known["chosen"]:
            rec.note(f"resumed: {BO['id']} is already built from {known['chosen']}")
        else:
            await make_puppet(rec, c, bo, known if resume else None)

        # The place: drafts → a choice → the plate → layers.
        known = places.get(ORCHARD["id"])
        if resume and known and known["next_step"].startswith("ready"):
            rec.note(f"resumed: {ORCHARD['id']} is already layered")
        else:
            chosen = None
            for round_no in range(1, ROUNDS + 1):
                made = await c(
                    "generate_background", **place, description=ORCHARD["description"], n=DRAFTS
                )
                chosen = first_ok(made["drafts"])
                if chosen:
                    break
                rec.note(f"round {round_no}: no draft passed its checks; painting more")
            if chosen is None:
                raise RuntimeError(f"no draft of {ORCHARD['id']} passed in {ROUNDS} rounds")
            rec.note(f"chose {chosen['candidate_id']}: the first draft whose checks passed")
            await c("choose_background", **place, candidate_id=chosen["candidate_id"])
            await c("split_depth_layers", **place)

        # Bo's voice and the lines, then the art previews (they render the line too).
        await a("set_voice", **bo, **BO_VOICE)
        bo_line = (await a("speak", **bo, lines=[{"text": BO_LINE}]))["lines"][0]
        pip_line = (await a("speak", **pip, lines=[{"text": PIP_LINE}]))["lines"][0]
        birds = await a(
            "find_sfx", queries=["birds singing in the countryside"], k=3, avoid=["traffic"]
        )
        bird_id = birds["results"][0]["sounds"][0]["sound_id"]
        puppet = await c(
            "preview_puppet", **bo, view="three_quarter", line=BO_LINE,
            background_id=ORCHARD["id"],
        )  # fmt: skip
        pan = await c(
            "preview_background", **place, move="slow_pan_right", duration_s=DURATION,
            character_id=BO["id"],
        )  # fmt: skip
        if not pan["ok"]:
            rec.note(f"the pan check failed: {pan['verdicts']}")
        await c("describe_art", **film)

        # The shot: Bo (three-quarter, facing Pip) waves and asks; Pip nods and answers.
        bo_start = 0.8
        bo_end = bo_start + bo_line["duration_s"]
        pip_start = round(bo_end + 0.4, 2)
        if pip_start + pip_line["duration_s"] > DURATION - 0.3:
            raise RuntimeError(f"the lines run past the {DURATION} s shot; shorten them")
        await s("create_scene", **shot, duration_s=DURATION, background=ORCHARD["id"],
                camera_move="slow_pan_right")  # fmt: skip
        await s("add_character", **shot, character_id=BO["id"], position=BO_AT,
                view="three_quarter", scale=puppet["scale"], facing="right")  # fmt: skip
        await s("add_character", **shot, character_id="pip", position=PIP_AT, facing="left")
        for who in (BO["id"], "pip"):
            w = {**shot, "character_id": who}
            await s("apply_motion", **w, motion="blink", start_s=0, duration_s=DURATION)
            await s("apply_motion", **w, motion="idle_breathe", start_s=0)
            await s("set_expression", **w, expr="happy", start_s=0)
        # Facing right, Bo's own left arm is the one toward Pip (preview_puppet's rule).
        await s("apply_motion", **shot, character_id=BO["id"], motion="wave", start_s=0.3,
                side="left", energy=0.6, cycles=2)  # fmt: skip
        await s("apply_motion", **shot, character_id="pip", motion="nod",
                start_s=round(bo_end - 0.6, 2))  # fmt: skip
        await s("apply_lipsync", **shot, character_id=BO["id"], line_id=bo_line["line_id"],
                start_s=bo_start)  # fmt: skip
        await s("apply_lipsync", **shot, character_id="pip", line_id=pip_line["line_id"],
                start_s=pip_start)  # fmt: skip
        await s("add_sound_effect", **shot, sound_id=bird_id, start_s=0.0, volume=0.3,
                query="birds singing in the countryside")  # fmt: skip
        await s("set_music", **shot, cue_id="m01", volume=0.45)
        await s("describe_shot", **shot)
        await s("render_preview_frame", **shot, time_s=round(bo_start + 1.0, 2))
        await a("preview_mix", **shot)
        await s("render_shot", **shot, quality="final")


def checks(rec: Recorder) -> list[tuple[bool, str]]:
    cfg = load_config()
    root = REPO_ROOT / "films" / FILM
    folder = root / "shots" / SHOT
    out: list[tuple[bool, str]] = []
    called = {tool for server, tool, *_ in rec.steps if server == "comfy_mcp"}
    out.append((called >= COMFY_TOOLS, f"all nine art tools called ({len(called & COMFY_TOOLS)})"))
    rig_file = root / "characters" / BO["id"] / "rig.json"
    rig = json.loads(rig_file.read_text()) if rig_file.is_file() else {"views": {}}
    views = rig["views"]
    faced = all("face" in v for v in views.values())
    out.append(
        (
            {"front", "three_quarter"} <= set(views) and faced,
            f"{BO['id']}: a rig with views {sorted(views)}, each with a face block",
        )
    )
    report_file = root / "characters" / BO["id"] / "build" / "report.json"
    report = json.loads(report_file.read_text()) if report_file.is_file() else {}
    consistency = report.get("consistency", {})
    out.append(
        (
            consistency.get("ok", False),
            f"{BO['id']}'s two views match {consistency.get('problems') or ''}".rstrip(),
        )
    )
    designed = (root / "characters" / BO["id"] / "design" / "candidates.json").is_file()
    out.append((designed, f"{BO['id']} was designed from words (candidates.json)"))
    layers_file = root / "backgrounds" / ORCHARD["id"] / "layers.json"
    layers = json.loads(layers_file.read_text())["layers"] if layers_file.is_file() else []
    out.append((len(layers) >= 3, f"{ORCHARD['id']}: {len(layers)} parallax layers"))
    pans = [d for _, tool, _, d, bad, *_ in rec.steps if tool == "preview_background" and not bad]
    checked = pans[-1]["frames_checked"] if pans else 0
    out.append((bool(pans) and pans[-1]["ok"], f"the pan shows no hole ({checked} frames checked)"))
    silent = [
        tool
        for server, tool, _, _, _, secs, heard, _ in rec.steps
        if server == "comfy_mcp" and secs > 30 and heard == 0
    ]
    out.append((not silent, f"every art call over 30 s sent progress notes {silent or ''}"))
    spec = json.loads((folder / "shot.json").read_text()) if folder.is_dir() else {}
    cast = {ch["id"] for ch in spec.get("characters", [])}
    out.append(
        (
            spec.get("background") == ORCHARD["id"] and {BO["id"], "pip"} <= cast,
            f"the shot: {sorted(cast)} in {spec.get('background')}",
        )
    )
    lines = spec.get("dialogue", [])
    cued = [d for d in lines if (root / "audio" / "lipsync" / f"{d['line_id']}.json").is_file()]
    out.append((len(cued) == len(lines) == 2, f"{len(lines)} voiced lines, each with mouth cues"))
    out.append((spec.get("music_cue") == "m01" and bool(spec.get("sfx")), "music and a sound"))
    mp4 = folder / "shot.mp4"
    streams: dict[str, Any] = {}
    if mp4.is_file():
        probe = subprocess.run(
            [str(cfg.path("tools", "ffprobe")), "-v", "error", "-show_entries",
             "stream=codec_type,width,height,nb_frames", "-of", "json", str(mp4)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        streams = {st["codec_type"]: st for st in json.loads(probe.stdout)["streams"]}
    v = streams.get("video", {})
    frames = str(round(DURATION * 24))
    out.append(
        (
            v.get("width") == 1920 and v.get("nb_frames") == frames,
            f"1080p video, {v.get('nb_frames')} frames",
        )
    )
    mix = folder / "mix.wav"
    loud = ffmpeg.measure(mix, cfg) if mix.is_file() else None
    out.append(
        (
            "audio" in streams
            and loud is not None
            # the mixer aims at -14 LUFS but trims the whole mix when a true peak still pokes
            # over -1.5 dBTP after its limiter (peaks win), so it may land a little under
            and -16 <= loud.integrated_lufs <= -13
            and loud.true_peak_db <= -1,
            "mixed soundtrack: "
            + (
                f"{loud.integrated_lufs:.1f} LUFS, {loud.true_peak_db:.1f} dBTP" if loud else "none"
            ),
        )
    )
    return out


def transcript(
    rec: Recorder, results: list[tuple[bool, str]], seconds: float, failure: str | None
) -> str:
    def short(value: Any) -> str:
        text = json.dumps(value, indent=1).replace(str(REPO_ROOT) + "/", "")
        return text if len(text) < 1200 else text[:1200] + "\n…"

    body = []
    for n, (server, tool, args, data, failed, secs, heard, last) in enumerate(rec.steps, 1):
        progress = f"; {heard} progress notes, last: “{last}”" if heard else ""
        body += [
            f"### {n}. `{server}.{tool}` ({secs:.1f} s{', refused' if failed else ''}{progress})",
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
    status = [f"- **Stopped early:** {failure}"] if failure else []
    return "\n".join(
        [
            "# Step 4's done-when shot: a new character in a new place, through three MCP servers",
            "",
            "Generated by `uv run scripts/run_step4_shot.py` (task 4.9). A scripted MCP client",
            "starts `comfy_mcp`, `audio_mcp` and `synfig_mcp` from `.mcp.json`. From words, it",
            "designs a character and builds its puppet, paints a place and splits it into",
            "parallax layers, checks both with the previews, then builds and renders a shot with",
            "them using only tool calls. Where the owner would choose, it takes the first",
            "candidate whose checks pass.",
            "",
            f"- Date: {date.today().isoformat()}; {len(rec.steps)} tool calls; "
            f"{seconds / 60:.0f} min.",
            f"- Character: `{BO['id']}`, “{BO['description']}”.",
            f"- Place: `{ORCHARD['id']}`, “{ORCHARD['description']}”.",
            f"- Video: `films/{FILM}/shots/{SHOT}/shot.mp4` (git-ignored).",
            *status,
            "",
            "## Checks",
            "",
            *[f"- [{'x' if ok else ' '}] {text}" for ok, text in results],
            "",
            *(["## Notes", "", *[f"- {n}" for n in rec.notes], ""] if rec.notes else []),
            "## Calls",
            "",
            *body,
        ]
    )


def comfy_running() -> bool:
    url = load_config().get("services", "comfyui_url")
    try:
        urllib.request.urlopen(url, timeout=1)
    except OSError:
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--resume", action="store_true", help="keep the film; skip art that is ready")
    args = ap.parse_args()
    root = REPO_ROOT / "films" / FILM
    if not args.resume or not root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
        Film.create(root, "storybook", load_manifest())
    if comfy_running():  # the music model needs the memory to itself (D-041)
        subprocess.run(["bash", str(REPO_ROOT / "scripts" / "comfy_server.sh"), "--stop"])
        if comfy_running():
            sys.exit("ComfyUI is running and this script didn't start it; stop it first")
    rec = Recorder()
    failure = None
    try:
        asyncio.run(build(rec, args.resume))
    except Exception as e:  # keep the transcript of what happened, then report
        while isinstance(e, BaseExceptionGroup) and e.exceptions:  # the clients' task groups
            e = e.exceptions[0]
        failure = f"{type(e).__name__}: {e}"
    seconds = time.monotonic() - rec.t0
    results = checks(rec)
    TRANSCRIPT.write_text(transcript(rec, results, seconds, failure))
    for ok, text in results:
        print(f"[{'x' if ok else ' '}] {text}")
    print(f"{len(rec.steps)} calls in {seconds / 60:.1f} min → {TRANSCRIPT.relative_to(REPO_ROOT)}")
    if failure:
        print(f"stopped early: {failure}")
    return 0 if not failure and all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
