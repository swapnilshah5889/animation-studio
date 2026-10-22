"""Download the CC0 sound-effect starter library and write its manifest (task 3.5, D-036).

    uv run scripts/fetch_sfx_library.py          # → <sfx_library>/ (config [paths] sfx_library)

Sources are listed below with the page where each license was checked. **CC0 only**: the
manifest schema refuses anything else (sfx_library.schema.json). Every sound is converted to
48 kHz mono 16-bit WAV (what CLAP indexes and the mix uses); the downloaded originals stay in
_downloads/ so the conversion can be redone offline.

Plus FSD50K's eval split: CC0 clips only, minus labels and words not for a children's film
(fsd50k_selection). Its 6 GB split zip is downloaded, joined, the chosen clips extracted, and
the archives deleted.

Not included, on purpose:
- BigSoundBank: its robots.txt keeps every robot off its audio files, and its ai.txt asks that
  they not be used for training. A human may hand-pick sounds there later.
- Sounds whose names say they aren't for a children's film (`EXCLUDE`).

Safe to re-run: downloads are skipped when present, and the manifest is rebuilt from disk.
OpenGameArt asks robots for 10 s between requests; this script waits that long between its
downloads there.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from studio_core.audio import ffmpeg
from studio_core.config import load_config
from studio_core.schema import validate

USER_AGENT = "animation-studio (local CC0 sound library; one-time download)"
AUDIO = {".wav", ".ogg", ".mp3", ".flac"}
MIN_S, MAX_S = 0.05, 60.0
EXCLUDE = re.compile(
    r"gun|shot|rifle|pistol|blood|gore|kill|death|dead|zombie|scream|"
    r"explosion|bomb|grenade|sword|stab|monster|ghost|horror|creepy",
    re.IGNORECASE,
)
PREVIEW = re.compile(r"preview|montage", re.IGNORECASE)  # a pack's demo reel, not a sound

KENNEY = "https://kenney.nl/media/pages/assets"
OGA = "https://opengameart.org"
SOURCES = [  # (source, pack, license page, [download urls])
    *[
        (
            "kenney",
            pack,
            f"https://kenney.nl/assets/{slug}",
            [f"{KENNEY}/{slug}/{key}/kenney_{slug}.zip"],
        )
        for slug, pack, key in (
            ("impact-sounds", "Impact Sounds", "87b4ddecda-1677589768"),
            ("interface-sounds", "Interface Sounds", "fa43c1dd4d-1677589452"),
            ("rpg-audio", "RPG Audio", "8e99002d76-1677590336"),
            ("ui-audio", "UI Audio", "490d233f68-1677590494"),
            ("music-jingles", "Music Jingles", "f37e530b9e-1677590399"),
            ("digital-audio", "Digital Audio", "216eac4753-1677590265"),
            ("sci-fi-sounds", "Sci-fi Sounds", "6b296f9ecf-1677589334"),
            ("casino-audio", "Casino Audio", "2472606a04-1721639069"),
        )
    ],
    # OpenGameArt: child-friendly packs whose pages list CC0 (checked 2026-10-22). Skipped: packs
    # that are one montage file (doors, GUI, squishes) and a copy of Kenney's jingles.
    *[
        ("oga", pack, f"{OGA}/content/{slug}", [f"{OGA}/sites/default/files/{f}" for f in files])
        for slug, pack, files in (
            (
                "different-steps-on-wood-stone-leaves-gravel-and-mud",
                "Different steps on wood, stone, leaves, gravel and mud",
                ["%5Bkdd%5DDifferentSteps_0.zip"],
            ),
            ("wind1", "Wind", [f"wind{i}.wav" for i in range(1, 6)]),
            ("dripping-water-loop", "Dripping water loop", ["atmosbasement.mp3_.flac"]),
            ("completion-sound", "Completion sound", ["completetask_0.mp3", "gmae.wav"]),
            ("jump-landing-sound", "Jump landing sound", ["jumpland.wav"]),
            ("bubbles-pop", "Bubbles pop", ["pop.ogg", "pop_0.ogg"]),
            (
                "level-up-power-up-coin-get-13-sounds",
                "Level up, power up, coin get",
                ["SoundPack01.zip"],
            ),
            ("swishes-sound-pack", "Swishes sound pack", ["swishes.zip"]),
            ("100-cc0-sfx-2", "100 CC0 SFX 2", ["sfx_100_v2.zip"]),
            ("50-cc0-retro-synth-sfx", "50 CC0 retro synth SFX", ["50-CC0-retro-synth-SFX.zip"]),
        )
    ],
]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def download(url: str, dest: Path, delay_s: float) -> bool:
    """Fetch url → dest unless it's there. Returns True if a request was made."""
    if dest.is_file() and dest.stat().st_size > 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    partial = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, length=1 << 20)  # streamed: some files are GBs
    partial.replace(dest)
    time.sleep(delay_s)
    return True


