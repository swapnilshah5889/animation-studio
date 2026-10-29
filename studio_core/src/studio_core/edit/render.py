"""Render edit/film.mlt to edit/final.mp4 with melt, then verify the result.

melt re-encodes finished shot MP4s fast (docs/benchmarks.md: 8.8 s for 60 s of 1080p, against
250 s from PNG sequences), so it only ever assembles finished videos. The checks are the film's
"done" facts: a video and an audio stream, the expected size, a duration equal to the sum of the
clips minus the crossfade overlaps, and a loudness within 1 LU of the shot target (-14 LUFS).
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio_core.audio import ffmpeg
from studio_core.audio.mix import settings as mix_settings
from studio_core.config import StudioConfig, load_config
from studio_core.edit.spec import FINAL_SIZE, EditError, total_seconds

QUALITIES: dict[str, dict[str, Any]] = {
    "preview": {"size": (640, 360), "crf": 28, "preset": "veryfast"},
    "final": {"size": FINAL_SIZE, "crf": 18, "preset": "medium"},
}
DURATION_TOLERANCE_S = 0.15  # AAC pads the audio by a frame or two
LOUDNESS_TOLERANCE_LU = 1.0


@dataclass
class Probe:
    width: int
    height: int
    duration_s: float
    has_video: bool
    has_audio: bool


def probe(path: Path, cfg: StudioConfig | None = None) -> Probe:
    cfg = cfg or load_config()
    proc = subprocess.run(
        [
            str(cfg.path("tools", "ffprobe")),
            *("-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise EditError(f"{path.name} is not a readable video: {proc.stderr.strip()[-300:]}")
    data = json.loads(proc.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    return Probe(
        int(video["width"]) if video else 0,
        int(video["height"]) if video else 0,
        float(data["format"]["duration"]),
        video is not None,
        any(s["codec_type"] == "audio" for s in data["streams"]),
    )


@dataclass
class RenderReport:
    path: Path
    quality: str
    width: int
    height: int
    duration_s: float
    expected_duration_s: float
    integrated_lufs: float | None
    true_peak_db: float | None
    normalised_db: float | None  # gain applied to bring the loudness in range, else None
    render_seconds: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def run_melt(
    mlt: Path,
    out: Path,
    quality: str,
    fps: int,
    progress: Callable[[int], None] | None = None,
    cfg: StudioConfig | None = None,
) -> None:
    cfg = cfg or load_config()
    q = QUALITIES[quality]
    w, h = q["size"]
    out.unlink(missing_ok=True)
    cmd = [
        str(cfg.path("tools", "melt")),
        str(mlt),
        *("-consumer", f"avformat:{out}"),
        *("vcodec=libx264", f"crf={q['crf']}", f"preset={q['preset']}", "pix_fmt=yuv420p"),
        *("acodec=aac", "ab=192k", "ar=48000", "channels=2"),
        *(f"width={w}", f"height={h}", f"frame_rate_num={fps}", "frame_rate_den=1"),
    ]
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
    assert proc.stderr is not None
    tail = b""
    last = -1
    while chunk := proc.stderr.read(256):
        tail = (tail + chunk)[-2000:]
        found = re.findall(rb"percentage:\s*(\d+)", chunk)
        if found and progress and int(found[-1]) != last:
            last = int(found[-1])
            progress(last)
    if proc.wait() != 0 or not out.is_file():
        raise EditError(f"melt failed ({proc.returncode}): {tail.decode(errors='replace')[-600:]}")


def _apply_gain(path: Path, gain_db: float, cfg: StudioConfig) -> None:
    tmp = path.with_name("final.gain.mp4")
    ffmpeg.run(
        [
            *("-i", str(path), "-c:v", "copy", "-af", f"volume={gain_db:.2f}dB"),
            *("-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp)),
        ],
        cfg,
    )
    tmp.replace(path)


def verify(
    path: Path, spec: dict[str, Any], quality: str, cfg: StudioConfig | None = None
) -> RenderReport:
    """Probe and measure `path`; brings the loudness into range with one linear gain if needed."""
    cfg = cfg or load_config()
    want_size = QUALITIES[quality]["size"]
    want_s = total_seconds(spec)
    p = probe(path, cfg)
    problems: list[str] = []
    if not p.has_video:
        problems.append("no video stream")
    if not p.has_audio:
        problems.append("no audio stream")
    if (p.width, p.height) != want_size:
        problems.append(f"size is {p.width}x{p.height}, expected {want_size[0]}x{want_size[1]}")
    if abs(p.duration_s - want_s) > DURATION_TOLERANCE_S:
        problems.append(f"duration is {p.duration_s:.2f} s, expected {want_s:.2f} s")

    lufs = peak = gain = None
    if p.has_audio:
        target = mix_settings(cfg)["target_lufs"]
        loud = ffmpeg.measure(path, cfg)
        if not math.isinf(loud.integrated_lufs) and (
            abs(loud.integrated_lufs - target) > LOUDNESS_TOLERANCE_LU
        ):
            gain = ffmpeg.gain_to(loud, target)
            _apply_gain(path, gain, cfg)
            loud = ffmpeg.measure(path, cfg)
        lufs, peak = round(loud.integrated_lufs, 1), round(loud.true_peak_db, 1)
        if math.isinf(loud.integrated_lufs):
            problems.append("the film's audio is silent")
        elif abs(loud.integrated_lufs - target) > LOUDNESS_TOLERANCE_LU:
            problems.append(f"loudness is {lufs} LUFS, target {target} (±1)")
    return RenderReport(
        path,
        quality,
        p.width,
        p.height,
        round(p.duration_s, 3),
        round(want_s, 3),
        lufs,
        peak,
        round(gain, 2) if gain is not None else None,
        problems=problems,
    )
