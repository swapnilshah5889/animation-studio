"""Lip-sync: a finished dialogue line → mouth cues (task 3.3, D-036, D-022).

    results = lipsync(film_root, ["l001", "l002"])

Runs Rhubarb Lip Sync on audio/dialogue/<line>.wav with the line's text as a hint
(`--dialogFile`, which makes recognition much more accurate), and writes
audio/lipsync/<line>.json in Rhubarb's own JSON format (schemas/lipsync.schema.json): mouth
shapes A to H and X, the set the procedural mouth draws (D-007).

- **Recognizer:** `pocketSphinx` for English voices (Kokoro ids starting with a or b),
  `phonetic` (language-independent) for anything else.
- **Cache:** cues that exist, validate and match the audio's length are reused. `speak` deletes
  the cues of any line whose audio it replaces, so a re-take is always redone.
- Lines run in parallel (Rhubarb uses one core per line; it runs under Rosetta, D-022).
- `soundFile` is stored relative to the cues file's folder, so film folders stay portable.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from studio_core.audio import ffmpeg
from studio_core.config import StudioConfig, load_config
from studio_core.schema import CUE_TOLERANCE_S, validate

ENGLISH_VOICE_PREFIXES = ("a", "b")  # Kokoro: a = US English, b = UK English
MAX_PARALLEL = 4


class LipsyncError(ValueError):
    """A lip-sync request was refused or Rhubarb failed. The message says what to fix."""


@dataclass(frozen=True)
class CueResult:
    line_id: str
    cues: Path
    n_cues: int
    shapes: str  # the distinct shapes used, e.g. "ABCEFGX"
    cached: bool


def recognizer_for(meta: dict | None) -> str:
    """pocketSphinx when every voice of the line is English (or the line has no metadata, as
    the Step 0 fixture lines), phonetic otherwise."""
    if meta is None:
        return "pocketSphinx"
    ids = [v["id"] for v in meta["voice"]["voices"]]
    return "pocketSphinx" if all(i[0] in ENGLISH_VOICE_PREFIXES for i in ids) else "phonetic"


def _paths(film_root: Path, line_id: str) -> tuple[Path, Path, Path, Path]:
    dialogue = film_root / "audio" / "dialogue"
    return (
        dialogue / f"{line_id}.wav",
        dialogue / f"{line_id}.txt",
        dialogue / f"{line_id}.json",
        film_root / "audio" / "lipsync" / f"{line_id}.json",
    )


def _usable(cues_file: Path, wav: Path) -> dict | None:
    """The existing cues if they are valid and match this audio, else None."""
    if not cues_file.is_file():
        return None
    data = json.loads(cues_file.read_text())
    if validate("lipsync", data):
        return None
    if abs(data["metadata"]["duration"] - ffmpeg.duration(wav)) > CUE_TOLERANCE_S:
        return None
    return data


def run_rhubarb(wav: Path, text: str | None, recognizer: str, cfg: StudioConfig) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cues.json"
        cmd = [
            str(cfg.path("tools", "rhubarb")),
            "--exportFormat",
            "json",
            "--recognizer",
            recognizer,
            "--extendedShapes",
            "GHX",
            "--output",
            str(out),
        ]
        if text:
            dialog = Path(tmp) / "dialog.txt"
            dialog.write_text(text + "\n")
            cmd += ["--dialogFile", str(dialog)]
        proc = subprocess.run([*cmd, str(wav)], capture_output=True, text=True)
        if proc.returncode != 0 or not out.is_file():
            raise LipsyncError(f"Rhubarb failed on {wav.name}: {proc.stderr[-800:]}")
        return json.loads(out.read_text())


def _one(film_root: Path, line_id: str, force: bool, cfg: StudioConfig) -> CueResult:
    wav, txt, meta_file, cues_file = _paths(film_root, line_id)
    cached = None if force else _usable(cues_file, wav)
    if cached is None:
        meta = json.loads(meta_file.read_text()) if meta_file.is_file() else None
        text = txt.read_text().strip() if txt.is_file() else None
        data = run_rhubarb(wav, text, recognizer_for(meta), cfg)
        data["metadata"]["soundFile"] = f"../dialogue/{wav.name}"  # relative to the cues file
        issues = validate("lipsync", data)
        if issues:
            raise LipsyncError(f"Rhubarb's cues for {line_id} are invalid: {issues}")
        cues_file.parent.mkdir(parents=True, exist_ok=True)
        cues_file.write_text(json.dumps(data, indent=1) + "\n")
    data = cached or json.loads(cues_file.read_text())
    shapes = "".join(sorted({c["value"] for c in data["mouthCues"]}))
    return CueResult(line_id, cues_file, len(data["mouthCues"]), shapes, cached is not None)


def lipsync(
    film_root: Path,
    line_ids: list[str],
    *,
    force: bool = False,
    cfg: StudioConfig | None = None,
) -> list[CueResult]:
    """Mouth cues for each line (see the module docstring). Refuses unknown lines up front."""
    cfg = cfg or load_config()
    missing = [lid for lid in line_ids if not _paths(film_root, lid)[0].is_file()]
    if missing:
        raise LipsyncError(f"no audio for {missing}; speak the lines first")
    if len(set(line_ids)) != len(line_ids):
        raise LipsyncError("a line appears twice in one request")
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, max(1, len(line_ids)))) as pool:
        return list(pool.map(lambda lid: _one(film_root, lid, force, cfg), line_ids))
