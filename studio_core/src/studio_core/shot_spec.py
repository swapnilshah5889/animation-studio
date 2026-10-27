"""Editing shot specs: the director's verbs, engine-neutral (D-028, D-030).

The director never writes engine files. It edits **intent** in `shots/<id>/shot.json` through
these functions, and a backend (`studio_core.shot` for Synfig) compiles the saved spec.

Every edit follows the same steps: load the spec, change one thing, check the whole spec, save
it only if it is valid. The checks are the shot schema, its semantic rules
(`studio_core.schema.check_shot`), and the film's own assets: the background, rigs, views, bone
names and dialogue files must exist. A failed check raises `SpecError` with a message an LLM can
act on ("unknown bone 'tail'; pip has: head, torso, ..."). Softer problems come back as warnings.
"""

from __future__ import annotations

import json
import re
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio_core import placement
from studio_core.audio.library import LibraryError, load_library
from studio_core.config import REPO_ROOT
from studio_core.film import Film
from studio_core.motions import MotionError, animate
from studio_core.rig import RigError, load_rig
from studio_core.schema import CUE_TOLERANCE_S, validate
from studio_core.sif.units import frames

FPS = 24  # shot lists can choose another rate later; Step 2 shots are all 24 fps
FILM_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# The placeholder puppet (Pip) that build_rig copies when no rig is given, until Step 4
# generates real puppets.
PLACEHOLDER_RIG = REPO_ROOT / "tests" / "fixtures" / "characters" / "pip"
REMOVABLE = ("character", "action", "pose", "expression", "dialogue", "sound_effect", "movement")


class SpecError(ValueError):
    """An edit was refused. The message says what to fix."""


def _known(items: list[str]) -> str:
    return ", ".join(items) if items else "none"


@dataclass(frozen=True)
class FilmFolder:
    """A film project folder (docs/ARCHITECTURE.md "Film project folder")."""

    root: Path
    sfx_root: Path | None = None  # the sound library; None = config [paths] sfx_library

    @classmethod
    def open(cls, films_root: Path, slug: str, *, sfx_root: Path | None = None) -> FilmFolder:
        if not FILM_SLUG.match(slug):
            raise SpecError(f"film {slug!r} is not a film name (lowercase letters, digits, '-')")
        root = films_root / slug
        if not root.is_dir():
            known = (
                sorted(p.name for p in films_root.iterdir() if p.is_dir())
                if films_root.is_dir()
                else []
            )
            raise SpecError(f"no film {slug!r}; films: {_known(known)}")
        return cls(root, sfx_root)

    @property
    def slug(self) -> str:
        return self.root.name

    def shot_file(self, shot_id: str) -> Path:
        return self.root / "shots" / shot_id / "shot.json"

    def rig_file(self, character_id: str) -> Path:
        return self.root / "characters" / character_id / "rig.json"

    def background_file(self, background_id: str) -> Path:
        return self.root / "backgrounds" / background_id / "layers.json"

    def line_files(self, line_id: str) -> tuple[Path, Path, Path]:
        audio = self.root / "audio"
        return (
            audio / "dialogue" / f"{line_id}.wav",
            audio / "lipsync" / f"{line_id}.json",
            audio / "dialogue" / f"{line_id}.txt",
        )

    def line_meta(self, line_id: str) -> Path:
        return self.root / "audio" / "dialogue" / f"{line_id}.json"

    def music_file(self, cue_id: str) -> Path:
        return self.root / "audio" / "music" / f"{cue_id}.wav"

    def music_cues(self) -> list[str]:
        folder = self.root / "audio" / "music"
        return sorted(p.stem for p in folder.glob("*.wav")) if folder.is_dir() else []

    def _ids(self, folder: str, marker: str) -> list[str]:
        base = self.root / folder
        return (
            sorted(p.name for p in base.iterdir() if (p / marker).is_file())
            if base.is_dir()
            else []
        )

    def characters(self) -> list[str]:
        return self._ids("characters", "rig.json")

    def backgrounds(self) -> list[str]:
        return self._ids("backgrounds", "layers.json")

    def shots(self) -> list[str]:
        return self._ids("shots", "shot.json")

    def lines(self) -> list[str]:
        folder = self.root / "audio" / "dialogue"
        return sorted(p.stem for p in folder.glob("*.wav")) if folder.is_dir() else []


