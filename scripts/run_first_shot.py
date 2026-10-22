"""Step 2's done-when: an LLM directs a shot through synfig_mcp, from Claude Code as the client.

    uv run scripts/make_demo_film.py          # once: the demo assets
    uv run scripts/run_first_shot.py [--model sonnet]

Runs Claude Code headless (`claude -p`) with only the synfig_mcp tools (from .mcp.json; every
built-in tool is disabled), on a fresh film folder films/first-shot/ that has the assets but no
shot. The prompt says *what* the shot should be, never which tools to call. Then it:

- writes the transcript (every tool call, its arguments and its result) to
  docs/learning/mcp-first-shot.md, and the raw event stream to films/first-shot/transcript.jsonl
- checks the result against Step 2's done-when: a 10-second shot, a rigged character waving and
  blinking, a parallax background, a mouth cue track, and a rendered 1080p video with audio

Uses the owner's Claude Code login and usage. Safe to re-run: the film folder and the transcript
are rebuilt every time. Exits 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date
from typing import Any

from studio_core.config import REPO_ROOT, load_config

FILM = REPO_ROOT / "films" / "first-shot"
DEMO = REPO_ROOT / "films" / "step2-demo"
TRANSCRIPT = REPO_ROOT / "docs" / "learning" / "mcp-first-shot.md"
PREFIX = "mcp__synfig_mcp__"

PROMPT = """\
You are directing one shot of a children's cut-out animated film, using the synfig_mcp tools.
The film is called 'first-shot'.

Make shot s01_sh01, 10 seconds long. Pip stands near the bottom centre of the frame in the
meadow, and the camera slowly pans to the right. Pip looks happy, blinks naturally and breathes
the whole time, waves with the left arm starting at about 1 second, and says Pip's recorded line
starting at 1.5 seconds, so the mouth moves with the words.

