"""Call the three MCP servers' tools through the MCP Inspector's CLI, via .mcp.json.

    uv run scripts/inspector_check.py           # needs films/step2-demo (scripts/make_demo_film.py)

This exercises the three servers the way an outside client does: the Inspector starts each from
.mcp.json over stdio, lists the tools, and calls them, plus calls that must be refused with a
fixable message. The audio part casts, speaks, lip-syncs, composes and searches, then places the
results in the shot through synfig_mcp and previews the mix (it runs Kokoro, Rhubarb, ACE-Step
and CLAP). The art part (comfy_mcp) describes the art, chooses a design and renders both
previews of a generated puppet (Kit, copied from films/step4-demo when it is there). Its GPU
jobs (design_character, build_puppet, generate_background, choose_background,
split_depth_layers) take minutes each, so here they only get requests they must refuse; task
4.9's scripted client runs them for real. It works on a scratch copy, films/inspector-check/,
made fresh on every run (films/ is git-ignored). Prints one line per call; exits 1 if any call
didn't do what was expected. The Inspector is pinned (INSPECTOR) and fetched by npx on first
use.
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
PIP_FILM = {"film": FILM, "character_id": "pip"}

# (tool, arguments, expect an error?)
CALLS: list[tuple[str, dict[str, Any], bool]] = [
    ("describe_film", {"film": FILM}, False),
    ("build_rig", {"film": FILM, "character_id": "owl"}, False),
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
    ("add_character", {**SHOT, "character_id": "fox", "position": [0.5, 0.9]}, True),
]


def call(tool: str | None, args: dict[str, Any], server: str = "synfig_mcp") -> dict[str, Any]:
    cmd = [
        "npx",
        "-y",
        INSPECTOR,
        "--cli",
        "--config",
        ".mcp.json",
        "--server",
        server,
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
    short = lambda x: str(x).replace(str(REPO_ROOT) + "/", "")  # noqa: E731
    if "mix_path" in data:
        levels = f"{data['integrated_lufs']} LUFS, {data['true_peak_db']} dBTP"
        return f"{short(data['mix_path'])} ({levels})"
    if "audio_path" in data:
        made = f"{data['duration_s']} s, peak {data['peak_memory_gb']} GB"
        return f"{short(data['audio_path'])} ({made})"
    if "styles" in data:  # describe_art
        chars = {c["id"]: c["next_step"].split(":")[0] for c in data["characters"]}
        places = [b["id"] for b in data["backgrounds"]]
        return f"style {data['style']}, characters {chars}, places {places}"
    if "frames_checked" in data:  # preview_background
        verdict = "no holes" if data["ok"] else f"HOLES in {len(data['holes'])} frames"
        return f"{verdict} ({data['frames_checked']} frames checked): {short(data['video_path'])}"
    for key in ("change", "video_path", "image_path", "rig_path", "voice_path"):
        if key in data:
            return short(data[key])
    if "spec" in data:
        return f"{data['n_frames']} frames, errors {data['errors']}, warnings {data['warnings']}"
    if "installed_voices" in data:
        chars = [c["id"] for c in data["characters"]]
        return f"characters {chars}, lines {len(data['lines'])}, sounds {data['sound_library']}"
    if "characters" in data:
        chars = [c["id"] for c in data["characters"]]
        return f"characters {chars}, lines {len(data['dialogue_lines'])}"
    if "results" in data:
        return "; ".join(
            f"{r['query']} → {[x['sound_id'] for x in r['sounds'][:2]]}" for r in data["results"]
        )
    if "lines" in data:
        return ", ".join(f"{x['line_id']} ({x['duration_s']} s)" for x in data["lines"])
    if isinstance(data.get("result"), list):  # list results (lipsync)
        return ", ".join(f"{x['line_id']}: {x['n_cues']} cues" for x in data["result"])
    return json.dumps(data)[:150]


def main() -> int:
    films = REPO_ROOT / "films"
    if not (films / "step2-demo").is_dir():
        sys.exit("films/step2-demo is missing: run scripts/make_demo_film.py first")
    shutil.rmtree(films / FILM, ignore_errors=True)
    shutil.copytree(films / "step2-demo", films / FILM, ignore=shutil.ignore_patterns("shots"))
    kit = films / "step4-demo" / "characters" / "kit"
    if kit.is_dir():  # a generated puppet, for the art previews
        shutil.copytree(kit, films / FILM / "characters" / "kit")

    results = {"ok": 0, "bad": 0}

    def check(tool: str, args: dict, want_error: bool = False, server: str = "synfig_mcp"):
        result = call(tool, args, server)
        got_error = bool(result.get("isError"))
        good = got_error == want_error
        results["ok" if good else "bad"] += 1
        mark = "ok " if good else "BAD"
        kind = "refused" if got_error else "done"
        print(f"{mark} {server[:6]} {tool:24} {kind:8} {summary(result)}")
        return result.get("structuredContent") or {}

    for server, expected in (("synfig_mcp", 16), ("audio_mcp", 7), ("comfy_mcp", 9), ("edit_mcp", 4)):
        tools = call(None, {}, server).get("tools", [])
        results["ok" if len(tools) == expected else "bad"] += 1
        print(f"tools/list {server}: {len(tools)} tools: {', '.join(t['name'] for t in tools)}")
    for tool, args, want_error in CALLS:
        check(tool, args, want_error)

    # the sound side (audio_mcp), then placing its results in the shot (synfig_mcp)
    audio = "audio_mcp"
    check("describe_audio", {"film": FILM}, server=audio)
    voice = {"film": FILM, "character_id": "pip", "voices": [{"id": "af_heart"}]}
    check("set_voice", {**voice, "speed": 1.08, "pitch_semitones": 2}, server=audio)
    spoken = check("speak", {**PIP_FILM, "lines": [{"text": "Look, a kite!"}]}, server=audio)
    line_id = spoken["lines"][0]["line_id"] if spoken.get("lines") else "l999"
    check("lipsync", {"film": FILM, "line_ids": [line_id]}, server=audio)
    check(
        "compose", {"film": FILM, "cue_id": "m01", "mood": "playful", "duration_s": 4}, server=audio
    )
    found = check("find_sfx", {"queries": ["a door opening"], "k": 3}, server=audio)
    sound_id = found["results"][0]["sounds"][0]["sound_id"] if found.get("results") else "none"
    check("add_sound_effect", {**SHOT, "sound_id": sound_id, "start_s": 1.0})
    check("set_music", {**SHOT, "cue_id": "m01", "volume": 0.4})
    check("apply_lipsync", {**PIP, "line_id": line_id, "start_s": 0.5})
    check("preview_mix", SHOT, server=audio)
    edit = "edit_mcp"
    check("describe_edit", {"film": "no-such-film"}, True, edit)
    check("assemble", {"film": "no-such-film", "shots": ["s01_sh01"]}, True, edit)
    check("create_film", {"film": "Bad Name", "title": "x"}, True, edit)
    check("render_film", {"film": "no-such-film"}, True, edit)
    check("speak", {**PIP_FILM, "lines": [{"text": "What the hell"}]}, True, audio)
    check(
        "compose", {"film": FILM, "cue_id": "m02", "mood": "spooky", "duration_s": 4}, True, audio
    )

    # the art side (comfy_mcp): describe, choose and preview; the GPU jobs only refused
    art = "comfy_mcp"
    kit_args = {"film": FILM, "character_id": "kit"}
    meadow = {"film": FILM, "background_id": "meadow"}
    check("describe_art", {"film": FILM}, server=art)
    if kit.is_dir():
        chosen = json.loads((kit / "design" / "candidates.json").read_text()).get("chosen", "c1")
        check("choose_design", {**kit_args, "candidate_id": chosen}, server=art)
        check("preview_puppet", kit_args, server=art)
        check("preview_background", {**meadow, "duration_s": 3, "character_id": "kit"}, server=art)
    else:
        print("note: films/step4-demo has no Kit; the puppet previews are skipped")
        check("preview_background", {**meadow, "duration_s": 3}, server=art)
    for tool, args in (
        ("design_character", {**kit_args, "description": "a bloody fox"}),
        ("design_character", {**PIP_FILM, "description": "a small owl"}),
        ("choose_design", {**kit_args, "candidate_id": "c99"}),
        ("build_puppet", {"film": FILM, "character_id": "fox"}),
        ("preview_puppet", PIP_FILM),
        ("generate_background", {**meadow, "description": "a dark wood", "n": 12}),
        ("choose_background", {**meadow, "candidate_id": "c1"}),
        ("split_depth_layers", meadow),
    ):
        check(tool, args, True, art)

    total = results["ok"] + results["bad"]
    print(f"\n{results['ok']}/{total} as expected")
    return 1 if results["bad"] else 0


if __name__ == "__main__":
    sys.exit(main())