# --------------------------------------------------------------------------- load, check, save


def load(film: FilmFolder, shot_id: str) -> dict[str, Any]:
    path = film.shot_file(shot_id)
    if not path.is_file():
        raise SpecError(
            f"no shot {shot_id!r} in film {film.slug!r}; shots: {_known(film.shots())}. "
            "Create it with create_scene."
        )
    return json.loads(path.read_text())


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def check(film: FilmFolder, spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a whole spec against the schema and the film's assets."""
    issues = validate("shot", spec)
    if issues:  # asset checks assume a well-formed spec
        return [str(i) for i in issues], []
    errors: list[str] = []
    warnings: list[str] = []
    if not film.background_file(spec["background"]).is_file():
        errors.append(
            f"background {spec['background']!r} not found; "
            f"backgrounds: {_known(film.backgrounds())}"
        )
    n_frames = frames(spec["duration_s"], FPS)
    for char in spec["characters"]:
        cid = char["id"]
        if not film.rig_file(cid).is_file():
            errors.append(f"character {cid!r} not found; characters: {_known(film.characters())}")
            continue
        try:
            rig = load_rig(film.rig_file(cid))
            view = rig.view(char.get("view"))
        except RigError as e:
            errors.append(str(e))
            continue
        try:  # catches motions a rig can't do (missing limbs) and unknown pose bones
            animate(
                view,
                char.get("actions", []),
                fps=FPS,
                n_frames=n_frames,
                poses=char.get("poses"),
                seed=cid,
            )
        except MotionError as e:
            errors.append(f"{cid}: {e}")
        motions = {a["motion"] for a in char.get("actions", [])}
        if "blink" not in motions and "face" in view:
            warnings.append(f"{cid} never blinks; add the 'blink' motion for the whole shot")
    _check_dialogue(film, spec, errors, warnings)
    _check_sounds(film, spec, errors, warnings)
    return errors, warnings


def _check_dialogue(
    film: FilmFolder, spec: dict[str, Any], errors: list[str], warnings: list[str]
) -> None:
    for line in spec.get("dialogue", []):
        lid = line["line_id"]
        wav, cues, _ = film.line_files(lid)
        if not wav.is_file():
            errors.append(f"line {lid!r} has no audio at {wav}; lines: {_known(film.lines())}")
            continue
        seconds = wav_seconds(wav)
        meta = film.line_meta(lid)
        if meta.is_file():  # lines made by speak (Step 3) carry metadata; fixture lines may not
            data = json.loads(meta.read_text())
            issues = validate("line", data)
            if issues:
                errors.append(f"line {lid!r} metadata: " + "; ".join(map(str, issues)))
            elif data["character"] != line["character"]:
                errors.append(
                    f"line {lid!r} was recorded in {data['character']}'s voice, "
                    f"but {line['character']} says it"
                )
        if not cues.is_file():
            errors.append(f"line {lid!r} has no mouth cues at {cues}; run lipsync on it")
        else:
            cue_data = json.loads(cues.read_text())
            issues = validate("lipsync", cue_data)
            if issues:
                errors.append(f"line {lid!r} mouth cues: " + "; ".join(map(str, issues)))
            elif abs(cue_data["metadata"]["duration"] - seconds) > CUE_TOLERANCE_S:
                errors.append(
                    f"line {lid!r} mouth cues were made for {cue_data['metadata']['duration']}s "
                    f"of audio, but the audio is {seconds:.2f}s; run lipsync on it again"
                )
        end = line["start_s"] + seconds
        if end > spec["duration_s"] + 1e-6:
            warnings.append(
                f"line {lid} ends at {end:.2f}s, after the {spec['duration_s']}s shot; "
                "it will be cut off"
            )


def _check_sounds(
    film: FilmFolder, spec: dict[str, Any], errors: list[str], warnings: list[str]
) -> None:
    effects = spec.get("sfx", [])
    library = None
    if any("sound" in e for e in effects):  # only read the library when a sound is chosen
        try:
            library = load_library(film.sfx_root)
        except LibraryError as e:
            errors.append(f"the sound library is broken: {e}")
    for i, effect in enumerate(effects):
        where = f"sound effect '{effect['query']}' at {effect['start_s']}s"
        if "sound" not in effect:
            warnings.append(f"{where} has no sound chosen yet; it is silent until one is set")
        elif library is not None and effect["sound"] not in library.sounds:
            errors.append(
                f"sfx[{i}]: {where} uses sound {effect['sound']!r}, which is not in the library "
                f"({len(library.sounds)} sounds); search with find_sfx"
            )
    cue = spec.get("music_cue")
    if cue and not film.music_file(cue).is_file():
        errors.append(f"music cue {cue!r} not found; cues: {_known(film.music_cues())}")


def save(film: FilmFolder, spec: dict[str, Any]) -> list[str]:
    """Check and save; returns warnings. Raises SpecError (nothing saved) if the spec is invalid."""
    errors, warnings = check(film, spec)
    if errors:
        raise SpecError("; ".join(errors))
    path = film.shot_file(spec["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2) + "\n")
    return warnings


def _character(spec: dict[str, Any], character_id: str) -> dict[str, Any]:
    for char in spec["characters"]:
        if char["id"] == character_id:
            return char
    present = [c["id"] for c in spec["characters"]]
    raise SpecError(
        f"{character_id!r} is not in shot {spec['id']}; in the shot: {_known(present)}. "
        "Add it with add_character first."
    )


# --------------------------------------------------------------------------- edits


def create_shot(
    film: FilmFolder,
    shot_id: str,
    duration_s: float,
    background: str,
    camera: dict[str, Any] | None = None,
    *,
    replace: bool = False,
) -> list[str]:
    if film.shot_file(shot_id).is_file() and not replace:
        raise SpecError(
            f"shot {shot_id!r} already exists; edit it, or pass replace=true to start it over"
        )
    spec: dict[str, Any] = {
        "schema_version": 1,
        "id": shot_id,
        "duration_s": duration_s,
        "background": background,
        "characters": [],
    }
    if camera:
        spec["camera"] = camera
    return save(film, spec)


def place_character(
    film: FilmFolder,
    shot_id: str,
    character_id: str,
    position: list[float],
    *,
    view: str | None = None,
    scale: float | None = None,
    facing: str | None = None,
) -> list[str]:
    """Add a character to the shot, or move it if it is already there (its tracks stay)."""
    spec = load(film, shot_id)
    try:
        char = _character(spec, character_id)
    except SpecError:
        char = {"id": character_id}
        spec["characters"].append(char)
    char["position"] = list(position)
    for key, value in (("view", view), ("scale", scale), ("facing", facing)):
        if value is not None:
            char[key] = value
    return save(film, spec)


def move_character(
    film: FilmFolder,
    shot_id: str,
    character_id: str,
    to: list[float],
    start_s: float,
    duration_s: float,
    ease: str = placement.DEFAULT_EASE,
) -> list[str]:
    """Move a character to `to` (where its feet end up) starting at start_s and taking
    duration_s. It stays where it is until start_s. Moves come in time order: a new move may not
    start before the last one ends."""
    if ease not in placement.EASES:
        raise SpecError(f"unknown ease {ease!r}; use one of: {', '.join(placement.EASES)}")
    spec = load(film, shot_id)
    char = _character(spec, character_id)
    path = char.setdefault("path", [])
    if path and start_s < path[-1]["time_s"] - 1e-9:
        raise SpecError(
            f"{character_id} is still moving until {path[-1]['time_s']}s; start this move at "
            "or after that, or remove the earlier move first"
        )
    if start_s > 1e-9 and (not path or start_s > path[-1]["time_s"] + 1e-9):
        here = placement.position_at(char["position"], path, start_s)
        path.append({"time_s": start_s, "position": [round(v, 6) for v in here], "ease": "linear"})
    path.append({"time_s": start_s + duration_s, "position": list(to), "ease": ease})
    return save(film, spec)


def add_action(
    film: FilmFolder,
    shot_id: str,
    character_id: str,
    motion: str,
    start_s: float,
    *,
    duration_s: float | None = None,
    params: dict[str, Any] | None = None,
) -> list[str]:
    spec = load(film, shot_id)
    action: dict[str, Any] = {"motion": motion, "start_s": start_s}
    if duration_s is not None:
        action["duration_s"] = duration_s
    if params:
        action["params"] = params
    _character(spec, character_id).setdefault("actions", []).append(action)
    return save(film, spec)


def add_pose(
    film: FilmFolder, shot_id: str, character_id: str, time_s: float, bones: dict[str, float]
) -> list[str]:
    """A manual key pose: bone angles (degrees from rest) at time_s. Replaces a pose at the
    same time."""
    spec = load(film, shot_id)
    char = _character(spec, character_id)
    poses = [p for p in char.get("poses", []) if p["time_s"] != time_s]
    char["poses"] = sorted([*poses, {"time_s": time_s, "bones": bones}], key=lambda p: p["time_s"])
    return save(film, spec)


def add_expression(
    film: FilmFolder, shot_id: str, character_id: str, expr: str, start_s: float
) -> list[str]:
    """The character's expression from start_s on. Replaces an expression at the same time."""
    spec = load(film, shot_id)
    char = _character(spec, character_id)
    kept = [e for e in char.get("expressions", []) if e["start_s"] != start_s]
    char["expressions"] = sorted(
        [*kept, {"expr": expr, "start_s": start_s}], key=lambda e: e["start_s"]
    )
    return save(film, spec)


def add_dialogue(
    film: FilmFolder,
    shot_id: str,
    character_id: str,
    line_id: str,
    start_s: float,
    text: str | None = None,
) -> list[str]:
    """The character speaks a recorded line at start_s: its audio plays and its Rhubarb cues
    drive the mouth. The text defaults to audio/dialogue/<line_id>.txt. Re-adding a line
    moves it."""
    spec = load(film, shot_id)
    _character(spec, character_id)
    if text is None:
        txt = film.line_files(line_id)[2]
        if not txt.is_file():
            raise SpecError(f"line {line_id!r} has no transcript at {txt}; pass its text")
        text = txt.read_text().strip()
    lines = [line for line in spec.get("dialogue", []) if line["line_id"] != line_id]
    line = {"character": character_id, "line_id": line_id, "text": text, "start_s": start_s}
    spec["dialogue"] = sorted([*lines, line], key=lambda line: line["start_s"])
    return save(film, spec)


def set_background(film: FilmFolder, shot_id: str, background_id: str) -> list[str]:
    spec = load(film, shot_id)
    spec["background"] = background_id
    return save(film, spec)


def set_camera(
    film: FilmFolder,
    shot_id: str,
    move: str,
    *,
    start_s: float | None = None,
    duration_s: float | None = None,
    zoom: float | None = None,
) -> list[str]:
    spec = load(film, shot_id)
    camera: dict[str, Any] = {"move": move}
    for key, value in (("zoom", zoom), ("start_s", start_s), ("duration_s", duration_s)):
        if value is not None:
            camera[key] = value
    spec["camera"] = camera
    return save(film, spec)


def add_sound_effect(
    film: FilmFolder,
    shot_id: str,
    sound_id: str,
    start_s: float,
    *,
    volume: float = 0.5,
    query: str | None = None,
) -> list[str]:
    """Play a library sound (found with find_sfx) at start_s. `query` is the description it
    answers (kept for humans and re-searching); it defaults to the sound's own description."""
    library = load_library(film.sfx_root)
    if sound_id not in library.sounds:
        raise SpecError(
            f"no sound {sound_id!r} in the library ({len(library.sounds)} sounds); "
            "search with find_sfx"
        )
    if query is None:
        sound = library.sounds[sound_id]
        query = (sound.get("description") or sound_id)[:100]
    spec = load(film, shot_id)
    effect = {"query": query, "sound": sound_id, "start_s": start_s, "volume": volume}
    spec["sfx"] = sorted([*spec.get("sfx", []), effect], key=lambda e: e["start_s"])
    return save(film, spec)


def set_music(
    film: FilmFolder, shot_id: str, cue_id: str | None, *, volume: float | None = None
) -> list[str]:
    """The shot's music cue (made with compose), or None for no music."""
    spec = load(film, shot_id)
    spec["music_cue"] = cue_id
    if cue_id is None:
        spec.pop("music_volume", None)
    elif volume is not None:
        spec["music_volume"] = volume
    return save(film, spec)


def remove_item(
    film: FilmFolder,
    shot_id: str,
    kind: str,
    *,
    character_id: str | None = None,
    index: int | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Remove a character (and its dialogue), or one action/pose/expression/dialogue line/sound
    effect by its index in describe_shot. Returns (what was removed, warnings)."""
    if kind not in REMOVABLE:
        raise SpecError(f"unknown kind {kind!r}; known: {', '.join(REMOVABLE)}")
    spec = load(film, shot_id)
    if kind == "dialogue":
        items = spec.get("dialogue", [])
    elif kind == "sound_effect":
        items = spec.get("sfx", [])
    elif character_id is None:
        raise SpecError(f"removing a {kind} needs character_id")
    elif kind == "character":
        char = _character(spec, character_id)
        spec["characters"].remove(char)
        spec["dialogue"] = [d for d in spec.get("dialogue", []) if d["character"] != character_id]
        return char, save(film, spec)
    elif kind == "movement":  # the whole path; the character stays at its start position
        char = _character(spec, character_id)
        removed = {"path": char.pop("path", [])}
        return removed, save(film, spec)
    else:
        items = _character(spec, character_id).get(f"{kind}s", [])
    if index is None or not 0 <= index < len(items):
        raise SpecError(f"{kind} index {index} is out of range: there are {len(items)} (0-based)")
    removed = items.pop(index)
    return removed, save(film, spec)


# --------------------------------------------------------------------------- rigs


def register_rig(
    film: FilmFolder, character_id: str, rig: dict[str, Any] | None = None
) -> tuple[Path, bool]:
    """Validate and register characters/<id>/rig.json. With no rig, copy the placeholder puppet
    under this id. Returns (rig path, created from the placeholder)."""
    if not ID.match(character_id):
        raise SpecError(f"{character_id!r} is not an id (lowercase letters, digits, '_')")
    folder = film.root / "characters" / character_id
    placeholder = rig is None
    if placeholder:
        if film.rig_file(character_id).is_file():
            raise SpecError(f"{character_id!r} already has a rig; pass rig to replace it")
        # The puppet only: the placeholder's voice belongs to Pip, not to this character.
        shutil.copytree(
            PLACEHOLDER_RIG, folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("voice.json")
        )
        rig = json.loads((PLACEHOLDER_RIG / "rig.json").read_text())
        rig["id"], rig["name"] = character_id, character_id.replace("_", " ").title()
    assert rig is not None
    if rig.get("id") != character_id:
        raise SpecError(
            f"the rig's id is {rig.get('id')!r} but the character id is {character_id!r}"
        )
    folder.mkdir(parents=True, exist_ok=True)
    trial = folder / "rig.json.new"  # parts resolve relative to the folder, like the real file
    trial.write_text(json.dumps(rig, indent=2) + "\n")
    try:
        load_rig(trial)
    except RigError as e:
        trial.unlink()
        raise SpecError(str(e).replace(str(trial), "rig.json")) from None
    trial.replace(film.rig_file(character_id))
    if (film.root / "film.json").is_file():
        try:
            Film.load(film.root).add_character(character_id)
        except ValueError as e:
            raise SpecError(f"rig saved, but film.json refused the character: {e}") from None
    return film.rig_file(character_id), placeholder
