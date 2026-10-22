"""Music (task 3.4): request planning, refusals, the memory guard, finishing, and one real
ACE-Step run (marked `models`) that must stay within the memory budget."""

import json
from pathlib import Path

import pytest

from studio_core.audio import ffmpeg, music
from studio_core.audio.music import BUDGET_GB, MOODS, MusicError, compose, finish, plan
from studio_core.config import expand_path, load_config
from studio_core.schema import validate

CFG = load_config()
has_ace = expand_path(CFG.get("envs", "ace_step")["python"]).exists()


def test_plan_builds_a_child_safe_instrumental_caption() -> None:
    p = plan("m01", "playful", 10, energy=1.0)
    assert p["caption"].startswith(music.BASE) and p["caption"].endswith("no vocals")
    assert "playful, bouncy and cheerful" in p["caption"] and "lively pace" in p["caption"]
    assert p["instruments"] == MOODS["playful"]["instruments"]
    assert p["bpm"] == MOODS["playful"]["bpm"][1]
    assert plan("m01", "playful", 10, energy=0.0)["bpm"] == MOODS["playful"]["bpm"][0]
    assert "minor key" in plan("m01", "sad", 10)["caption"]


def test_plan_is_deterministic_and_hashes_the_request() -> None:
    a, b = plan("m01", "calm", 10), plan("m01", "calm", 10)
    assert a == b  # same cue id + mood → same seed → same request
    assert plan("m02", "calm", 10)["seed"] != a["seed"]
    assert plan("m01", "calm", 10, seed=7)["seed"] == 7
    for other in (
        plan("m01", "calm", 12),
        plan("m01", "calm", 10, energy=0.9),
        plan("m01", "calm", 10, instruments=["harp"]),
    ):
        assert other["hash"] != a["hash"]


def test_plan_refusals() -> None:
    with pytest.raises(MusicError, match="unknown mood 'spooky'; moods: playful"):
        plan("m01", "spooky", 10)
    with pytest.raises(MusicError, match="energy must be between 0 and 1"):
        plan("m01", "calm", 10, energy=2)
    with pytest.raises(MusicError, match="at most 60 s"):
        plan("m01", "calm", 90)
    with pytest.raises(MusicError, match=r"unknown instruments \['electric guitar'\]"):
        plan("m01", "calm", 10, instruments=["harp", "electric guitar"])
    assert plan("m01", "calm", 10, instruments=["harp", "harp"])["instruments"] == ["harp"]


def test_make_room_refuses_while_comfyui_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(music.urllib.request, "urlopen", lambda *a, **k: object())
    with pytest.raises(MusicError, match="ComfyUI is running"):
        music.make_room(CFG)


def test_finish_trims_fades_and_normalizes(tmp_path: Path) -> None:
    raw = tmp_path / "raw.wav"
    ffmpeg.run(
        ["-f", "lavfi", "-i", "sine=frequency=330:duration=12:sample_rate=44100", str(raw)], CFG
    )
    out = tmp_path / "cue.wav"
    finish(raw, out, 7.5, CFG)
    assert ffmpeg.duration(out) == pytest.approx(7.5, abs=0.01)
    assert ffmpeg.measure(out).integrated_lufs == pytest.approx(music.MUSIC_LUFS, abs=0.5)
    tail = tmp_path / "tail.wav"
    ffmpeg.run(["-sseof", "-0.2", "-i", str(out), str(tail)], CFG)
    assert ffmpeg.measure(tail).true_peak_db < ffmpeg.measure(out).true_peak_db - 12  # faded out
    import wave

    with wave.open(str(out)) as w:
        assert (w.getframerate(), w.getnchannels()) == (48000, 2)


@pytest.mark.models
@pytest.mark.skipif(not has_ace, reason="no ACE-Step env")
def test_compose_within_the_memory_budget(tmp_path: Path) -> None:
    cue = compose(tmp_path, "m01", "playful", 10, energy=0.6)
    assert not cue.cached and cue.peak_gb is not None
    assert cue.peak_gb <= BUDGET_GB, f"peak footprint {cue.peak_gb:.1f} GB"
    assert cue.duration_s == pytest.approx(10, abs=0.01)
    assert ffmpeg.measure(cue.wav).integrated_lufs == pytest.approx(music.MUSIC_LUFS, abs=0.5)
    meta = json.loads(cue.wav.with_suffix(".json").read_text())
    assert validate("music", meta) == [] and meta["caption"] == cue.caption
    again = compose(tmp_path, "m01", "playful", 10, energy=0.6)
    assert again.cached and again.wav == cue.wav
