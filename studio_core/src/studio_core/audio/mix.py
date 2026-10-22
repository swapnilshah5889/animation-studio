"""The shot mix: dialogue + sound effects + music → one 48 kHz stereo track (task 3.6, D-036).

    wav = mix_shot(film_root, shot_spec, out=Path(".../mix.wav"))

Three buses, summed, then brought to the web loudness target:

- **Dialogue:** each line at its `start_s`. Lines arrive normalized (-20 LUFS, `speak`).
- **Sound effects:** each chosen library sound (`sfx[].sound`) at its `start_s`, normalized to
  `sfx_lufs` and scaled by its `volume` (0..1, as amplitude). Very short sounds can't be measured
  as loudness, so they are peak-normalized instead (`sfx_peak_db`).
- **Music:** the cue (`music_cue`, normalized to -20 LUFS by `compose`) scaled by
  `music_volume`, and **ducked under the dialogue**: a volume envelope dips by `duck_db` while
  any line plays, ramping down over `duck_attack_s` before it and back up over `duck_release_s`
  after. We know exactly when lines play, so the envelope is computed, not detected (no
  compressor), and it is the same every time (rules in code).

Finally one linear gain brings the whole mix to `target_lufs`. A limiter running at 4x
oversampling (true peaks fall between samples) catches the few peaks the gain would push past
`peak_db`. The result is measured, and trimmed if a peak still pokes over. The numbers live in
config [mix]; defaults are below.

Every input is first converted by ffmpeg to 48 kHz stereo float. numpy then does the placement,
gains and envelope sample-exactly, which is what the tests measure.
"""

from __future__ import annotations

import math
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from studio_core.audio import ffmpeg
from studio_core.audio.library import load_library
from studio_core.config import StudioConfig, load_config

RATE = 48_000
DEFAULTS = {
    "target_lufs": -14.0,  # finished shot, for the web (EBU R128 broadcast would be -23)
    "peak_db": -1.5,  # true-peak ceiling
    "sfx_lufs": -20.0,  # a sound effect at volume 1.0
    "sfx_peak_db": -6.0,  # ... or, if too short to measure, its peak at volume 1.0
    "duck_db": -10.0,  # music under dialogue
    "duck_attack_s": 0.15,
    "duck_release_s": 0.4,
}


class MixError(ValueError):
    pass


@dataclass(frozen=True)
class Buses:
    dialogue: np.ndarray  # (samples, 2) float32
    sfx: np.ndarray
    music: np.ndarray
    duck: np.ndarray  # (samples,) the music envelope, 1.0 = full level

    def total(self) -> np.ndarray:
        return self.dialogue + self.sfx + self.music


def settings(cfg: StudioConfig | None = None) -> dict[str, float]:
    cfg = cfg or load_config()
    return {**DEFAULTS, **{k: float(v) for k, v in (cfg.data.get("mix") or {}).items()}}


