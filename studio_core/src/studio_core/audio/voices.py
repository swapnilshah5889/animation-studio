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
WORKER = REPO_ROOT / "scripts" / "audio" / "kokoro_batch.py"
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


def check_text(text: str) -> list[str]:
    """Why a line can't be spoken in a children's film ([] = fine)."""
    problems = []
    if not text.strip():
        return ["the text is blank"]
    if len(text) > 300:
        problems.append(f"the text is {len(text)} characters; split it into lines of at most 300")
    if re.search(r"https?://|www\.|@\w+\.\w", text):
        problems.append("the text contains a web or email address")
    odd = sorted({c for c in text if not ALLOWED.match(c)})
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
    return {"speed": 1.0, "pitch_semitones": 0.0, "loudness_lufs": -20.0, **voice}


# --------------------------------------------------------------------------- synthesis


def run_worker(job: dict[str, Any], cfg: StudioConfig) -> dict[str, Any]:
    python = expand_path(cfg.get("envs", "kokoro")["python"])
    proc = subprocess.run(
        [str(python), str(WORKER)], input=json.dumps(job), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise VoiceError(f"the Kokoro worker failed: {proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


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
) -> tuple[dict[str, Path], str]:
    """Speak `items` ({key, text, voice}) into out_dir/<key>.wav, finished. One worker call.
    Returns ({key: wav}, model name)."""
    cfg = cfg or load_config()
    for item in items:
        if item["voice"]["engine"] != "kokoro":
            raise VoiceError(
                f"{item['voice']['engine']} isn't installed; it's decided at voice casting"
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".raw-") as raw_dir:
        job = {
            "out_dir": raw_dir,
            "device": cfg.get("audio", "kokoro_device", "cpu"),
            "voices": items[0]["voice"]["voices"] if items else [],
            "speed": 1.0,
            "lines": [
                {
                    "key": it["key"],
                    "text": it["text"],
                    "voices": it["voice"]["voices"],
                    "speed": _defaults(it["voice"])["speed"],
                }
                for it in items
            ],
        }
        result = run_worker(job, cfg) if items else {"files": {}, "model": ""}
        out = {}
        for it in items:
            wav = out_dir / f"{it['key']}.wav"
            postprocess(Path(result["files"][it["key"]]), wav, it["voice"], cfg)
            out[it["key"]] = wav
    return out, result["model"]


MODEL = "kokoro-82m v1.0 (kokoro 0.9.4)"  # what the worker reports; part of every line's hash


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

    known = existing_lines(film_root)
    by_hash = {m["hash"]: lid for lid, m in known.items() if m["character"] == character_id}
    plan: list[dict[str, Any]] = []  # per input line: id, text, hash, take, cached
    taken: set[str] = set()
    for line in lines:
        text = " ".join(line["text"].split())
        digest = line_hash(text, voice, MODEL)
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
        wavs, model = synthesize(
            [{"key": p["id"], "text": p["text"], "voice": voice} for p in todo], Path(work), cfg
        )
        if todo and model != MODEL:
            raise VoiceError(f"the worker reports {model!r}, expected {MODEL!r}; update MODEL")
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
                "model": MODEL,
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
