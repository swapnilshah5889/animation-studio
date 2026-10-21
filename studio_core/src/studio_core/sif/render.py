"""Render a .sif with the Synfig CLI, and encode the frames to MP4 with ffmpeg.

Pipeline rule from the Step 0 benchmarks: Synfig writes PNG frames, ffmpeg encodes each shot,
and melt only assembles finished MP4s. Binary paths come from config/studio.toml.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from studio_core.config import StudioConfig, load_config
from studio_core.sif.validate import validate_sif


class RenderError(RuntimeError):
    pass


def run_tool(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run synfig or ffmpeg; raise RenderError with the tail of stderr if it fails."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # Quirk: synfig prints warnings (e.g. the missing JPEG module) on stderr and exits 0 on success.
    if proc.returncode != 0:
        raise RenderError(f"{Path(cmd[0]).name} failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return proc


def render_frames(
    sif: Path,
    out_dir: Path,
    *,
    begin: int | None = None,
    end: int | None = None,
    size: tuple[int, int] | None = None,
    cfg: StudioConfig | None = None,
    validate: bool = True,
) -> list[Path]:
    """Render frames begin..end (inclusive; default: the whole canvas) to out_dir/frame.NNNN.png.

    The file is validated first (studio_core.sif.validate); pass validate=False only to
    reproduce a CLI failure on purpose."""
    if validate:
        issues = validate_sif(sif)
        if issues:
            raise RenderError(f"{sif.name} would not render correctly: " + "; ".join(issues))
    cfg = cfg or load_config()
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    cmd = [
        str(cfg.path("tools", "synfig")),
        str(sif),
        "-t",
        "png",
        "-o",
        str(out_dir / "frame.png"),
    ]
    if begin is not None:
        cmd += ["--begin-time", f"{begin}f"]
    if end is not None:
        cmd += ["--end-time", f"{end}f"]
    if size:
        cmd += ["-w", str(size[0]), "-h", str(size[1])]
    run_tool(cmd)
    frames = sorted(out_dir.glob("frame*.png"))
    if not frames:
        raise RenderError(f"synfig wrote no frames for {sif}")
    return frames


def encode_mp4(
    frames_dir: Path,
    mp4: Path,
    fps: int,
    *,
    audio: Path | None = None,
    cfg: StudioConfig | None = None,
) -> Path:
    """Encode frame*.png (sorted by name) to H.264 MP4, optionally muxing an audio track."""
    cfg = cfg or load_config()
    mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(cfg.path("tools", "ffmpeg")),
        "-y",
        "-v",
        "error",
        "-framerate",
        str(fps),
        "-pattern_type",
        "glob",
        "-i",
        str(frames_dir / "frame*.png"),
    ]
    if audio:
        # Pad the audio with silence and stop at the video's end, so the shot keeps its length.
        cmd += ["-i", str(audio), "-af", "apad", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(mp4)]
    run_tool(cmd)
    return mp4
