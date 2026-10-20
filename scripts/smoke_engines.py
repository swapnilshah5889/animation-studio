"""Engine smoke tests: prove Synfig and MLT render MP4s from the command line.

    uv run scripts/smoke_engines.py synfig            # fixtures/smoke/smoke.sif -> PNGs -> MP4
    uv run scripts/smoke_engines.py melt --wav x.wav  # color clip + a WAV -> MP4 via MLT XML
    uv run scripts/smoke_engines.py all --wav x.wav

Outputs go to ~/ai-studio/scratch/smoke/ (outside the repo). Each run starts clean, so it is safe to
re-run. Every output is checked with ffprobe (frame count, duration, streams), not just "exit 0".
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from studio_core.config import REPO_ROOT, StudioConfig, load_config

OUT = Path.home() / "ai-studio" / "scratch" / "smoke"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "smoke" / "smoke.sif"


def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)  # type: ignore[call-overload]
    if proc.returncode != 0:
        sys.exit(f"FAILED ({proc.returncode}):\n{proc.stderr[-3000:]}")
    return proc


def probe(cfg: StudioConfig, path: Path) -> dict[str, object]:
    proc = run(
        [
            str(cfg.path("tools", "ffprobe")),
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,nb_read_frames,sample_rate:format=duration",
            "-of",
            "json",
            str(path),
        ]
    )
    data = json.loads(proc.stdout)
    return {"duration_s": float(data["format"]["duration"]), "streams": data["streams"]}


def audio_duration(cfg: StudioConfig, path: Path) -> float:
    proc = run(
        [
            str(cfg.path("tools", "ffprobe")),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    return float(proc.stdout.strip())


def make_part(cfg: StudioConfig, path: Path, color: str, size: str) -> None:
    """A flat-colored PNG standing in for a cut-out puppet part."""
    run(
        [
            str(cfg.path("tools", "ffmpeg")),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={size}",
            "-frames:v",
            "1",
            str(path),
        ]
    )


def smoke_synfig(cfg: StudioConfig) -> Path:
    work = OUT / "synfig"
    shutil.rmtree(work, ignore_errors=True)
    (work / "frames").mkdir(parents=True)
    shutil.copy(FIXTURE, work / "smoke.sif")
    make_part(cfg, work / "torso.png", "orange", "200x300")
    make_part(cfg, work / "arm.png", "0x8B4513", "50x200")

    start = time.perf_counter()
    run(
        [
            str(cfg.path("tools", "synfig")),
            str(work / "smoke.sif"),
            "-t",
            "png",
            "-o",
            str(work / "frames" / "frame.png"),
        ]
    )
    render_s = time.perf_counter() - start
    frames = sorted((work / "frames").glob("*.png"))
    print(f"synfig rendered {len(frames)} PNG frames in {render_s:.1f}s")

    mp4 = work / "smoke_synfig.mp4"
    run(
        [
            str(cfg.path("tools", "ffmpeg")),
            "-y",
            "-v",
            "error",
            "-framerate",
            "24",
            "-pattern_type",
            "glob",
            "-i",
            str(work / "frames" / "*.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(mp4),
        ]
    )
    info = probe(cfg, mp4)
    video = info["streams"][0]  # type: ignore[index]
    assert video["width"] == 1280 and video["height"] == 720, video
    assert int(video["nb_read_frames"]) == len(frames) == 49, (video, len(frames))  # 0f..48f
    print(f"OK synfig -> {mp4}  {json.dumps(info)}")
    return mp4


MLT_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<!-- Step 0 smoke test: a color clip with a voice line starting at 0.5 s, as an MLT project. -->
<mlt LC_NUMERIC="C" producer="main">
  <profile description="HD 1080p 24 fps" width="1920" height="1080" progressive="1"
           sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="16"
           display_aspect_den="9" frame_rate_num="24" frame_rate_den="1" colorspace="709"/>
  <producer id="bg" in="0" out="{last}">
    <property name="mlt_service">color</property>
    <property name="resource">#4a7ab8</property>
  </producer>
  <producer id="voice">
    <property name="resource">{wav}</property>
  </producer>
  <playlist id="video_track">
    <entry producer="bg" in="0" out="{last}"/>
  </playlist>
  <playlist id="audio_track">
    <blank length="12"/>
    <entry producer="voice"/>
  </playlist>
  <tractor id="main" in="0" out="{last}">
    <multitrack>
      <track producer="video_track"/>
      <track producer="audio_track" hide="video"/>
    </multitrack>
    <transition>
      <property name="mlt_service">mix</property>
      <property name="a_track">0</property>
      <property name="b_track">1</property>
      <property name="always_active">1</property>
      <property name="sum">1</property>
    </transition>
  </tractor>
</mlt>
"""


def smoke_melt(cfg: StudioConfig, wav: Path) -> Path:
    work = OUT / "melt"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    # The color clip (video track) sets the length: the voice line plus 0.5 s lead-in, rounded up
    # to whole seconds with at least 0.5 s of tail. Audio shorter than video keeps the length.
    fps = 24
    seconds = math.ceil(audio_duration(cfg, wav) + 1.0)
    project = work / "smoke.mlt"
    project.write_text(MLT_TEMPLATE.format(last=seconds * fps - 1, wav=wav.resolve()))

    mp4 = work / "smoke_melt.mp4"
    run(
        [
            str(cfg.path("tools", "melt")),
            "-silent",
            str(project),
            "-consumer",
            f"avformat:{mp4}",
            "vcodec=libx264",
            "acodec=aac",
            "pix_fmt=yuv420p",
        ]
    )
    info = probe(cfg, mp4)
    kinds = {s["codec_type"]: s for s in info["streams"]}  # type: ignore[union-attr]
    assert {"video", "audio"} <= kinds.keys(), kinds
    assert kinds["video"]["width"] == 1920, kinds["video"]
    assert int(kinds["video"]["nb_read_frames"]) == seconds * fps, kinds["video"]
    assert abs(float(info["duration_s"]) - seconds) < 0.2, info  # type: ignore[arg-type]
    print(f"OK melt -> {mp4}  {json.dumps(info)}")
    return mp4


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("engine", choices=["synfig", "melt", "all"])
    parser.add_argument("--wav", type=Path, help="audio for the melt test (e.g. the Kokoro sample)")
    args = parser.parse_args()
    cfg = load_config()
    if args.engine in ("synfig", "all"):
        smoke_synfig(cfg)
    if args.engine in ("melt", "all"):
        if not args.wav:
            parser.error("melt needs --wav")
        smoke_melt(cfg, args.wav)
    return 0


if __name__ == "__main__":
    sys.exit(main())
