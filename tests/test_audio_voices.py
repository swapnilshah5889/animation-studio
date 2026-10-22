"""Voices (task 3.2): text checks, hashing and ids, ffmpeg postprocessing measured on synthetic
tones, refusals, and one real Kokoro run (marked `models`)."""

import json
import math
import shutil
import struct
import wave
from itertools import pairwise
from pathlib import Path

import pytest

from studio_core.audio import ffmpeg
from studio_core.audio.voices import (
    MODEL,
    VoiceError,
    check_text,
    line_hash,
    load_voice,
    next_line_id,
    speak,
)
from studio_core.config import expand_path, load_config
from studio_core.schema import validate

FIXTURES = Path(__file__).parent / "fixtures"
VOICE = json.loads((FIXTURES / "schemas" / "voice_pip.json").read_text())
has_kokoro = expand_path(load_config().get("envs", "kokoro")["python"]).exists()


def film_with_voice(root: Path, voice: dict | None = None) -> Path:
    (root / "characters" / "pip").mkdir(parents=True)
    (root / "characters" / "pip" / "voice.json").write_text(json.dumps(voice or VOICE))
    return root


def tone(path: Path, *, hz: float = 440, seconds: float = 1.0, pad_s: float = 0.0) -> Path:
    """A sine tone with optional silence before and after, as 24 kHz mono 16-bit WAV."""
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={hz}:duration={seconds}:sample_rate=24000",
            "-af",
            f"adelay={int(pad_s * 1000)},apad=pad_dur={pad_s},volume=0.3",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
    )
    return path


def frequency(path: Path) -> float:
    """Dominant frequency from upward zero crossings (fine for a pure tone)."""
    with wave.open(str(path)) as w:
        rate, n = w.getframerate(), w.getnframes()
        samples = struct.unpack(f"<{n}h", w.readframes(n))
    crossings = sum(1 for a, b in pairwise(samples) if a < 0 <= b)
    return crossings / (n / rate)


# --------------------------------------------------------------------------- text, hash, ids


def test_check_text() -> None:
    assert check_text("Hi Bunny! Look \u2014 it\u2019s a kite\u2026") == []
    assert check_text("  ") == ["the text is blank"]
    assert "web or email" in check_text("See www.example.com")[0]
    assert "'<'" in check_text("I <3 kites")[0]
    assert "['hell']" in check_text("What the hell")[0]
    assert check_text("Hello, shell!") == []  # whole words only
    assert "at most 300" in check_text("la " * 120)[0]


def test_line_hash() -> None:
    base = line_hash("Hi!", VOICE, MODEL)
    assert base == line_hash("Hi!", {**VOICE, "notes": "changed notes"}, MODEL)  # notes ignored
    assert base != line_hash("Hi?", VOICE, MODEL)
    assert base != line_hash("Hi!", {**VOICE, "speed": 1.1}, MODEL)
    assert base != line_hash("Hi!", VOICE, "another model")


def test_next_line_id(tmp_path: Path) -> None:
    assert next_line_id(tmp_path) == "l001"
    folder = tmp_path / "audio" / "dialogue"
    folder.mkdir(parents=True)
    (folder / "l001.wav").write_bytes(b"")  # a fixture-style line without metadata
    (folder / "l007.json").write_text("{}")
    assert next_line_id(tmp_path) == "l008"
    assert next_line_id(tmp_path, {"l008", "l010"}) == "l011"


def test_load_voice_errors(tmp_path: Path) -> None:
    with pytest.raises(VoiceError, match="has no voice yet"):
        load_voice(tmp_path, "pip")
    film = film_with_voice(tmp_path, {**VOICE, "speed": 3})
    with pytest.raises(VoiceError, match="speed"):
        load_voice(film, "pip")
    (film / "characters" / "pip" / "voice.json").write_text(
        json.dumps({**VOICE, "character": "kit"})
    )
    with pytest.raises(VoiceError, match="is the voice of 'kit', not 'pip'"):
        load_voice(film, "pip")