Check your work before the final render (the shot's warnings, and a preview frame or two), then
render the final video. Finish with a short summary and the video's path."""


def cli_env() -> dict[str, str]:
    """The environment for `claude`. Started from inside a Claude Code session, it would inherit
    that session's auth proxy and host-managed token refresh, and fail ("OAuth session expired").
    Dropping them makes it use the CLI's own login, as when run from a terminal."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE", "ANTHROPIC_", "USE_LOCAL_OAUTH", "USE_STAGING_OAUTH"))
    }


def logged_in() -> bool:
    out = subprocess.run(
        ["claude", "auth", "status"], env=cli_env(), capture_output=True, text=True
    ).stdout
    try:
        return bool(json.loads(out).get("loggedIn"))
    except ValueError:
        return False


def run_claude(model: str | None, budget: float | None) -> tuple[list[dict[str, Any]], float]:
    cmd = [
        "claude",
        "-p",
        PROMPT,
        "--mcp-config",
        str(REPO_ROOT / ".mcp.json"),
        "--strict-mcp-config",
        "--tools",
        "",
        "--allowedTools",
        f"{PREFIX}*",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
    ]
    if model:
        cmd += ["--model", model]
    if budget:
        cmd += ["--max-budget-usd", str(budget)]
    t0 = time.monotonic()
    events = []
    raw = FILM / "transcript.jsonl"
    env = cli_env()
    with (
        raw.open("w") as log,
        subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, text=True) as proc,
    ):
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            if not line.strip():
                continue
            event = json.loads(line)
            events.append(event)
            for block in event.get("message", {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    print(f"  → {block['name'].removeprefix(PREFIX)}", flush=True)
    if proc.returncode != 0:
        sys.exit(f"claude exited with {proc.returncode}; see {raw}")
    return events, time.monotonic() - t0


def result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))


def abridge(text: str, limit: int = 1200) -> str:
    text = text.replace(str(REPO_ROOT) + "/", "")
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more chars)"


def transcript_md(events: list[dict[str, Any]], seconds: float, checks: list[str]) -> str:
    init = next((e for e in events if e.get("type") == "system"), {})
    final = next((e for e in events if e.get("type") == "result"), {})
    results = {}
    for e in events:
        if e.get("type") == "user":
            for block in e["message"].get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results[block["tool_use_id"]] = block
    body: list[str] = []
    n = 0
    for e in events:
        if e.get("type") != "assistant":
            continue
        for block in e["message"].get("content", []):
            if block.get("type") == "text" and block["text"].strip():
                body.append("> " + block["text"].strip().replace("\n", "\n> ") + "\n")
            elif block.get("type") == "tool_use":
                n += 1
                res = results.get(block["id"], {})
                status = "refused" if res.get("is_error") else "ok"
                body.append(f"### {n}. `{block['name'].removeprefix(PREFIX)}` ({status})\n")
                body.append("```json\n" + json.dumps(block["input"], indent=1) + "\n```\n")
                body.append(
                    "Result:\n\n```\n" + abridge(result_text(res.get("content", ""))) + "\n```\n"
                )
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout
    return "\n".join(
        [
            "# The first shot, directed through MCP",
            "",
            "Step 2's done-when (task 2.8): from Claude Code as the MCP client, an LLM builds and",
            "renders a 10-second shot with a rigged character waving and blinking in front of a",
            "parallax background, with a mouth cue track driving the mouth.",
            "",
            "Generated by `uv run scripts/run_first_shot.py`, which runs Claude Code headless",
            "with only the 14 synfig_mcp tools (all built-in tools disabled) and rewrites this",
            "file. The prompt says what the shot is, not which tools to use.",
            "",
            "## Run",
            "",
            f"- Date: {date.today().isoformat()}",
            f"- Client: Claude Code {version.strip()}, model `{init.get('model', '?')}`",
            f"- Tool calls: {n}, turns: {final.get('num_turns', '?')}, wall time: {seconds:.0f} s",
            "",
            "## Prompt",
            "",
            "> " + PROMPT.replace("\n", "\n> "),
            "",
            "## Checks against the done-when",
            "",
            *checks,
            "",
            "## Transcript",
            "",
            "Every tool call with its arguments and result (long results abridged), and the",
            "model's own words as quotes.",
            "",
            *body,
        ]
    )


def check_result() -> list[str]:
    """The done-when, checked from the saved spec and the rendered video."""
    cfg = load_config()
    checks: list[tuple[bool, str]] = []
    spec_file = FILM / "shots" / "s01_sh01" / "shot.json"
    if not spec_file.is_file():
        return ["- [ ] shot s01_sh01 was created"]
    spec = json.loads(spec_file.read_text())
    checks.append((spec["duration_s"] == 10, f"10-second shot (got {spec['duration_s']} s)"))
    layers = json.loads((FILM / "backgrounds" / spec["background"] / "layers.json").read_text())
    factors = sorted({layer["parallax"] for layer in layers["layers"]})
    moving = spec.get("camera", {}).get("move", "static") != "static"
    checks.append(
        (len(factors) > 1 and moving, f"parallax background {factors} with a camera move")
    )
    chars = spec["characters"]
    rigged = [c for c in chars if (FILM / "characters" / c["id"] / "rig.json").is_file()]
    motions = {a["motion"] for c in rigged for a in c.get("actions", [])}
    checks.append(("wave" in motions, f"a rigged character waves (motions: {sorted(motions)})"))
    checks.append(("blink" in motions, "and blinks"))
    lines = spec.get("dialogue", [])
    cued = [d for d in lines if (FILM / "audio" / "lipsync" / f"{d['line_id']}.json").is_file()]
    speakers = {d["character"] for d in cued}
    checks.append(
        (bool(cued) and speakers <= {c["id"] for c in rigged}, f"mouth cue track: {len(cued)} line")
    )
    mp4 = FILM / "shots" / "s01_sh01" / "shot.mp4"
    if mp4.is_file():
        probe = subprocess.run(
            [str(cfg.path("tools", "ffprobe")), "-v", "error", "-show_entries",
             "stream=codec_type,width,height,nb_frames", "-of", "json", str(mp4)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        streams = {s["codec_type"]: s for s in json.loads(probe.stdout)["streams"]}
        video = streams.get("video", {})
        size = f"{video.get('width')}x{video.get('height')}"
        checks.append(
            (
                size == "1920x1080" and video.get("nb_frames") == "240" and "audio" in streams,
                f"rendered video: {size}, {video.get('nb_frames')} frames, audio: "
                f"{'audio' in streams} ({mp4.relative_to(REPO_ROOT)})",
            )
        )
    else:
        checks.append((False, "rendered video shot.mp4"))
    return [f"- [{'x' if ok else ' '}] {text}" for ok, text in checks]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", help="Claude Code model alias or id (default: your default)")
    ap.add_argument("--max-budget-usd", type=float, help="stop the run past this API spend")
    args = ap.parse_args()
    if not DEMO.is_dir():
        sys.exit("films/step2-demo is missing: run scripts/make_demo_film.py first")
    if not logged_in():
        sys.exit("the claude CLI is not logged in here: run `claude auth login` in this shell")
    shutil.rmtree(FILM, ignore_errors=True)
    shutil.copytree(DEMO, FILM, ignore=shutil.ignore_patterns("shots"))

    print("Claude Code is directing the shot…")
    events, seconds = run_claude(args.model, args.max_budget_usd)
    checks = check_result()
    TRANSCRIPT.write_text(transcript_md(events, seconds, checks))
    print("\n".join(checks))
    print(f"\ntranscript: {TRANSCRIPT.relative_to(REPO_ROOT)} ({seconds:.0f} s)")
    return 0 if all(c.startswith("- [x]") for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
