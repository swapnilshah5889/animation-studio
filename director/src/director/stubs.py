"""Dry-run stand-ins for the slow tools (`director ... --dry-run`).

A dry run uses the real LLM and the real cheap tools (describe_*, create_scene, add_character, ...
which also validate every call), and replaces only what needs a GPU, a long render or a second
model:
music, the picture renders, the vision checks and the art tools. It shows the plan and the
approval stops without waiting an hour. Nothing here is used by a real run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from director.hub import ProgressFn, ToolDispatcher, ToolInfo, ToolResult

Handler = Callable[[dict[str, Any]], dict[str, Any]]


def _silent_mp4(path: Path, seconds: float, size: str = "64x36") -> None:
    """A tiny black clip with a silent audio track, so the real edit and its checks accept it."""
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={size}:r=24",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


def handlers(films_root: Path, template_music: Path) -> dict[str, Handler]:
    def film(a: dict[str, Any]) -> Path:
        return films_root / a["film"]

    def compose(a: dict[str, Any]) -> dict[str, Any]:
        out = film(a) / "audio" / "music"
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy(template_music.with_suffix(".wav"), out / f"{a['cue_id']}.wav")
        meta = json.loads(template_music.with_suffix(".json").read_text())
        meta.update(cue_id=a["cue_id"], mood=a["mood"], duration_s=a["duration_s"], dry_run=True)
        (out / f"{a['cue_id']}.json").write_text(json.dumps(meta, indent=2))
        return {"cue_id": a["cue_id"], "dry_run": True}

    def render_shot(a: dict[str, Any]) -> dict[str, Any]:
        folder = film(a) / "shots" / a["shot_id"]
        spec = json.loads((folder / "shot.json").read_text())
        _silent_mp4(folder / "shot.mp4", spec["duration_s"])
        return {"path": str(folder / "shot.mp4"), "dry_run": True}

    def preview_frame(a: dict[str, Any]) -> dict[str, Any]:
        return {"path": "(dry run: no picture rendered)", "time_s": a["time_s"], "dry_run": True}

    def check_frame(a: dict[str, Any]) -> dict[str, Any]:
        return {
            "time_s": a["time_s"],
            "ok": True,
            "code_ok": True,
            "code_findings": [],
            "problems": [],
            "matches": [],
            "description": "(dry run)",
            "dry_run": True,
        }

    def check_film(a: dict[str, Any]) -> dict[str, Any]:
        shots = sorted(p.name for p in (film(a) / "shots").iterdir() if p.is_dir())
        rows = [
            {
                "shot_id": s,
                "ok": True,
                "dialogue": [],
                "frames": [{"ok": True, "problems": [], "code_findings": []}],
            }
            for s in shots
        ]
        return {"ok": True, "needs_human": False, "shots": rows, "summary": [], "dry_run": True}

    def art(tool: str) -> Handler:
        def refuse(a: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError(f"dry run: {tool} would run a GPU job; import the assets instead")

        return refuse

    return {
        "compose": compose,
        "render_shot": render_shot,
        "render_preview_frame": preview_frame,
        "check_frame": check_frame,
        "check_film": check_film,
        "check_safety": lambda a: {"ok": True, "needs_human": False, "dry_run": True},
        **{
            t: art(t)
            for t in (
                "design_character",
                "choose_design",
                "build_puppet",
                "generate_background",
                "choose_background",
                "split_depth_layers",
            )
        },
    }


class StubbedHub:
    """The real hub, except for the tools that have a stand-in."""

    def __init__(self, real: ToolDispatcher, stubs: dict[str, Handler]) -> None:
        self.real, self.stubs = real, stubs
        self.tools: dict[str, ToolInfo] = real.tools

    async def call(
        self, tool: str, args: dict[str, Any], on_progress: ProgressFn | None = None
    ) -> ToolResult:
        if tool not in self.stubs:
            return await self.real.call(tool, args, on_progress)
        try:
            data = self.stubs[tool](args)
        except Exception as err:
            return ToolResult(f"{type(err).__name__}: {err}", refused=True)
        return ToolResult(json.dumps(data), data=data)
