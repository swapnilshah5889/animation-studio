"""Task 4B.7: the Step 4B review reel. Videos of the cast, as built with the defaults and with
every 4B option on, plus a contact sheet per character.

    uv run scripts/review_reel.py                      # all five, 1080p (hours on the CPU)
    uv run scripts/review_reel.py --only kit --quality preview     # 640x360, minutes
    uv run scripts/review_reel.py --sweep              # also the pose sweep of both variants

Per character (films/step4-cast/characters/<id>):
  A  <id>-default.mp4      the character as built with the current defaults (no bending, no hands,
                           no secondary bones), rendered from the real folder (linked, read only)
  B  <id>-4b-options.mp4   a scratch copy rebuilt with sam=False, three_quarter="klein",
                           bendable=True, secondary=True (saved redraws reused), then add_hands,
                           rendered with bending on
  <id>-compare.mp4         default left, options right, for the motions where bending matters
  <id>-sheet.png           labelled key frames of every beat: the file to open first
Each video is two shots (front view, then three-quarter view) of short beats on the meadow:
idle + blink, the 11 expressions, wave, nod, head_tilt, point, talk_gesture, jump, shrug, bow,
look_around, clap, laugh, think, sneak, walk_cycle, and in B the four hand poses. Captions are
burned in with Pillow (this ffmpeg has no drawtext). In the front view the walk marches in place:
the character moves across the frame but its feet face the camera, so it is a march, not a stroll.

Outputs go to renders/review-reel/ (git-ignored), scratch films to films/review-reel/ (also
ignored). Safe to re-run: every render is redone from the character folders.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from studio_core.config import REPO_ROOT, load_config
from studio_core.face import EXPRESSIONS
from studio_core.rig import load_rig
from studio_core.shot import render_shot
from studio_core.shot_spec import (
    FilmFolder,
    add_action,
    add_expression,
    add_hand,
    create_shot,
    move_character,
    place_character,
    register_rig,
)
from studio_core.sif.render import encode_mp4

FPS = 24
CAST = REPO_ROOT / "films" / "step4-cast"
WORK = REPO_ROOT / "films" / "review-reel"
OUT = REPO_ROOT / "renders" / "review-reel"
MEADOW = REPO_ROOT / "films" / "step4-demo" / "backgrounds" / "meadow"
IDS = ("kit", "bo", "bird", "child", "robot")
VIEWS = ("front", "three_quarter")
SHOT_IDS = {"front": "s01_sh01", "three_quarter": "s01_sh02"}
BLANK_SHOT = "s00_sh01"
DEFECT_KINDS = ("hole", "seam", "detached")
HAND_POSES = ("fist", "point", "open", "wave")
COMPARE = ("wave", "point", "clap", "think", "jump", "walk_cycle")
# Seconds each motion runs by itself (measured on Kit); a beat adds PAD so the next starts calm.
NATURAL = {
    "wave": 2.5, "nod": 0.75, "head_tilt": 1.6, "point": 2.1, "talk_gesture": 1.5, "jump": 1.1,
    "shrug": 1.3, "bow": 1.6, "look_around": 1.7, "clap": 1.9, "laugh": 1.4, "think": 2.6,
    "sneak": 2.4,
}  # fmt: skip
PAD = 0.5
EXPRESSION_S = 1.3
HAND_S = 1.5
WALK_S = 3.5
IDLE_S = 2.5


@dataclass(frozen=True)
class Beat:
    """One short beat of a reel: what is shown for `duration_s` from `start_s`."""

    label: str
    kind: str  # idle | expression | motion | walk | hand
    name: str  # the expression, motion or hand pose
    start_s: float
    duration_s: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


def plan_beats(*, hands: bool) -> list[Beat]:
    """The beats of one view, back to back from 0 s. The hand beats come last, so every other
    beat starts at the same time in the default and the options video."""
    items: list[tuple[str, str, str, float]] = [("idle breathe + blink", "idle", "idle", IDLE_S)]
    items += [(f"expression: {e}", "expression", e, EXPRESSION_S) for e in EXPRESSIONS]
    for motion in NATURAL:
        items.append((motion, "motion", motion, NATURAL[motion] + PAD))
    items.append(("walk_cycle across the frame", "walk", "walk_cycle", WALK_S))
    items.append(("walk_step across the frame", "walk", "walk_step", WALK_S))
    if hands:
        items += [(f"hand: {p}", "hand", p, HAND_S) for p in HAND_POSES]
    beats, t = [], 0.0
    for label, kind, name, length in items:
        beats.append(Beat(label, kind, name, round(t, 3), length))
        t += length
    return beats


def caption_text(character: str, variant: str, view: str, beat: Beat) -> str:
    where = "front" if view == "front" else "three-quarter"
    note = " (marches in place)" if beat.kind == "walk" and view == "front" else ""
    return f"{character} | {variant} | {where} | {beat.label}{note}"


def beat_at(beats: list[Beat], t: float) -> Beat:
    """The beat showing at time t (the last one for any time past the end)."""
    for b in beats:
        if t < b.end_s - 1e-9:
            return b
    return beats[-1]


def key_time(beat: Beat) -> float:
    """The moment of a beat that shows it best: well into the motion, before it settles."""
    if beat.kind == "walk":
        return beat.start_s + beat.duration_s * 0.4
    return beat.start_s + 0.2 + min(beat.duration_s - PAD, 1.4) * 0.55


# ----------------------------------------------------------------------------- the films


FILM_DIR = {"default": "default", "4b-options": "options"}


def film_for(variant: str) -> FilmFolder:
    root = WORK / FILM_DIR[variant]
    (root / "characters").mkdir(parents=True, exist_ok=True)
    if not (root / "backgrounds" / "meadow").exists():
        (root / "backgrounds").mkdir(exist_ok=True)
        (root / "backgrounds" / "meadow").symlink_to(MEADOW, target_is_directory=True)
    return FilmFolder(root)


def link_default(cid: str) -> FilmFolder:
    film = film_for("default")
    link = film.root / "characters" / cid
    if link.is_symlink() or link.exists():
        link.unlink() if link.is_symlink() else shutil.rmtree(link)
    link.symlink_to((CAST / "characters" / cid).resolve(), target_is_directory=True)
    return film


def rebuild_options(cid: str, log=print) -> FilmFolder:
    """A scratch copy of the character, rebuilt with the 4B options and given hands."""
    from studio_core.hands import add_hands
    from studio_core.puppet.build import build_puppet

    film = film_for("4b-options")
    dest = film.root / "characters" / cid
    if dest.is_symlink() or dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(CAST / "characters" / cid, dest, symlinks=True)
    t0 = time.monotonic()
    build_puppet(film.root, cid, sam=False, three_quarter="klein", bendable=True, secondary=True)
    rig = load_rig(film.rig_file(cid))
    register_rig(film, cid, add_hands(rig))
    log(f"  rebuilt {cid} with bendable, secondary and hands in {time.monotonic() - t0:.0f} s")
    return film


def build_spec(film: FilmFolder, shot_id: str, cid: str, view: str, beats: list[Beat]) -> None:
    """Write the shot: the character stays put except in the walk beat, each beat starts from a
    neutral face, and hand beats show the pose on both hands, then rest."""
    duration = beats[-1].end_s
    create_shot(film, shot_id, duration, "meadow", replace=True)
    place_character(film, shot_id, cid, [0.5, 0.92], view=view)
    add_action(film, shot_id, cid, "idle_breathe", 0.0)
    add_action(film, shot_id, cid, "blink", 0.0)
    for b in beats:
        face = b.name if b.kind == "expression" else "neutral"
        add_expression(film, shot_id, cid, face, b.start_s)
        if b.kind == "motion":
            add_action(film, shot_id, cid, b.name, b.start_s + 0.2)
        elif b.kind == "walk":
            add_action(film, shot_id, cid, b.name, b.start_s, duration_s=b.duration_s)
            move_character(film, shot_id, cid, [0.2, 0.92], b.start_s, 0.01)
            move_character(film, shot_id, cid, [0.8, 0.92], b.start_s + 0.01, b.duration_s - 0.5)
        elif b.kind == "hand":
            for side in ("left", "right"):
                add_hand(film, shot_id, cid, b.name, b.start_s, side)
                add_hand(film, shot_id, cid, "rest", b.end_s - 0.05, side)


# ----------------------------------------------------------------------------- frames


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def burn(frame: Image.Image, text: str) -> Image.Image:
    """The frame with a caption on a dark strip along the bottom."""
    img = frame.convert("RGB")
    h = max(18, img.height // 24)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, img.height - h * 1.7, img.width, img.height], fill=(0, 0, 0, 170))
    draw.text((h * 0.6, img.height - h * 1.45), text, fill=(255, 255, 255), font=_font(h))
    return img


def frame_path(folder: Path, index: int) -> Path:
    return folder / f"frame.{index:04d}.png"


def render_view(
    film: FilmFolder,
    cid: str,
    variant: str,
    view: str,
    beats: list[Beat],
    *,
    size: tuple[int, int] | None,
    bend: bool,
    out: Path,
) -> dict:
    """Render one shot and burn the captions into a frames folder under `out`. Returns the
    frame folder (clean, for key frames) and the captioned one (for the video)."""
    shot_id = SHOT_IDS[view]
    build_spec(film, shot_id, cid, view, beats)
    t0 = time.monotonic()
    shot = render_shot(film.root, shot_id, size=size, audio=False, bend=bend, keep_frames=True)
    seconds = time.monotonic() - t0
    clean = shot.frames[0].parent
    capped = out / f"{view}-captioned"
    shutil.rmtree(capped, ignore_errors=True)
    capped.mkdir(parents=True)
    for i, path in enumerate(sorted(shot.frames)):
        beat = beat_at(beats, i / FPS)
        burn(Image.open(path), caption_text(cid, variant, view, beat)).save(frame_path(capped, i))
    return {"clean": clean, "captioned": capped, "seconds": seconds, "n": len(shot.frames)}


def encode_concat(parts: list[Path], mp4: Path) -> None:
    """One video from several caption folders, frames renumbered in order."""
    cfg = load_config()
    joined = mp4.parent / f".{mp4.stem}-frames"
    shutil.rmtree(joined, ignore_errors=True)
    joined.mkdir(parents=True)
    n = 0
    for folder in parts:
        for p in sorted(folder.glob("frame*.png")):
            p.replace(frame_path(joined, n))
            n += 1
    encode_mp4(joined, mp4, FPS, cfg=cfg)
    shutil.rmtree(joined)


def character_box(frames: list[Path], blank: Path, margin: int = 40) -> tuple[int, int, int, int]:
    """The union bounding box of what differs from the empty meadow, in the given frames."""
    ref = np.asarray(Image.open(blank).convert("RGB"), dtype=np.int16)
    x0, y0, x1, y1 = ref.shape[1], ref.shape[0], 0, 0
    for p in frames:
        diff = np.abs(np.asarray(Image.open(p).convert("RGB"), dtype=np.int16) - ref).sum(2) > 60
        ys, xs = np.nonzero(diff)
        if len(xs):
            x0, y0 = min(x0, xs.min()), min(y0, ys.min())
            x1, y1 = max(x1, xs.max()), max(y1, ys.max())
    w, h = ref.shape[1], ref.shape[0]
    if x1 <= x0 or y1 <= y0:
        return 0, 0, w, h
    left, top = max(0, x0 - margin), max(0, y0 - margin)
    right, bottom = min(w, x1 + margin), min(h, y1 + margin)
    # even sides: H.264 (yuv420p) cannot encode an odd width or height
    return int(left), int(top), int(right - (right - left) % 2), int(bottom - (bottom - top) % 2)


def contact_sheet(
    cid: str,
    entries: list[tuple[str, Path]],
    blank: Path,
    path: Path,
    cols: int = 6,
    cell_w: int = 300,
) -> Path:
    """Key frames of every beat, labelled, cropped to the area the character uses."""
    box = character_box([p for _, p in entries], blank)
    crop_w, crop_h = box[2] - box[0], box[3] - box[1]
    cell_h = round(cell_w * crop_h / crop_w)
    lab = 22
    rows = -(-len(entries) // cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + lab)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = _font(13)
    for i, (label, p) in enumerate(entries):
        x, y = (i % cols) * cell_w, (i // cols) * (cell_h + lab)
        thumb = Image.open(p).convert("RGB").crop(box).resize((cell_w, cell_h), Image.LANCZOS)
        sheet.paste(thumb, (x, y + lab))
        draw.text((x + 4, y + 4), label, fill=(0, 0, 0), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path


def compare_video(
    cid: str,
    beats: list[Beat],
    left: Path,
    right: Path,
    blank: Path,
    mp4: Path,
    view: str,
) -> None:
    """Default left, options right, for the beats where bending matters (clean frames)."""
    keep = [b for b in beats if b.name in COMPARE]
    box = character_box([frame_path(left, round(key_time(b) * FPS)) for b in keep], blank)
    folder = mp4.parent / f".{mp4.stem}-frames"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    n = 0
    for b in keep:
        for f in range(round(b.start_s * FPS), round(b.end_s * FPS)):
            pair = []
            for src, name in ((left, "default"), (right, "4b options")):
                img = Image.open(frame_path(src, f)).convert("RGB").crop(box)
                pair.append(burn(img, f"{cid} | {name} | {view} | {b.label}"))
            both = Image.new("RGB", (pair[0].width * 2, pair[0].height))
            both.paste(pair[0], (0, 0))
            both.paste(pair[1], (pair[0].width, 0))
            both.save(frame_path(folder, n))
            n += 1
    encode_mp4(folder, mp4, FPS)
    shutil.rmtree(folder)


# ----------------------------------------------------------------------------- one character


@dataclass
class Result:
    character: str
    files: dict[str, Path] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


def blank_frame(film: FilmFolder, size: tuple[int, int] | None, out: Path) -> Path:
    """The empty meadow at the first frame, for finding where the character is."""
    create_shot(film, BLANK_SHOT, 0.5, "meadow", replace=True)
    shot = render_shot(film.root, BLANK_SHOT, size=size, audio=False, keep_frames=True)
    keep = out / "blank.png"
    shutil.copy2(shot.frames[0], keep)
    return keep


def do_character(cid: str, quality: str, log=print) -> Result:
    res = Result(cid)
    size = (640, 360) if quality == "preview" else None
    out = OUT / f"work-{cid}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    variants = {"default": (link_default, False), "4b-options": (rebuild_options, True)}
    clean: dict[tuple[str, str], Path] = {}
    captioned: dict[str, list[Path]] = {"default": [], "4b-options": []}
    beats = {"default": plan_beats(hands=False), "4b-options": plan_beats(hands=True)}
    blank = None
    t_char = time.monotonic()
    for variant, (prepare, bend) in variants.items():
        try:
            film = prepare(cid)
        except Exception as e:
            res.failures.append(f"{variant}: could not prepare ({type(e).__name__}: {e})")
            continue
        if blank is None:
            blank = blank_frame(film, size, out)
        for view in VIEWS:
            try:
                r = render_view(
                    film, cid, variant, view, beats[variant], size=size, bend=bend,
                    out=out / variant,
                )  # fmt: skip
            except Exception as e:
                res.failures.append(f"{variant}/{view}: {type(e).__name__}: {e}")
                continue
            clean[(variant, view)] = r["clean"]
            captioned[variant].append(r["captioned"])
            res.seconds[f"{variant}/{view}"] = r["seconds"]
            log(f"  {cid} {variant} {view}: {r['n']} frames in {r['seconds']:.0f} s")
    sheet_entries: list[tuple[str, Path]] = []
    for variant, tag in (("4b-options", "options"), ("default", "default")):
        if (variant, "front") in clean and (variant, "three_quarter") in clean:
            for view in VIEWS:
                for b in beats[variant]:
                    p = frame_path(clean[(variant, view)], round(key_time(b) * FPS))
                    short = "front" if view == "front" else "3/4"
                    sheet_entries.append((f"{tag} {short}: {b.label}", p))
            break
    for variant, mp4_name in (("default", "default"), ("4b-options", "4b-options")):
        parts = captioned[variant]
        if len(parts) == len(VIEWS):
            mp4 = OUT / f"{cid}-{mp4_name}.mp4"
            encode_concat(parts, mp4)
            res.files[mp4_name] = mp4
    if blank is not None and sheet_entries:
        res.files["sheet"] = contact_sheet(cid, sheet_entries, blank, OUT / f"{cid}-sheet.png")
    if blank is not None and all(
        ("default", v) in clean and ("4b-options", v) in clean for v in VIEWS
    ):
        mp4 = OUT / f"{cid}-compare.mp4"
        try:
            compare_video(
                cid, beats["default"], clean[("default", "front")],
                clean[("4b-options", "front")], blank, mp4, "front",
            )  # fmt: skip
            res.files["compare"] = mp4
        except Exception as e:
            res.failures.append(f"compare: {type(e).__name__}: {e}")
    res.seconds["total"] = time.monotonic() - t_char
    shutil.rmtree(out, ignore_errors=True)
    for variant in variants:
        for view in VIEWS:
            shutil.rmtree(
                WORK / FILM_DIR[variant] / "shots" / SHOT_IDS[view] / "frames", ignore_errors=True
            )
    return res


# ----------------------------------------------------------------------------- sweep and index


def run_sweep(cid: str, variant: str) -> int | None:
    """Defect count of the pose sweep on one variant's scratch film; None if it did not run."""
    film = WORK / FILM_DIR[variant]
    out = OUT / f"sweep-{variant}"
    cmd = ["uv", "run", str(REPO_ROOT / "scripts" / "pose_sweep.py"), "--film", str(film),
           "--only", cid, "--out", str(out / cid)]  # fmt: skip
    report = out / cid / "report.json"
    if not report.is_file():
        subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    if not report.is_file():
        return None
    data = json.loads(report.read_text())
    return sum(n[k] for c in data["characters"] for n in c["counts"].values() for k in DEFECT_KINDS)


