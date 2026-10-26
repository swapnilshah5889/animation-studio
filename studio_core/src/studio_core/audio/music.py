"""Music: intent → a music cue (task 3.4, D-036).

    cue = compose(film_root, "m01", mood="playful", duration_s=10, energy=0.6)

The director asks for a **mood**, an **energy** (0 = gentle, 1 = lively) and optionally a few
**instruments**. Code turns that into the model's caption and tempo from the tables below, so the
LLM never writes model-specific prompts and every caption is child-appropriate and instrumental
(rules in code).

Steps:
1. Validate the request against `MOODS` and `INSTRUMENTS`; pick a seed from the cue id unless
   one is given (the same request always makes the same music).
2. **Cache:** the request hash covers mood, energy, instruments, duration, seed and model. Same
   hash = the existing cue is reused.
3. **Make room:** unload every Ollama model, and refuse if ComfyUI is running (one large model
   in memory at a time, AGENTS.md). ACE-Step then runs in its own env (scripts/audio/
   acestep_compose.py) in bf16 with PyTorch's DiT and VAE only (D-041), under
   `/usr/bin/time -l`, so the peak memory footprint of every cue is measured and reported.
4. **Finish:** trim to the exact length with a short fade-in and a fade-out, normalize to
   `MUSIC_LUFS` with a linear gain (so `music_volume` means the same for every cue), write
   audio/music/<cue>.wav (48 kHz stereo) and .json (schemas/music.schema.json).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio_core.audio import ffmpeg
from studio_core.config import REPO_ROOT, StudioConfig, expand_path, load_config
from studio_core.ollama import Ollama
from studio_core.schema import validate

WORKER = REPO_ROOT / "scripts" / "audio" / "acestep_compose.py"
MODEL = "ace-step-1.5 turbo"
PRECISION = "bf16"  # measured in task 3.4: see DECISIONS D-041
SAMPLE_RATE = 48_000
MUSIC_LUFS = -20.0  # every cue is normalized here before mixing
BUDGET_GB = 14.0  # peak footprint (D-036)
MIN_GEN_S = 10.0  # shorter cues are generated at this length, then trimmed
MAX_S = 60.0  # a shot is at most 60 s
FADE_IN_S, FADE_OUT_S = 0.05, 1.5
BASE = "instrumental background music for a children's animated cartoon"

# mood → words for the caption, default instruments, tempo range (bpm at energy 0 and 1), key
MOODS: dict[str, dict[str, Any]] = {
    "playful": {
        "words": "playful, bouncy and cheerful",
        "instruments": ["ukulele", "glockenspiel", "hand claps"],
        "bpm": (96, 128),
        "key": "major",
    },
    "calm": {
        "words": "calm, warm and gentle",
        "instruments": ["acoustic guitar", "soft piano", "flute"],
        "bpm": (66, 84),
        "key": "major",
    },
    "curious": {
        "words": "curious and light, tiptoeing",
        "instruments": ["pizzicato strings", "marimba", "clarinet"],
        "bpm": (84, 108),
        "key": "major",
    },
    "adventurous": {
        "words": "adventurous and brave, a sense of discovery",
        "instruments": ["strings", "french horn", "soft drums"],
        "bpm": (100, 132),
        "key": "major",
    },
    "silly": {
        "words": "silly, comic and bouncy",
        "instruments": ["bassoon", "tuba", "xylophone", "slide whistle"],
        "bpm": (100, 136),
        "key": "major",
    },
    "sleepy": {
        "words": "sleepy lullaby, soft and slow",
        "instruments": ["music box", "harp", "celesta"],
        "bpm": (56, 72),
        "key": "major",
    },
    "sad": {
        "words": "gently sad and tender, never scary",
        "instruments": ["soft piano", "cello"],
        "bpm": (60, 78),
        "key": "minor",
    },
    "mysterious": {
        "words": "softly mysterious and wondering, never scary",
        "instruments": ["celesta", "harp", "pizzicato strings"],
        "bpm": (70, 92),
        "key": "minor",
    },
    "triumphant": {
        "words": "triumphant and joyful, a happy ending",
        "instruments": ["brass", "strings", "timpani", "bells"],
        "bpm": (104, 128),
        "key": "major",
    },
}
INSTRUMENTS = sorted(
    {i for m in MOODS.values() for i in m["instruments"]}
    | {"piano", "acoustic guitar", "kalimba", "recorder", "accordion", "banjo", "bells", "strings"}
)


class MusicError(ValueError):
    """A compose request was refused or the model failed. The message says what to fix."""


@dataclass(frozen=True)
class MusicCue:
    cue_id: str
    wav: Path
    duration_s: float
    caption: str
    seed: int
    cached: bool
    peak_gb: float | None  # measured peak footprint of the model process (None when cached)


def plan(
    cue_id: str,
    mood: str,
    duration_s: float,
    energy: float = 0.5,
    instruments: list[str] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """The model request for an intent, checked. Pure: no files, no model."""
    if mood not in MOODS:
        raise MusicError(f"unknown mood {mood!r}; moods: {', '.join(MOODS)}")
    if not 0 <= energy <= 1:
        raise MusicError(f"energy must be between 0 and 1, not {energy}")
    if not 0 < duration_s <= MAX_S:
        raise MusicError(f"duration must be more than 0 and at most {MAX_S:g} s, not {duration_s}")
    chosen = list(dict.fromkeys(instruments)) if instruments else MOODS[mood]["instruments"]
    unknown = sorted(set(chosen) - set(INSTRUMENTS))
    if unknown:
        raise MusicError(f"unknown instruments {unknown}; instruments: {', '.join(INSTRUMENTS)}")
    if len(chosen) > 6:
        raise MusicError("at most 6 instruments")
    m = MOODS[mood]
    lo, hi = m["bpm"]
    bpm = round(lo + (hi - lo) * energy)
    pace = "very gentle" if energy < 0.25 else "lively" if energy > 0.75 else "moderate"
    caption = f"{BASE}, {m['words']}, {', '.join(chosen)}, {pace} pace, {m['key']} key, no vocals"
    if seed is None:
        seed = int(hashlib.sha256(f"{cue_id}:{mood}".encode()).hexdigest()[:8], 16)
    request = {
        "mood": mood,
        "energy": round(energy, 3),
        "instruments": chosen,
        "duration_s": duration_s,
        "seed": seed,
        "model": MODEL,
        "precision": PRECISION,
    }
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    return {**request, "caption": caption, "bpm": bpm, "hash": digest}


def make_room(cfg: StudioConfig) -> list[str]:
    """Unload Ollama models; refuse if ComfyUI is up. Returns the models that were unloaded."""
    comfy = cfg.get("services", "comfyui_url")
    try:
        urllib.request.urlopen(comfy, timeout=1)
        raise MusicError(
            "ComfyUI is running and holds GPU memory; stop it before composing "
            "(one large model at a time)"
        )
    except OSError:
        pass  # not running: good
    client = Ollama(cfg.get("services", "ollama_url"))
    try:
        names = [m["name"] for m in client.loaded()]
    except OSError:
        return []  # Ollama not running: nothing to unload
    for name in names:
        client.unload(name)
    return names


def run_worker(request: dict[str, Any], out_dir: Path, cfg: StudioConfig) -> tuple[Path, float]:
    """Generate with ACE-Step; returns (wav, peak footprint GB)."""
    python = expand_path(cfg.get("envs", "ace_step")["python"])
    cmd = [
        "/usr/bin/time",
        "-l",
        str(python),
        str(WORKER),
        "--out-dir",
        str(out_dir),
        "--duration",
        str(max(request["duration_s"], MIN_GEN_S)),
        "--caption",
        request["caption"],
        "--bpm",
        str(request["bpm"]),
        "--seed",
        str(request["seed"]),
        "--precision",
        PRECISION,
        "--no-mlx-dit",  # the MLX DiT keeps a second copy of the weights
        "--no-mlx-vae",  # so does the MLX VAE: ~8 GB of the old 21 GB peak (D-041)
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    peak = next(
        (
            int(line.split()[0]) / 1024**3
            for line in proc.stderr.splitlines()
            if "peak memory" in line
        ),
        0.0,
    )
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        raise MusicError(f"ACE-Step failed: {proc.stderr[-1500:]}") from None
    if proc.returncode != 0 or "error" in result:
        raise MusicError(f"ACE-Step failed: {result.get('error') or proc.stderr[-1500:]}")
    return Path(result["files"][0]), peak


def finish(raw: Path, out: Path, duration_s: float, cfg: StudioConfig) -> None:
    """Exact length, fades, 48 kHz stereo, normalized to MUSIC_LUFS (linear gain)."""
    shaped = out.with_suffix(".shaped.wav")
    fade_out = min(FADE_OUT_S, duration_s / 3)
    chain = (
        f"atrim=0:{duration_s},afade=t=in:d={FADE_IN_S},"
        f"afade=t=out:st={duration_s - fade_out:.3f}:d={fade_out:.3f}"
    )
    ffmpeg.run(
        ["-i", str(raw), "-af", chain, "-ar", str(SAMPLE_RATE), "-ac", "2", str(shaped)], cfg
    )
    gain = ffmpeg.gain_to(ffmpeg.measure(shaped, cfg), MUSIC_LUFS)
    ffmpeg.run(
        ["-i", str(shaped), "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(out)], cfg
    )
    shaped.unlink()


def compose(
    film_root: Path,
    cue_id: str,
    mood: str,
    duration_s: float,
    *,
    energy: float = 0.5,
    instruments: list[str] | None = None,
    seed: int | None = None,
    regenerate: bool = False,
    cfg: StudioConfig | None = None,
) -> MusicCue:
    """Compose (or reuse) audio/music/<cue_id>.wav. See the module docstring."""
    cfg = cfg or load_config()
    request = plan(cue_id, mood, duration_s, energy, instruments, seed)
    folder = film_root / "audio" / "music"
    wav, meta_file = folder / f"{cue_id}.wav", folder / f"{cue_id}.json"
    if not regenerate and wav.is_file() and meta_file.is_file():
        old = json.loads(meta_file.read_text())
        if old.get("hash") == request["hash"]:
            return MusicCue(
                cue_id, wav, ffmpeg.duration(wav), old["caption"], old["seed"], True, None
            )

    make_room(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder, prefix=".compose-") as work:
        raw, peak = run_worker(request, Path(work), cfg)
        finish(raw, wav, duration_s, cfg)
    meta = {
        "schema_version": 1,
        "cue_id": cue_id,
        "mood": mood,
        "energy": request["energy"],
        "instruments": request["instruments"],
        "duration_s": duration_s,
        "caption": request["caption"],
        "model": f"{MODEL} ({PRECISION})",
        "seed": request["seed"],
        "sample_rate": SAMPLE_RATE,
        "channels": 2,
        "looped": False,
        "hash": request["hash"],
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    issues = validate("music", meta)
    if issues:
        raise RuntimeError(f"music metadata is invalid: {issues}")
    meta_file.write_text(json.dumps(meta, indent=2) + "\n")
    return MusicCue(
        cue_id, wav, ffmpeg.duration(wav), request["caption"], request["seed"], False, peak
    )
