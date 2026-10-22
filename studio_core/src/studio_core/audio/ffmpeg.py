"""Small, deterministic ffmpeg operations on audio files, shared by voices and the mix.

Loudness follows EBU R128 (`loudnorm`'s measurement). We normalize with a plain **linear gain**
computed from a first measuring pass: no dynamic processing, so a line sounds the same, only
louder or softer, and the result is exactly repeatable.
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from studio_core.config import StudioConfig, load_config


class AudioError(RuntimeError):
    pass


def run(args: list[str], cfg: StudioConfig | None = None) -> str:
    """Run ffmpeg with `args`; returns stderr (where ffmpeg prints measurements)."""
    cfg = cfg or load_config()
    cmd = [str(cfg.path("tools", "ffmpeg")), "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-1500:]}")
    return proc.stderr


@dataclass(frozen=True)
class Loudness:
    integrated_lufs: float  # -inf for silence
    true_peak_db: float
    range_lu: float


def measure(path: Path, cfg: StudioConfig | None = None) -> Loudness:
    err = run(["-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"], cfg)
    data = json.loads(err[err.rindex("{") : err.rindex("}") + 1])

    def num(key: str) -> float:
        value = data[key]
        return -math.inf if value in ("-inf", "inf") else float(value)

    return Loudness(num("input_i"), num("input_tp"), num("input_lra"))


def gain_to(loudness: Loudness, target_lufs: float, peak_ceiling_db: float = -1.5) -> float:
    """dB of gain that brings `loudness` to the target without the true peak passing the ceiling.
    0 for silence (nothing to measure)."""
    if math.isinf(loudness.integrated_lufs):
        return 0.0
    return min(target_lufs - loudness.integrated_lufs, peak_ceiling_db - loudness.true_peak_db)


def duration(path: Path) -> float:
    import wave

    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def trim_filter(keep_start_s: float = 0.08, keep_end_s: float = 0.12) -> str:
    """Remove leading and trailing silence, keeping a little air at each end."""
    one_side = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence={}:detection=peak"
    return ",".join(
        [one_side.format(keep_start_s), "areverse", one_side.format(keep_end_s), "areverse"]
    )


def pitch_filter(semitones: float, sample_rate: int) -> str:
    """Shift pitch *and* formants by `semitones`, keeping the duration: play faster (asetrate),
    resample, then stretch back (atempo). Like a smaller vocal tract: younger-sounding."""
    if semitones == 0:
        return ""
    f = 2 ** (semitones / 12)
    return f"asetrate={sample_rate * f:.3f},aresample={sample_rate},atempo={1 / f:.6f}"