def save_times(results: list[Result]) -> None:
    path = OUT / "times.json"
    times = json.loads(path.read_text()) if path.is_file() else {}
    times.update({r.character: r.seconds for r in results})
    path.write_text(json.dumps(times, indent=1))


def existing_result(cid: str) -> Result:
    """A Result for a character rendered earlier: the files on disk and the saved times."""
    res = Result(cid)
    for key in ("default", "4b-options", "compare", "sheet"):
        path = OUT / f"{cid}-{key}.{'png' if key == 'sheet' else 'mp4'}"
        if path.is_file():
            res.files[key] = path
        else:
            res.failures.append(f"{key} missing")
    times = OUT / "times.json"
    if times.is_file():
        res.seconds = json.loads(times.read_text()).get(cid, {})
    return res


def write_index(
    results: list[Result], sweeps: dict[str, dict[str, int | None]], quality: str
) -> Path:
    lines = ["# Step 4B review reel", "", f"Quality: {quality}. Open the sheets first.", ""]
    beats = plan_beats(hands=True)
    lines += ["## Beats (each view, in order)", ""]
    lines += [f"- {b.start_s:6.1f} s  {b.label}" for b in beats]
    lines += ["", "Hand beats are in the options video only. Front-view walk marches in place.", ""]
    notes = OUT / "notes.md"
    if notes.is_file():  # the owner's review notes, kept by hand
        lines += ["## Owner notes", "", notes.read_text().strip(), ""]
    for r in results:
        lines += [f"## {r.character}", ""]
        for key, path in r.files.items():
            lines.append(f"- {key}: {path}")
        if r.seconds:
            total = r.seconds.get("total") or r.seconds.get("render_only", 0)
            parts = ", ".join(
                f"{k} {v:.0f} s" for k, v in r.seconds.items() if k not in ("total", "render_only")
            )
            lines.append(f"- render time: {total:.0f} s ({parts})")
        if r.character in sweeps:
            s = sweeps[r.character]
            lines.append(
                f"- pose sweep defects: default {s.get('default')}, options {s.get('options')}"
            )
        lines += [f"- FAILED: {f}" for f in r.failures]
        lines.append("")
    path = OUT / "index.md"
    path.write_text("\n".join(lines))
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", action="append", choices=IDS, help="a character id (repeatable)")
    ap.add_argument("--quality", choices=("preview", "final"), default="final")
    ap.add_argument("--sweep", action="store_true", help="also run the pose sweep on both variants")
    ap.add_argument(
        "--index-only",
        action="store_true",
        help="no rendering: rebuild index.md from the files and times.json",
    )
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results, sweeps = [], {}
    t0 = time.monotonic()
    for cid in args.only or IDS:
        print(f"== {cid}", flush=True)
        if args.index_only:
            results.append(existing_result(cid))
        else:
            results.append(do_character(cid, args.quality, print))
            save_times(results)
    if args.sweep:
        for r in results:
            sweeps[r.character] = {
                "default": run_sweep(r.character, "default"),
                "options": run_sweep(r.character, "4b-options"),
            }
    index = write_index(results, sweeps, args.quality)
    print(f"{time.monotonic() - t0:.0f} s; index {index}")
    failed = [f for r in results for f in r.failures]
    for f in failed:
        print("FAILED", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