def originals(folder: Path) -> list[Path]:
    """Audio files in a pack folder, zips unpacked."""
    for archive in sorted(folder.glob("*.zip")):
        target = folder / archive.stem
        if not target.is_dir():
            with zipfile.ZipFile(archive) as z:
                z.extractall(target)
    return sorted(
        p
        for p in folder.rglob("*")
        if p.suffix.lower() in AUDIO and "__MACOSX" not in p.parts and not p.name.startswith(".")
    )


def words(path: Path) -> list[str]:
    raw = re.sub(r"([a-z])([A-Z])", r"\1 \2", path.stem)
    return [w for w in re.split(r"[^A-Za-z]+", raw.lower()) if len(w) > 1]


# --------------------------------------------------------------------------- FSD50K
# FSD50K (Zenodo 4060432): Freesound clips with AudioSet labels, a license per clip. Only the
# eval split's CC0 clips are used, minus the labels below (D-044).
FSD = "https://zenodo.org/api/records/4060432/files"
FSD_SMALL = ["FSD50K.metadata.zip", "FSD50K.ground_truth.zip", "FSD50K.doc.zip"]
FSD_AUDIO = ["FSD50K.eval_audio.z01", "FSD50K.eval_audio.zip"]  # one split zip, 6.26 GB
FSD_DENY = {
    # recordings of real people's voices and bodies: privacy and consent, children included
    "Human_voice", "Speech", "Male_speech_and_man_speaking", "Female_speech_and_woman_speaking",
    "Child_speech_and_kid_speaking", "Conversation", "Chatter", "Crowd", "Singing",
    "Male_singing", "Female_singing", "Laughter", "Giggle", "Chuckle_and_chortle", "Screaming",
    "Shout", "Yell", "Whispering", "Crying_and_sobbing", "Gasp", "Sigh", "Breathing",
    "Respiratory_sounds", "Cough", "Sneeze", "Burping_and_eructation", "Fart",
    "Chewing_and_mastication", "Speech_synthesizer", "Cheering",
    # violence
    "Gunshot_and_gunfire", "Explosion",
}  # fmt: skip
FSD_WORDS = re.compile(
    EXCLUDE.pattern + r"|sex|porn|nsfw|drug|beer|alcohol|vomit|puke|fuck|shit|damn|bitch",
    re.IGNORECASE,
)


def fsd50k_selection(folder: Path) -> list[dict]:
    """The eval clips we may use: CC0, no denied label, nothing unsuitable in their text."""
    for name in FSD_SMALL:
        download(f"{FSD}/{name}/content", folder / name, 1.0)
        with zipfile.ZipFile(folder / name) as z:
            z.extractall(folder)
    info = json.loads((folder / "FSD50K.metadata" / "eval_clips_info_FSD50K.json").read_text())
    chosen = []
    with (folder / "FSD50K.ground_truth" / "eval.csv").open() as fh:
        for row in csv.DictReader(fh):
            clip, labels = info[row["fname"]], row["labels"].split(",")
            text = " ".join([clip["title"], clip["description"], " ".join(clip["tags"])])
            if "publicdomain/zero" not in clip["license"] or set(labels) & FSD_DENY:
                continue
            if FSD_WORDS.search(text):
                continue
            chosen.append({"fname": row["fname"], "labels": labels, **clip})
    return chosen


def fsd50k_originals(folder: Path, chosen: list[dict]) -> Path:
    """Extract only the chosen clips; download and join the split zip only if some are missing.
    The 6 GB archives are deleted afterwards (the extracted CC0 clips are kept)."""
    out = folder / "eval_cc0"
    missing = [c for c in chosen if not (out / f"{c['fname']}.wav").is_file()]
    if missing:
        for name in FSD_AUDIO:
            if download(f"{FSD}/{name}/content", folder / name, 1.0):
                print(f"downloaded fsd50k/{name}", flush=True)
        joined = folder / "eval_joined.zip"
        if not joined.is_file():
            subprocess.run(
                ["zip", "-q", "-s", "0", str(folder / FSD_AUDIO[1]), "--out", str(joined)],
                check=True,
            )
        out.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(joined) as z:
            for clip in missing:
                member = f"FSD50K.eval_audio/{clip['fname']}.wav"
                (out / f"{clip['fname']}.wav").write_bytes(z.read(member))
        for name in [*FSD_AUDIO, joined.name]:
            (folder / name).unlink(missing_ok=True)
    return out