def load_48k_stereo(path: Path, cfg: StudioConfig, work: Path) -> np.ndarray:
    """Any audio file → (samples, 2) float32 at 48 kHz, via ffmpeg (16-bit WAV in between)."""
    out = work / f"{abs(hash(str(path)))}.wav"
    ffmpeg.run(["-i", str(path), "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s16le", str(out)], cfg)
    with wave.open(str(out)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return (data.reshape(-1, 2).astype("float32") / 32768.0).copy()


def place(bus: np.ndarray, clip: np.ndarray, start_s: float, gain: float = 1.0) -> None:
    """Add `clip` into `bus` from `start_s`, cut at the bus end."""
    start = round(start_s * RATE)
    if start >= len(bus):
        return
    n = min(len(clip), len(bus) - start)
    bus[start : start + n] += clip[:n] * gain


def duck_envelope(
    n_samples: int, lines: list[tuple[float, float]], s: dict[str, float]
) -> np.ndarray:
    """Music gain per sample: 1.0, dipping to duck_db while any (start_s, end_s) line plays,
    with linear ramps of duck_attack_s before and duck_release_s after. Lines closer together
    than the two ramps are treated as one span, so the music doesn't swell between them."""
    t = np.arange(n_samples, dtype="float64") / RATE
    depth = np.zeros(n_samples)
    attack, release = s["duck_attack_s"], s["duck_release_s"]
    spans: list[list[float]] = []
    for start, end in sorted(lines):  # a gap too short to recover in is held down
        if spans and start - spans[-1][1] < attack + release:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    for start, end in spans:
        rise = np.clip((t - (start - attack)) / attack, 0, 1)
        fall = np.clip(((end + release) - t) / release, 0, 1)
        depth = np.maximum(depth, np.minimum(rise, fall))
    low = 10 ** (s["duck_db"] / 20)
    return (1 - depth * (1 - low)).astype("float32")


def _sfx_gain(clip: np.ndarray, volume: float, s: dict[str, float], path: Path, cfg) -> float:
    loud = ffmpeg.measure(path, cfg)
    if math.isinf(loud.integrated_lufs) or len(clip) < 0.4 * RATE:
        peak = float(np.max(np.abs(clip))) or 1.0
        base_db = s["sfx_peak_db"] - 20 * math.log10(peak)
    else:
        base_db = s["sfx_lufs"] - loud.integrated_lufs
    return 10 ** (base_db / 20) * volume


def buses(
    film_root: Path, shot: dict[str, Any], cfg: StudioConfig | None = None, work: Path | None = None
) -> Buses:
    """The three buses for a shot spec, before the final loudness gain."""
    cfg = cfg or load_config()
    s = settings(cfg)
    n = round(shot["duration_s"] * RATE)
    with tempfile.TemporaryDirectory() as tmp:
        work = work or Path(tmp)
        dialogue = np.zeros((n, 2), "float32")
        spans = []
        for line in shot.get("dialogue", []):
            wav = film_root / "audio" / "dialogue" / f"{line['line_id']}.wav"
            clip = load_48k_stereo(wav, cfg, work)
            place(dialogue, clip, line["start_s"])
            spans.append((line["start_s"], line["start_s"] + len(clip) / RATE))

        sfx = np.zeros((n, 2), "float32")
        chosen = [e for e in shot.get("sfx", []) if "sound" in e]
        if chosen:
            library = load_library(cfg.path("paths", "sfx_library"))
            for effect in chosen:
                path = library.path(effect["sound"])
                clip = load_48k_stereo(path, cfg, work)
                gain = _sfx_gain(clip, effect.get("volume", 0.5), s, path, cfg)
                place(sfx, clip, effect["start_s"], gain)

        music = np.zeros((n, 2), "float32")
        duck = duck_envelope(n, spans, s)
        if shot.get("music_cue"):
            wav = film_root / "audio" / "music" / f"{shot['music_cue']}.wav"
            place(music, load_48k_stereo(wav, cfg, work), 0.0, shot.get("music_volume", 0.5))
            music *= duck[:, None]
    return Buses(dialogue, sfx, music, duck)


def write_wav(path: Path, samples: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return path


def mix_shot(
    film_root: Path, shot: dict[str, Any], out: Path, cfg: StudioConfig | None = None
) -> Path | None:
    """Mix a shot's audio to `out` (48 kHz stereo WAV at the loudness target).
    None if the shot has no audio at all."""
    cfg = cfg or load_config()
    s = settings(cfg)
    has_sfx = any("sound" in e for e in shot.get("sfx", []))
    if not (shot.get("dialogue") or has_sfx or shot.get("music_cue")):
        return None
    raw = write_wav(out.with_suffix(".raw.wav"), buses(film_root, shot, cfg).total())
    gain = s["target_lufs"] - ffmpeg.measure(raw, cfg).integrated_lufs
    trim = 0.0
    for _ in range(3):  # true peaks sit between samples: limit at 4x, then check and trim
        limit = 10 ** ((s["peak_db"] - trim) / 20)
        ffmpeg.run(
            [
                "-i",
                str(raw),
                "-af",
                f"aresample={4 * RATE},volume={gain - trim:.2f}dB,"
                f"alimiter=limit={limit:.4f}:level=disabled,aresample={RATE}",
                "-c:a",
                "pcm_s16le",
                str(out),
            ],
            cfg,
        )
        over = ffmpeg.measure(out, cfg).true_peak_db - s["peak_db"]
        if over <= 0.05:
            break
        trim += over + 0.1
    raw.unlink()
    return out
