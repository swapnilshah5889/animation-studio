"""Owner checkpoint 3 (Step 4, task 4.4): a built puppet waving, blinking and talking next to Pip.

    uv run scripts/preview_puppet.py                          # Kit in films/step4-demo
    uv run scripts/preview_puppet.py --film my-film --character fox --size 960x540
    uv run scripts/preview_puppet.py --view three_quarter     # the same shot in the 3/4 view

One short shot through the engine-neutral path that synfig_mcp uses. The shot_spec edits
(create_shot, place_character, add_action, add_expression, add_dialogue) write
shots/s00_sh01/shot.json, and the Synfig backend (studio_core.shot.render_shot) renders it.
Scene 00 sits outside the story's numbering, so this test shot never collides with a real one;
it is replaced on every run.

The timeline (`Timeline`; the shot runs 6-9 s, depending on the line):
- 0-1 s: rest. The puppet stands as drawn, with nothing moving.
- 1 s: it waves with the arm on Pip's side (two back-and-forths, about 2 s) and starts breathing.
- About 3.2 s: a blink. The blink motion starts at 2.8 s, and its first blink lands 0.4 s later.
- 3.6 s: it speaks the line, lip-synced from the line's Rhubarb cues.

Pip stands beside it, scaled to the same standing height, breathing and blinking, and nods once
the line is over.

`--view three_quarter` runs the same staging with the puppet placed in its three-quarter view
(refused if its rig has none). The three-quarter art faces screen-right (D-048), so the puppet,
standing left of Pip, is placed `facing: right`, which is the art as drawn, and looks toward Pip.
The wave, the scale match and the face close-up all use that view's own rig: its bones, its part
sizes and its `face` block. Pip stays in his front view.

Talking takes the real path: `speak` (Kokoro in envs/kokoro, then Rhubarb) in the character's
voice.json. If the character has no voice yet, the script casts a placeholder from casting page
c13 (`af_bella`, +1.5 semitones, 5% faster). It writes that to characters/<id>/voice.json, the
only file it writes in the character's folder, so recast it at voice casting.

Only what's missing is set up: the film (storybook style), Pip (the placeholder puppet, via
`register_rig`) and the background (the meadow fixture).

Outputs (renders/ is git-ignored, and every run overwrites them; the front view keeps its
folder name, other views add theirs, e.g. <film>-<character>-three_quarter):
    renders/puppet-preview/<film>-<character>/puppet_preview.mp4
    renders/puppet-preview/<film>-<character>/contact_sheet.png
The contact sheet shows four key frames (rest, wave peak, eyes closed, mouth open), each with a
close-up of the puppet's face. The shot stays in the film (shots/s00_sh01/: shot.json, scene.sif
to open in Synfig Studio, shot.mp4). Its frames are deleted.

To try the script without a generated puppet, register the placeholder under the character's id
in a scratch film first (`shot_spec.register_rig(film, "kit")`).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from studio_core.audio.voices import VoiceError, save_voice, speak
from studio_core.config import REPO_ROOT, StudioConfig, load_config
from studio_core.film import Film
from studio_core.models import load_manifest
from studio_core.motions import MotionContext, animate, sample
from studio_core.rig import Rig, RigError, ground_offset_px, load_rig, world_pose
from studio_core.scene import DESIGN
from studio_core.shot import render_shot
from studio_core.shot_spec import (
    FPS,
    FilmFolder,
    SpecError,
    add_action,
    add_dialogue,
    add_expression,
    check,
    create_shot,
    load,
    place_character,
    register_rig,
)
from studio_core.sif import frames
from studio_core.sif.lipsync import load_cues

SHOT = "s00_sh01"
REFERENCE = "pip"  # the hand-drawn placeholder puppet every generated puppet is compared with
LINE = "Hi Pip! Do you want to play in the meadow?"
SUBJECT_AT, PIP_AT = (0.36, 0.92), (0.66, 0.92)  # feet, as fractions of the frame
VIEWS = ("front", "three_quarter")  # rig.schema.json view names
STYLE = "storybook"  # only used when the film doesn't exist yet
FIXTURE_BACKGROUND = REPO_ROOT / "tests" / "fixtures" / "backgrounds" / "meadow"
# Casting page c13 (scripts/audio/voice_casting.py): heard by the owner, not given to Pip or Bunny.
PLACEHOLDER_VOICE = {
    "engine": "kokoro",
    "voices": [{"id": "af_bella", "weight": 1}],
    "speed": 1.05,
    "pitch_semitones": 1.5,
    "loudness_lufs": -20,
    "notes": "Placeholder from scripts/preview_puppet.py (casting page c13); recast at casting.",
}
OPEN_MOUTHS = ("D", "C", "E", "B")  # Rhubarb shapes, widest first (studio_core.face)
WAVE = {"energy": 0.6, "cycles": 2}

Box = tuple[float, float, float, float]


# --------------------------------------------------------------------------- the plan (pure)


@dataclass(frozen=True)
class Timeline:
    """When things happen, in seconds from the start of the shot."""

    wave_s: float = 1.0  # the rest pose holds until here
    blink_s: float = 2.8  # the blink motion's first blink lands 0.4 s after its start
    talk_s: float = 3.6
    tail_s: float = 1.2  # after the line: Pip nods, then the shot ends
    min_duration_s: float = 6.0

    def duration(self, line_s: float) -> float:
        """The shot's length: the line plus the tail, rounded up to half a second."""
        return max(self.min_duration_s, math.ceil((self.talk_s + line_s + self.tail_s) * 2) / 2)

    def nod_s(self, line_s: float) -> float:
        return round(self.talk_s + line_s + 0.2, 2)