def fsd50k_sounds(lib: Path) -> list[dict]:
    folder = lib / "_downloads" / "fsd50k"
    chosen = fsd50k_selection(folder)
    originals = fsd50k_originals(folder, chosen)
    sounds = []
    for clip in chosen:
        out = lib / "fsd50k" / f"{clip['fname']}.wav"
        if not out.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            src = originals / f"{clip['fname']}.wav"
            ffmpeg.run(["-i", str(src), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out)])
        seconds = ffmpeg.duration(out)
        if not MIN_S <= seconds <= MAX_S:
            continue
        label_words = [w.lower() for lab in clip["labels"] for w in re.split(r"[_()]+", lab) if w]
        tags = sorted({*label_words, *(t.lower() for t in clip["tags"][:20])})[:30]
        title = " ".join(clip["title"].split())[:120]
        labels = ", ".join(lab.replace("_", " ") for lab in clip["labels"])
        sounds.append(
            {
                "id": f"fsd50k_{clip['fname']}",
                "file": str(out.relative_to(lib)),
                "source": "fsd50k",
                "pack": "FSD50K (eval, CC0 clips)",
                "license": "CC0-1.0",
                "url": f"https://freesound.org/s/{clip['fname']}/",
                "original_name": title[:200],
                "description": f"{labels}. {title}"[:500],
                "tags": [t[:40] for t in tags],
                "duration_s": round(seconds, 3),
                "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            }
        )
    return sounds


def main() -> int:
    lib = load_config().path("paths", "sfx_library")
    downloads = lib / "_downloads"
    sounds, skipped, ids = [], {"excluded": 0, "too short or long": 0}, set()
    for source, pack, page, urls in SOURCES:
        folder = downloads / source / slug(pack)
        delay = 10.0 if "opengameart.org" in page else 1.0
        for url in urls:
            name = Path(urllib.request.url2pathname(url.split("/")[-1])).name
            if download(url, folder / name, delay):
                print(f"downloaded {source}/{name}", flush=True)
        for original in originals(folder):
            rel = original.relative_to(folder)
            if EXCLUDE.search(str(rel)):
                skipped["excluded"] += 1
                continue
            if PREVIEW.search(rel.name):
                skipped["previews"] = skipped.get("previews", 0) + 1
                continue
            out = lib / source / slug(pack) / f"{slug(str(rel.with_suffix('')))}.wav"
            if not out.is_file():
                out.parent.mkdir(parents=True, exist_ok=True)
                ffmpeg.run(
                    ["-i", str(original), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
                )
            seconds = ffmpeg.duration(out)
            if not MIN_S <= seconds <= MAX_S:
                skipped["too short or long"] += 1
                continue
            base = f"{source}_{slug(pack)}_{slug(original.stem)}"[:76]
            sound_id, n = base, 1
            while sound_id in ids:
                n += 1
                sound_id = f"{base}_{n}"
            ids.add(sound_id)
            tags = sorted(set(words(original)) - {"wav", "ogg"})
            sounds.append(
                {
                    "id": sound_id,
                    "file": str(out.relative_to(lib)),
                    "source": source,
                    "pack": pack,
                    "license": "CC0-1.0",
                    "url": page,
                    "original_name": str(rel),
                    "description": f"{pack}: {' '.join(words(original))}",
                    "tags": tags,
                    "duration_s": round(seconds, 3),
                    "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                }
            )
    sounds += fsd50k_sounds(lib)
    # the same audio in two packs: keep the first
    seen, unique = set(), []
    for s in sounds:
        if s["sha256"] not in seen:
            seen.add(s["sha256"])
            unique.append(s)
    manifest = {"schema_version": 1, "sounds": unique}
    issues = validate("sfx_library", manifest)
    if issues:
        sys.exit("manifest invalid: " + "; ".join(map(str, issues[:5])))
    (lib / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    by_source: dict[str, int] = {}
    for s in unique:
        by_source[s["source"]] = by_source.get(s["source"], 0) + 1
    minutes = sum(s["duration_s"] for s in unique) / 60
    print(
        f"{len(unique)} sounds ({minutes:.1f} min) from {by_source}; "
        f"skipped {skipped}, {len(sounds) - len(unique)} duplicates → {lib / 'manifest.json'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
