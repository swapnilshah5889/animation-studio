"""The shot mix (task 3.6): the ducking envelope, placement, and a full mix of synthetic signals
measured for ducking depth, sound-effect timing and loudness."""

import hashlib
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from studio_core.audio import ffmpeg
from studio_core.audio.mix import DEFAULTS, RATE, buses, duck_envelope, mix_shot, place
from studio_core.config import StudioConfig, load_config

CFG = load_config()


def write(path: Path, samples: np.ndarray, rate: int, channels: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def tone(hz: float, seconds: float, rate: int, amp: float = 0.3) -> np.ndarray:
    t = np.arange(round(seconds * rate)) / rate
    return amp * np.sin(2 * np.pi * hz * t)


def rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(x.astype("float64") ** 2)) + 1e-12)


def test_duck_envelope() -> None:
    env = duck_envelope(6 * RATE, [(2.0, 3.0)], DEFAULTS)
    low = 10 ** (DEFAULTS["duck_db"] / 20)
    at = lambda s: float(env[round(s * RATE)])  # noqa: E731
    assert at(1.0) == 1.0 and at(4.0) == 1.0  # before attack, after release
    assert at(2.5) == pytest.approx(low, abs=1e-6)  # during the line
    assert at(2.0 - DEFAULTS["duck_attack_s"] / 2) == pytest.approx((1 + low) / 2, abs=0.01)
    assert at(3.0 + DEFAULTS["duck_release_s"] / 2) == pytest.approx((1 + low) / 2, abs=0.01)
    both = duck_envelope(6 * RATE, [(1.0, 1.5), (1.6, 2.0)], DEFAULTS)
    assert float(both[round(1.55 * RATE)]) == pytest.approx(low, abs=1e-6)  # gap shorter than ramps


def test_place_is_sample_exact_and_cut_at_the_end() -> None:
    bus = np.zeros((RATE, 2), "float32")
    place(bus, np.ones((RATE // 2, 2), "float32"), 0.75, gain=0.5)
    nonzero = np.flatnonzero(bus[:, 0])
    assert nonzero[0] == round(0.75 * RATE) and nonzero[-1] == RATE - 1
    assert bus[-1, 0] == 0.5


@pytest.fixture
def film(tmp_path: Path) -> tuple[Path, StudioConfig, dict]:
    root = tmp_path / "film"
    line = tone(1000, 1.0, 24000)  # a "line" at 24 kHz mono, like speak's output
    write(root / "audio" / "dialogue" / "l001.wav", line, 24000, 1)
    music = np.repeat(tone(220, 6.0, 48000, 0.2)[:, None], 2, axis=1)
    write(root / "audio" / "music" / "m01.wav", music.reshape(-1), 48000, 2)
    click = np.zeros(int(0.5 * 48000))
    click[0:48] = 0.8  # a 1 ms click at the very start of the file
    lib = tmp_path / "sfx"
    path = write(lib / "test" / "click.wav", click, 48000, 1)
    manifest = {
        "schema_version": 1,
        "sounds": [
            {
                "id": "test_click",
                "file": "test/click.wav",
                "source": "test",
                "license": "CC0-1.0",
                "url": "https://example.org/click",
                "duration_s": 0.5,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        ],
    }
    (lib / "manifest.json").write_text(json.dumps(manifest))
    cfg = StudioConfig(
        {**CFG.data, "paths": {**CFG.data["paths"], "sfx_library": str(lib)}}, CFG.source
    )
    shot = {
        "duration_s": 6,
        "dialogue": [{"character": "pip", "line_id": "l001", "text": "Hi", "start_s": 2.0}],
        "sfx": [{"query": "a click", "sound": "test_click", "start_s": 4.0, "volume": 1.0}],
        "music_cue": "m01",
        "music_volume": 0.5,
    }
    return root, cfg, shot


def test_buses_duck_the_music_and_place_the_sound(film) -> None:
    root, cfg, shot = film
    b = buses(root, shot, cfg)
    assert b.dialogue.shape == b.music.shape == (6 * RATE, 2)
    before = rms_db(b.music[round(0.5 * RATE) : round(1.5 * RATE)])
    during = rms_db(b.music[round(2.3 * RATE) : round(2.8 * RATE)])
    assert during - before == pytest.approx(DEFAULTS["duck_db"], abs=0.5)
    onset = np.flatnonzero(np.abs(b.sfx[:, 0]) > 0.01)[0] / RATE
    assert onset == pytest.approx(4.0, abs=0.010)
    assert np.abs(b.dialogue[: round(1.9 * RATE)]).max() < 1e-4  # silent before the line


def test_mix_reaches_the_loudness_target(film, tmp_path: Path) -> None:
    root, cfg, shot = film
    out = mix_shot(root, shot, tmp_path / "mix.wav", cfg)
    loud = ffmpeg.measure(out, cfg)
    assert loud.integrated_lufs == pytest.approx(DEFAULTS["target_lufs"], abs=1.0)
    assert loud.true_peak_db <= -1.0
    assert ffmpeg.duration(out) == pytest.approx(6.0, abs=0.01)
    assert mix_shot(root, {"duration_s": 2}, tmp_path / "none.wav", cfg) is None