def test_refusals_happen_before_any_synthesis(tmp_path: Path) -> None:
    film = film_with_voice(tmp_path)
    with pytest.raises(VoiceError, match=r"line 1 \(new\): the text uses \['damn'\]"):
        speak(film, "pip", [{"text": "Hello!"}, {"text": "Oh damn."}])
    with pytest.raises(VoiceError, match="'7' is not a line id"):
        speak(film, "pip", [{"line_id": "7", "text": "Hello!"}])
    with pytest.raises(VoiceError, match="l002 appears twice"):
        speak(film, "pip", [{"line_id": "l002", "text": "A"}, {"line_id": "l002", "text": "B"}])
    folder = film / "audio" / "dialogue"
    folder.mkdir(parents=True)
    meta = json.loads((FIXTURES / "schemas" / "line_l001.json").read_text())
    (folder / "l001.json").write_text(json.dumps({**meta, "character": "bunny"}))
    with pytest.raises(VoiceError, match="line l001 belongs to bunny"):
        speak(film, "pip", [{"line_id": "l001", "text": "Mine now"}])
    assert not (folder / "l001.wav").exists()
    film_with_voice(tmp_path / "other", {**VOICE, "engine": "chatterbox"})
    with pytest.raises(VoiceError, match="chatterbox isn't installed"):
        speak(tmp_path / "other", "pip", [{"text": "Hello!"}])


# --------------------------------------------------------------------------- ffmpeg steps


def test_pitch_step_raises_pitch_and_keeps_length(tmp_path: Path) -> None:
    src = tone(tmp_path / "a.wav")
    out = tmp_path / "b.wav"
    ffmpeg.run(["-i", str(src), "-af", ffmpeg.pitch_filter(2, 24000), str(out)])
    assert frequency(out) == pytest.approx(440 * 2 ** (2 / 12), rel=0.02)
    assert ffmpeg.duration(out) == pytest.approx(1.0, abs=0.03)
    assert ffmpeg.pitch_filter(0, 24000) == ""


def test_trim_keeps_a_little_air(tmp_path: Path) -> None:
    src = tone(tmp_path / "a.wav", pad_s=1.0)  # 1 s silence + 1 s tone + 1 s silence
    out = tmp_path / "b.wav"
    ffmpeg.run(["-i", str(src), "-af", ffmpeg.trim_filter(), str(out)])
    assert ffmpeg.duration(src) == pytest.approx(3.0, abs=0.01)
    assert ffmpeg.duration(out) == pytest.approx(1.0 + 0.08 + 0.12, abs=0.03)


def test_linear_gain_reaches_the_target(tmp_path: Path) -> None:
    src = tone(tmp_path / "a.wav", seconds=2)
    gain = ffmpeg.gain_to(ffmpeg.measure(src), -23.0)
    out = tmp_path / "b.wav"
    ffmpeg.run(["-i", str(src), "-af", f"volume={gain:.2f}dB", str(out)])
    assert ffmpeg.measure(out).integrated_lufs == pytest.approx(-23.0, abs=0.3)
    loud = ffmpeg.measure(src)
    assert ffmpeg.gain_to(loud, 0.0) == pytest.approx(-1.5 - loud.true_peak_db)  # peak-limited
    assert ffmpeg.gain_to(ffmpeg.Loudness(-math.inf, -math.inf, 0), -20) == 0.0


# --------------------------------------------------------------------------- with Kokoro


@pytest.mark.models
@pytest.mark.skipif(not has_kokoro, reason="no Kokoro env")
def test_speak_writes_lines_caches_and_regenerates(tmp_path: Path) -> None:
    film = film_with_voice(tmp_path)
    first = speak(film, "pip", [{"text": "Hi Bunny! Look what I found."}, {"text": "Wow!"}])
    assert [(r.line_id, r.take, r.cached) for r in first] == [
        ("l001", 1, False),
        ("l002", 1, False),
    ]
    for r in first:
        meta = json.loads(r.wav.with_suffix(".json").read_text())
        assert validate("line", meta) == []
        assert meta["duration_s"] == pytest.approx(r.duration_s, abs=0.001)
        assert r.wav.with_suffix(".txt").read_text().strip() == r.text
        assert ffmpeg.measure(r.wav).integrated_lufs == pytest.approx(
            VOICE["loudness_lufs"], abs=0.5
        )

    again = speak(film, "pip", [{"text": "Hi  Bunny!  Look what I found."}])  # spacing differs
    assert [(r.line_id, r.cached) for r in again] == [("l001", True)]

    cues = film / "audio" / "lipsync" / "l002.json"
    cues.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "audio" / "pip_line_01.rhubarb.json", cues)
    redo = speak(film, "pip", [{"line_id": "l002", "text": "Wow!"}], regenerate=True)
    assert [(r.line_id, r.take, r.cached) for r in redo] == [("l002", 2, False)]
    assert not cues.exists()  # stale cues of the old take are gone
