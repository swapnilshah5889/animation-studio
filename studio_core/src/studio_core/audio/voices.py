"""Voices: text → a finished dialogue line in a character's voice (task 3.2, D-036).

    results = speak(film_root, "pip", [{"text": "Hi Bunny!"}, {"line_id": "l007", "text": "..."}])

For each line:

1. **Check the text** for a children's film (`check_text`): length, characters, a small
   blocklist (config/safety_blocklist.txt). Problems refuse the whole batch.
2. **Cache:** the line's hash covers the text, the voice settings and the model. Same hash =
   the existing take is reused, no synthesis. `regenerate=True` forces a new take.
3. **Synthesize** every uncached line in one call to the Kokoro worker
   (scripts/audio/kokoro_batch.py in envs/kokoro, D-016), so the model loads once.
4. **Post-process** with ffmpeg: trim silence at both ends, apply the voice's pitch step,
   normalize to the voice's speech loudness with a linear gain (true peak ≤ -1.5 dBTP).
5. **Write** audio/dialogue/<line_id>.wav, .txt and .json (schemas/line.schema.json). Stale
   mouth cues for a replaced line are removed.
6. **Lip-sync** (unless `cues=False`): Rhubarb mouth cues for every line of the request
   (studio_core.audio.lipsync; cached lines with valid cues are not redone), so a spoken line is
   always ready for the mouth.

`synthesize` is the same pipeline without a film folder, for previews (voice casting).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio_core.audio import ffmpeg
from studio_core.audio.lipsync import lipsync
from studio_core.config import REPO_ROOT, StudioConfig, expand_path, load_config
from studio_core.schema import validate

SAMPLE_RATE = 24_000
PEAK_CEILING_DB = -1.5
WORKER = REPO_ROOT / "scripts" / "audio" / "kokoro_batch.py"  # workers live next to each other
BLOCKLIST = REPO_ROOT / "config" / "safety_blocklist.txt"
LINE_ID = re.compile(r"^l([0-9]{3,})$")
# Letters (any script), digits, spaces and the punctuation speech uses.
ALLOWED = re.compile(r"[^\W_]|[\s.,!?;:'\"()\-\u2018\u2019\u201c\u201d\u2013\u2014\u2026]")


class VoiceError(ValueError):
    """A speak request was refused. The message says what to fix."""


@dataclass(frozen=True)
class SpokenLine:
    line_id: str
    wav: Path
    text: str
    duration_s: float
    take: int
    cached: bool
    cues: Path | None = None  # audio/lipsync/<line_id>.json, unless speak(cues=False)


# --------------------------------------------------------------------------- text and ids


def _blocklist() -> set[str]:
    words = BLOCKLIST.read_text().splitlines() if BLOCKLIST.is_file() else []
    return {w.strip().lower() for w in words if w.strip() and not w.startswith("#")}


def _speakable(c: str) -> bool:
    """Letters, digits, spaces, speech punctuation, plus the combining marks of scripts like
    Devanagari (vowel signs, virama) and its danda punctuation."""
    return bool(ALLOWED.match(c)) or unicodedata.category(c).startswith("M") or c in "\u0964\u0965"


def check_text(text: str) -> list[str]:
    """Why a line can't be spoken in a children's film ([] = fine)."""
    problems = []
    if not text.strip():
        return ["the text is blank"]
    if len(text) > 300:
        problems.append(f"the text is {len(text)} characters; split it into lines of at most 300")
    if re.search(r"https?://|www\.|@\w+\.\w", text):
        problems.append("the text contains a web or email address")
    odd = sorted({c for c in text if not _speakable(c)})
    if odd:
        problems.append(f"the text contains characters that can't be spoken: {''.join(odd)!r}")
    blocked = sorted({w for w in re.findall(r"[a-z']+", text.lower()) if w in _blocklist()})
    if blocked:
        problems.append(f"the text uses {blocked}, not for a children's film; rephrase it")
    return problems


def line_hash(text: str, voice: dict[str, Any], model: str) -> str:
    settings = {k: v for k, v in voice.items() if k != "notes"}
    payload = json.dumps({"text": text, "voice": settings, "model": model}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _dialogue_dir(film_root: Path) -> Path:
    return film_root / "audio" / "dialogue"


def existing_lines(film_root: Path) -> dict[str, dict[str, Any]]:
    """line_id → metadata, for lines made by speak (fixture lines without metadata are skipped)."""
    folder = _dialogue_dir(film_root)
    return {
        p.stem: json.loads(p.read_text())
        for p in sorted(folder.glob("l*.json"))
        if LINE_ID.match(p.stem)
    }


def next_line_id(film_root: Path, taken: set[str] = frozenset()) -> str:
    """The next free lNNN after every line in the film (with or without metadata)."""
    numbers = [
        int(m.group(1))
        for p in _dialogue_dir(film_root).glob("l*.*")
        if (m := LINE_ID.match(p.stem))
    ]
    numbers += [int(m.group(1)) for t in taken if (m := LINE_ID.match(t))]
    return f"l{max(numbers, default=0) + 1:03d}"


# --------------------------------------------------------------------------- voices


def load_voice(film_root: Path, character_id: str) -> dict[str, Any]:
    path = film_root / "characters" / character_id / "voice.json"
    if not path.is_file():
        raise VoiceError(f"{character_id!r} has no voice yet ({path}); cast one with set_voice")
    voice = json.loads(path.read_text())
    issues = validate("voice", voice)
    if issues:
        raise VoiceError(f"{path}: " + "; ".join(map(str, issues)))
    if voice["character"] != character_id:
        raise VoiceError(f"{path} is the voice of {voice['character']!r}, not {character_id!r}")
    return voice


def _defaults(voice: dict[str, Any]) -> dict[str, Any]:
    return {
        "speed": 1.0,
        "pitch_semitones": 0.0,
        "loudness_lufs": -20.0,
        "pitch": "moderate",
        "expressiveness": 0.5,
        **voice,
    }


# --------------------------------------------------------------------------- installed voices

KOKORO_VOICES = Path.home() / "ai-studio" / "models" / "kokoro-82m" / "voices"
PARLER_WEIGHTS = Path.home() / "ai-studio" / "models" / "indic-parler-tts" / "model.safetensors"
# Indic Parler-TTS named speakers (model card, D-042); usable once its weights are downloaded.
PARLER_SPEAKERS = {
    "en-in": [
        "Thoma", "Mary", "Swapna", "Dinesh", "Meera", "Jatin", "Aakash", "Sneha", "Kabir",
        "Tisha", "Chingkhei", "Thoiba", "Priya", "Tarun", "Gauri", "Nisha", "Raghav", "Kavya",
        "Ravi", "Vikas", "Riya",
    ],
    "hi": ["Rohit", "Divya", "Aman", "Rani"],
}  # fmt: skip


def available() -> dict[str, list[str]]:
    """Voices that can be used right now, per engine."""
    kokoro = sorted(p.stem for p in KOKORO_VOICES.glob("*.pt")) if KOKORO_VOICES.is_dir() else []
    parler = [f"{lang}:{name}" for lang, names in PARLER_SPEAKERS.items() for name in names]
    return {"kokoro": kokoro, "parler": parler if PARLER_WEIGHTS.is_file() else []}


def save_voice(film_root: Path, character_id: str, settings: dict[str, Any]) -> Path:
    """Validate and write characters/<id>/voice.json. The voices it names must be installed."""
    folder = film_root / "characters" / character_id
    if not (folder / "rig.json").is_file():
        known = sorted(p.parent.name for p in (film_root / "characters").glob("*/rig.json"))
        raise VoiceError(f"no character {character_id!r}; characters: {', '.join(known) or 'none'}")
    voice = {"schema_version": 1, "character": character_id, **settings}
    issues = validate("voice", voice)
    if issues:
        raise VoiceError("; ".join(map(str, issues)))
    installed = available()
    if voice["engine"] == "kokoro":
        unknown = sorted({v["id"] for v in voice["voices"]} - set(installed["kokoro"]))
        if unknown:
            raise VoiceError(
                f"voices {unknown} aren't installed; "
                f"kokoro voices: {', '.join(installed['kokoro'])}"
            )
    elif voice["engine"] == "parler":
        if not installed["parler"]:
            raise VoiceError(
                "Parler (Indian voices) isn't downloaded yet; the owner deferred it (task 3.2b)"
            )
        names = PARLER_SPEAKERS.get(voice["language"], [])
        if voice["speaker"] not in names:
            raise VoiceError(
                f"{voice['speaker']!r} isn't a {voice['language']} speaker; speakers: {names}"
            )
    else:
        model_of(voice)  # refuses engines that aren't installed
    path = folder / "voice.json"
    path.write_text(json.dumps(voice, indent=2) + "\n")
    return path


# --------------------------------------------------------------------------- engines

# What each worker reports as its model; part of every line's hash, so a model change re-voices.
ENGINES = {
    "kokoro": {
        "env": "kokoro",
        "worker": "kokoro_batch.py",
        "model": "kokoro-82m v1.0 (kokoro 0.9.4)",
    },
    "parler": {
        "env": "parler",
        "worker": "parler_batch.py",
        "model": "indic-parler-tts (parler-tts d108732)",
    },
}
KOKORO_LANG = {"en-us": "a", "en-gb": "b", "en-in": "a", "hi": "h"}  # Kokoro has no en-IN rules


def model_of(voice: dict[str, Any]) -> str:
    engine = voice["engine"]
    if engine not in ENGINES:
        raise VoiceError(f"{engine} isn't installed; it's decided at voice casting")
    return ENGINES[engine]["model"]


def parler_description(voice: dict[str, Any]) -> str:
    """Parler is steered by a description. Code writes it from the voice's settings (the LLM
    never does), naming the speaker so the voice stays the same from line to line."""
    v = _defaults(voice)
    pitch = {"low": "low-pitched", "moderate": "moderate in pitch", "high": "high-pitched"}
    e = v["expressiveness"]
    style = "monotone" if e < 0.25 else "very expressive and animated" if e > 0.75 else "expressive"
    pace = "slowly" if v["speed"] < 0.9 else "quickly" if v["speed"] > 1.1 else "at a moderate pace"
    return (
        f"{v['speaker']}'s voice is {pitch[v['pitch']]} and {style}, speaking {pace}, "
        "with a very clear, close-up recording that has no background noise."
    )


def seed_of(text: str, voice: dict[str, Any]) -> int:
    """A fixed seed per line for engines that sample (Parler): same line, same take."""
    return int(line_hash(text, voice, model_of(voice))[:8], 16)


def run_worker(engine: str, job: dict[str, Any], cfg: StudioConfig) -> dict[str, Any]:
    python = expand_path(cfg.get("envs", ENGINES[engine]["env"])["python"])
    worker = WORKER.parent / ENGINES[engine]["worker"]
    proc = subprocess.run(
        [str(python), str(worker)], input=json.dumps(job), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise VoiceError(f"the {engine} worker failed: {proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _job(engine: str, items: list[dict[str, Any]], raw_dir: str, cfg: StudioConfig) -> dict:
    if engine == "kokoro":
        return {
            "out_dir": raw_dir,
            "device": cfg.get("audio", "kokoro_device", "cpu"),
            "voices": items[0]["voice"]["voices"],
            "speed": 1.0,
            "lines": [
                {
                    "key": it["key"],
                    "text": it["text"],
                    "voices": it["voice"]["voices"],
                    "speed": _defaults(it["voice"])["speed"],
                    "lang": KOKORO_LANG.get(it["voice"].get("language", "")),
                }
                for it in items
            ],
        }
    return {
        "out_dir": raw_dir,
        "device": cfg.get("audio", "parler_device", "mps"),
        "lines": [
            {
                "key": it["key"],
                "text": it["text"],
                "description": parler_description(it["voice"]),
                "seed": seed_of(it["text"], it["voice"]),
            }
            for it in items
        ],
    }


# --------------------------------------------------------------------------- synthesis


def postprocess(raw: Path, out: Path, voice: dict[str, Any], cfg: StudioConfig) -> float:
    """Trim, pitch, normalize: raw worker output → final 24 kHz mono 16-bit WAV. Returns seconds."""
    voice = _defaults(voice)
    shaped = out.with_suffix(".shaped.wav")
    chain = ",".join(
        f
        for f in (ffmpeg.trim_filter(), ffmpeg.pitch_filter(voice["pitch_semitones"], SAMPLE_RATE))
        if f
    )
    ffmpeg.run(
        ["-i", str(raw), "-af", chain, "-ar", str(SAMPLE_RATE), "-ac", "1", str(shaped)], cfg
    )
    gain = ffmpeg.gain_to(ffmpeg.measure(shaped, cfg), voice["loudness_lufs"], PEAK_CEILING_DB)
    ffmpeg.run(
        ["-i", str(shaped), "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(out)], cfg
    )
    shaped.unlink()
    return ffmpeg.duration(out)


def synthesize(
    items: list[dict[str, Any]], out_dir: Path, cfg: StudioConfig | None = None
) -> tuple[dict[str, Path], dict[str, str]]:
    """Speak `items` ({key, text, voice}) into out_dir/<key>.wav, finished. One worker call per
    engine. Returns ({key: wav}, {engine: model name the worker reported})."""
    cfg = cfg or load_config()
    for item in items:
        model_of(item["voice"])  # refuses engines that aren't installed
    out_dir.mkdir(parents=True, exist_ok=True)
    out, models = {}, {}
    for engine in sorted({it["voice"]["engine"] for it in items}):
        group = [it for it in items if it["voice"]["engine"] == engine]
        with tempfile.TemporaryDirectory(dir=out_dir, prefix=".raw-") as raw_dir:
            result = run_worker(engine, _job(engine, group, raw_dir, cfg), cfg)
            models[engine] = result["model"]
            for it in group:
                wav = out_dir / f"{it['key']}.wav"
                postprocess(Path(result["files"][it["key"]]), wav, it["voice"], cfg)
                out[it["key"]] = wav
    return out, models


def speak(
    film_root: Path,
    character_id: str,
    lines: list[dict[str, str]],
    *,
    regenerate: bool = False,
    cues: bool = True,
    cfg: StudioConfig | None = None,
) -> list[SpokenLine]:
    """Speak lines ({text, optional line_id}) in the character's voice. See the module docstring."""
    if not lines:
        raise VoiceError("no lines to speak")
    voice = load_voice(film_root, character_id)
    problems = [
        f"line {i} ({line.get('line_id', 'new')}): {p}"
        for i, line in enumerate(lines)
        for p in check_text(line.get("text", ""))
    ]
    for i, line in enumerate(lines):
        if "line_id" in line and not LINE_ID.match(line["line_id"]):
            problems.append(f"line {i}: {line['line_id']!r} is not a line id like 'l007'")
    if problems:
        raise VoiceError("; ".join(problems))

    model = model_of(voice)
    known = existing_lines(film_root)
    by_hash = {m["hash"]: lid for lid, m in known.items() if m["character"] == character_id}
    plan: list[dict[str, Any]] = []  # per input line: id, text, hash, take, cached
    taken: set[str] = set()
    for line in lines:
        text = " ".join(line["text"].split())
        digest = line_hash(text, voice, model)
        lid = line.get("line_id") or (None if regenerate else by_hash.get(digest))
        lid = lid or next_line_id(film_root, taken)
        if lid in taken:
            raise VoiceError(f"line {lid} appears twice in one request")
        taken.add(lid)
        old = known.get(lid)
        if old and old["character"] != character_id:
            raise VoiceError(f"line {lid} belongs to {old['character']}; use a new line id")
        cached = bool(old) and old["hash"] == digest and not regenerate
        take = (old["take"] + (0 if cached else 1)) if old else 1
        plan.append({"id": lid, "text": text, "hash": digest, "take": take, "cached": cached})

    folder = _dialogue_dir(film_root)
    todo = [p for p in plan if not p["cached"]]
    with tempfile.TemporaryDirectory(dir=film_root, prefix=".speak-") as work:
        wavs, reported = synthesize(
            [{"key": p["id"], "text": p["text"], "voice": voice} for p in todo], Path(work), cfg
        )
        if todo and reported.get(voice["engine"]) != model:
            raise VoiceError(
                f"the worker reports {reported.get(voice['engine'])!r}, expected {model!r}; "
                "update ENGINES"
            )
        folder.mkdir(parents=True, exist_ok=True)
        for p in todo:
            wav = folder / f"{p['id']}.wav"
            wavs[p["id"]].replace(wav)
            meta = {
                "schema_version": 1,
                "line_id": p["id"],
                "character": character_id,
                "text": p["text"],
                "voice": voice,
                "model": model,
                "sample_rate": SAMPLE_RATE,
                "duration_s": round(ffmpeg.duration(wav), 3),
                "hash": p["hash"],
                "take": p["take"],
                "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            issues = validate("line", meta)
            if issues:  # a bug on our side, not the caller's
                raise RuntimeError(f"line metadata is invalid: {issues}")
            (folder / f"{p['id']}.txt").write_text(p["text"] + "\n")
            (folder / f"{p['id']}.json").write_text(json.dumps(meta, indent=2) + "\n")
            stale = film_root / "audio" / "lipsync" / f"{p['id']}.json"
            stale.unlink(missing_ok=True)  # cues of the previous take no longer match
    cue_files = {}
    if cues:
        cue_files = {
            r.line_id: r.cues for r in lipsync(film_root, [p["id"] for p in plan], cfg=cfg)
        }
    return [
        SpokenLine(
            line_id=p["id"],
            wav=folder / f"{p['id']}.wav",
            text=p["text"],
            duration_s=ffmpeg.duration(folder / f"{p['id']}.wav"),
            take=p["take"],
            cached=p["cached"],
            cues=cue_files.get(p["id"]),
        )
        for p in plan
    ]