def plan_actions(
    tl: Timeline, line_s: float, wave_side: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the puppet's actions, Pip's actions), as shot spec actions."""
    subject = [
        {"motion": "wave", "start_s": tl.wave_s, "params": {**WAVE, "side": wave_side}},
        {"motion": "idle_breathe", "start_s": tl.wave_s},
        {"motion": "blink", "start_s": tl.blink_s},
    ]
    pip = [
        {"motion": "idle_breathe", "start_s": 0.0},
        {"motion": "blink", "start_s": tl.wave_s},  # open eyes in the rest frame
        {"motion": "nod", "start_s": tl.nod_s(line_s), "params": {"energy": 0.5}},
    ]
    return subject, pip


def pick_view(rig: Rig, name: str) -> dict[str, Any]:
    """One view of the rig, or a refusal that says which views the rig has."""
    if name not in rig.data["views"]:
        have = ", ".join(sorted(rig.data["views"]))
        raise SpecError(
            f"{rig.id} has no {name} view (its views: {have}); rig that view first "
            "(Step 4, task 4.5), or preview a view it has"
        )
    return rig.view(name)


def output_name(film: str, character: str, view: str) -> str:
    """The folder under renders/puppet-preview/: the front view keeps its plain name."""
    return f"{film}-{character}" if view == "front" else f"{film}-{character}-{view}"


def facing_toward(at: tuple[float, float], other: tuple[float, float]) -> str:
    """The shot spec `facing` that turns a character at `at` toward `other`. Both views are drawn
    facing screen-right, so 'right' is the art as drawn and 'left' mirrors it (scene.py)."""
    return "right" if other[0] >= at[0] else "left"


def arm_toward(facing: str) -> str:
    """The character's own side that is on the viewer's right. In the art as drawn (front, and
    three-quarter facing screen-right) that is its left (the far side in three-quarter); mirrored,
    its right."""
    return "left" if facing == "right" else "right"


def wave_side(view: dict[str, Any], toward: str = "left") -> str:
    """The arm to wave with: `toward` Pip (the character's left = the viewer's right) if that
    side has an upper arm and a forearm, else the other side."""
    ctx = MotionContext(view=view, fps=FPS, start=0, last_frame=0)
    for side in (toward, "right" if toward == "left" else "left"):
        if ctx.has("upper_arm", side) and ctx.has("forearm", side):
            return side
    raise SpecError("the rig has no arm (upper_arm + forearm) to wave with")


def rest_box(view: dict[str, Any], part: str | None = None) -> Box:
    """(left, bottom, right, top) of the rest pose's art, or of one part of it, in art px with
    y up and the root joint at (0, 0). Parts are drawn unrotated at rest."""
    rest = world_pose(view)
    boxes = []
    for name, spec in view["parts"].items():
        if part is not None and name != part:
            continue
        joint = rest[spec["bone"]][0]
        (w, h), (px, py) = spec["size_px"], spec["pivot_px"]
        boxes.append((joint.x - px, joint.y - (h - py), joint.x - px + w, joint.y + py))
    if not boxes:
        raise ValueError(f"no part {part!r}; parts: {sorted(view['parts'])}")
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def matched_scale(view: dict[str, Any], reference: dict[str, Any], ref_scale: float = 1.0) -> float:
    """The scale that makes `view` stand as tall as `reference` at `ref_scale` (within the shot
    schema's 0.2-3)."""
    height = rest_box(view)[3] - rest_box(view)[1]
    ref_height = rest_box(reference)[3] - rest_box(reference)[1]
    return round(min(3.0, max(0.2, ref_scale * ref_height / height)), 3)


def screen_box(
    view: dict[str, Any],
    feet: tuple[float, float],
    scale: float,
    part: str | None = None,
    facing: str = "right",
) -> Box:
    """Where the rest art lands in the 1920x1080 design frame, as (left, top, right, bottom)
    pixels, y down, with the character's feet at `feet` (frame fractions). `facing` 'left'
    mirrors the art about the root joint. The same placement rule as studio_core.scene: the
    lowest art pixel sits on the feet."""
    left, bottom, right, top = rest_box(view, part)
    root_x = feet[0] * DESIGN.width
    root_y = feet[1] * DESIGN.height - ground_offset_px(view) * scale
    if facing == "left":
        left, right = -right, -left
    x0, x1 = root_x + left * scale, root_x + right * scale
    return (x0, root_y - top * scale, x1, root_y - bottom * scale)


def key_frames(
    view: dict[str, Any],
    actions: list[dict[str, Any]],
    cues: list[dict[str, Any]],
    tl: Timeline,
    n_frames: int,
) -> list[tuple[str, int]]:
    """The frames the contact sheet shows, measured from the motions themselves (the same
    `animate` call the backend makes) and from the line's mouth cues."""
    anim = animate(view, actions, fps=FPS, n_frames=n_frames)
    wave = next(c for c in anim.clips if c.motion == "wave")
    arm = [keys for (kind, _), keys in wave.channels.items() if kind == "angle"]
    peak = max(
        range(wave.start, wave.end + 1),
        key=lambda f: sum(abs(float(sample(keys, f))) for keys in arm),  # type: ignore[arg-type]
    )
    closed = [w.frame for w in (anim.eyes.waypoints if anim.eyes else ()) if w.value == "closed"]
    if not closed:
        raise ValueError("the eyes never close: the blink lands after the end of the shot")
    for shape in OPEN_MOUTHS:
        found = [c for c in cues if c["value"] == shape]
        if found:
            cue = max(found, key=lambda c: float(c["end"]) - float(c["start"]))
            mid = tl.talk_s + (float(cue["start"]) + float(cue["end"])) / 2
            mouth = (f"mouth open ({shape})", min(frames(mid, FPS), n_frames - 1))
            break
    else:
        raise ValueError("the line's cues never open the mouth")
    rest = frames(tl.wave_s / 2, FPS)
    return [("rest", rest), ("wave peak", peak), ("eyes closed", closed[0]), mouth]


# --------------------------------------------------------------------------- film setup


def ensure_film(films_root: Path, slug: str) -> FilmFolder:
    """Open the film, creating it (film.json, storybook style) only if the folder is missing."""
    root = films_root / slug
    if not root.exists():
        Film.create(root, STYLE, load_manifest())
        print(f"created film {slug} ({STYLE})")
    return FilmFolder.open(films_root, slug)


def ensure_background(film: FilmFolder, background: str) -> None:
    if film.background_file(background).is_file():
        return
    if background != FIXTURE_BACKGROUND.name:
        raise SpecError(f"no background {background!r}; backgrounds: {film.backgrounds()}")
    shutil.copytree(FIXTURE_BACKGROUND, film.root / "backgrounds" / background)
    print(f"added the placeholder background {background}")


def ensure_voice(film: FilmFolder, character: str) -> str:
    """The character's voice, casting the placeholder only if it has none."""
    path = film.root / "characters" / character / "voice.json"
    if not path.is_file():
        save_voice(film.root, character, PLACEHOLDER_VOICE)
        print(f"{character} had no voice: cast the placeholder af_bella (c13) in {path.name}")
    voice = json.loads(path.read_text())
    return ", ".join(v["id"] for v in voice.get("voices", [])) or voice.get("speaker", "?")


# --------------------------------------------------------------------------- outputs


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def contact_sheet(
    frame_files: list[Path], keys: list[tuple[str, int]], face: Box, out: Path
) -> Path:
    """A 2x2 grid: per key frame, the frame and a square close-up of the face (`face` in design
    px, y down), under a label."""
    thumb_w, thumb_h, close, label_h, gap = 960, 540, 540, 44, 12
    cell_w, cell_h = thumb_w + close, label_h + thumb_h
    sheet = Image.new("RGB", (2 * cell_w + gap, 2 * cell_h + gap), (250, 250, 247))
    draw, font = ImageDraw.Draw(sheet), _font(26)
    for i, (label, frame) in enumerate(keys):
        img = Image.open(frame_files[frame]).convert("RGB")
        k = img.width / DESIGN.width  # frames may be rendered smaller than the design size
        left, top, right, bottom = face
        side = max(right - left, bottom - top) * 1.3  # a square with some margin
        cx, cy = (left + right) / 2, (top + bottom) / 2
        half = side / 2
        crop = img.crop(tuple(round(v * k) for v in (cx - half, cy - half, cx + half, cy + half)))
        x, y = (i % 2) * (cell_w + gap), (i // 2) * (cell_h + gap)
        sheet.paste(img.resize((thumb_w, thumb_h), Image.LANCZOS), (x, y + label_h))
        sheet.paste(crop.resize((close, close), Image.LANCZOS), (x + thumb_w, y + label_h))
        text = f"{i + 1}  {label}   {frame / FPS:.2f} s (frame {frame})"
        draw.text((x + 12, y + 8), text, font=font, fill=(40, 40, 60))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def probe(mp4: Path, cfg: StudioConfig) -> str:
    result = subprocess.run(
        [str(cfg.path("tools", "ffprobe")), "-v", "error", "-show_entries",
         "stream=codec_type,width,height,nb_frames:format=duration", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    data = json.loads(result.stdout)
    streams = {s["codec_type"]: s for s in data["streams"]}
    v = streams["video"]
    seconds = float(data["format"]["duration"])
    audio = "with audio" if "audio" in streams else "no audio"
    return f"{v['width']}x{v['height']}, {v['nb_frames']} frames, {seconds:.2f} s, {audio}"


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--film", default="step4-demo")
    ap.add_argument("--character", default="kit")
    ap.add_argument(
        "--view",
        choices=VIEWS,
        default="front",
        help="the rig view to place; three_quarter faces Pip (default: front)",
    )
    ap.add_argument("--out", type=Path, help="output folder (default: renders/puppet-preview/)")
    ap.add_argument("--background", default="meadow", help="a background of the film")
    ap.add_argument("--line", default=LINE, help="what the puppet says")
    ap.add_argument("--scale", type=float, help="the puppet's scale (default: Pip's height)")
    ap.add_argument("--size", help="render size WxH (default: 1920x1080)")
    args = ap.parse_args()
    cid = args.character
    if cid == REFERENCE:
        sys.exit("Pip is the reference puppet; preview another character")
    size = tuple(int(v) for v in args.size.split("x")) if args.size else None
    folder = output_name(args.film, cid, args.view)
    out = args.out or REPO_ROOT / "renders" / "puppet-preview" / folder
    cfg = load_config()
    tl = Timeline()
    t0 = time.monotonic()

    try:
        film = ensure_film(cfg.path("paths", "films"), args.film)
        if not film.rig_file(cid).is_file():
            sys.exit(
                f"{cid} has no rig at {film.rig_file(cid)}; build the puppet first "
                f"(characters: {', '.join(film.characters()) or 'none'})"
            )
        rig = load_rig(film.rig_file(cid))
        view = pick_view(rig, args.view)  # refuse before touching the film any further
        if "face" not in view:
            sys.exit(f"{cid}'s {args.view} view has no face block: it can't blink or talk")
        if not film.rig_file(REFERENCE).is_file():
            register_rig(film, REFERENCE)
            print("added Pip (the placeholder puppet)")
        ensure_background(film, args.background)
        pip_view = load_rig(film.rig_file(REFERENCE)).view("front")
        facing = facing_toward(SUBJECT_AT, PIP_AT)
        scale = args.scale or matched_scale(view, pip_view)

        voice = ensure_voice(film, cid)
        line = speak(film.root, cid, [{"text": args.line}], cfg=cfg)[0]
        if line.cues is None:
            sys.exit(f"line {line.line_id} has no mouth cues")
        print(f"line {line.line_id} ({voice}, {line.duration_s:.2f} s, cached: {line.cached})")

        duration = tl.duration(line.duration_s)
        subject, pip = plan_actions(tl, line.duration_s, wave_side(view, arm_toward(facing)))
        # Every edit checks and saves the whole spec, like the director's tool calls.
        create_shot(film, SHOT, duration, args.background, replace=True)
        place_character(
            film, SHOT, cid, list(SUBJECT_AT), view=args.view, scale=scale, facing=facing
        )
        place_character(film, SHOT, REFERENCE, list(PIP_AT), view="front")
        for who, actions in ((cid, subject), (REFERENCE, pip)):
            add_expression(film, SHOT, who, "happy", 0.0)
            for a in actions:
                add_action(film, SHOT, who, a["motion"], a["start_s"], params=a.get("params"))
        add_dialogue(film, SHOT, cid, line.line_id, tl.talk_s)
    except (SpecError, VoiceError, RigError) as e:
        sys.exit(f"refused: {e}")
    for w in check(film, load(film, SHOT))[1]:  # warnings about the finished shot only
        print(f"warning: {w}")
    print(
        f"shot {SHOT}: {duration} s; {cid} ({args.view} view, facing {facing}) at scale {scale}, "
        "Pip at 1"
    )

    rendered = render_shot(film.root, SHOT, size=size, cfg=cfg)  # type: ignore[arg-type]
    keys = key_frames(view, subject, load_cues(line.cues), tl, len(rendered.frames))
    face = screen_box(view, SUBJECT_AT, scale, part=view["face"]["part"], facing=facing)
    sheet = contact_sheet(rendered.frames, keys, face, out / "contact_sheet.png")
    mp4 = out / "puppet_preview.mp4"
    shutil.copy2(rendered.mp4, mp4)
    shutil.rmtree(rendered.frames[0].parent)
    print(f"rendered in {time.monotonic() - t0:.0f} s: {probe(mp4, cfg)}")
    print(f"key frames: {', '.join(f'{label} {f}' for label, f in keys)}")
    print(f"video: {mp4}")
    print(f"contact sheet: {sheet}")
    print(f"shot: {rendered.sif.parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
