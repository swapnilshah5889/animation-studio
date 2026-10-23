"""A built puppet waving, blinking and talking next to Pip (owner checkpoint 3, task 4.4).

    result = preview_puppet(film, "kit")                     # outputs stay in the shot folder
    result = preview_puppet(film, "kit", view="three_quarter", out=Path("renders/kit-3q"))

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

`view="three_quarter"` runs the same staging with the puppet placed in its three-quarter view
(refused if its rig has none). The three-quarter art faces screen-right (D-048), so the puppet,
standing left of Pip, is placed `facing: right`, which is the art as drawn, and looks toward Pip.
The wave, the scale match and the face close-up all use that view's own rig: its bones, its part
sizes and its `face` block. Pip stays in his front view.

Talking takes the real path: `speak` (Kokoro in envs/kokoro, then Rhubarb) in the character's
voice.json. A character with no voice yet is refused, unless `cast_placeholder` is set (the
command line sets it): then the placeholder from casting page c13 (`af_bella`, +1.5 semitones,
5% faster) is written to characters/<id>/voice.json, the only file written in the character's
folder, so recast it at voice casting.

The character, its view, its voice, the background and the line are checked before anything is
written. Then only what's missing is set up: Pip (the placeholder puppet, via `register_rig`)
and the background, when it is the meadow fixture.

Outputs: the shot stays in the film (shots/s00_sh01/: shot.json, scene.sif to open in Synfig
Studio, shot.mp4), with contact_sheet.png next to it. With `out`, the MP4 is copied to
out/puppet_preview.mp4 and the sheet is written to out/contact_sheet.png instead. The contact
sheet shows four key frames (rest, wave peak, eyes closed, mouth open), each with a close-up of
the puppet's face. The rendered frames are deleted.

To try it without a generated puppet, register the placeholder under the character's id in a
scratch film first (`shot_spec.register_rig(film, "kit")`).
"""

from __future__ import annotations

import json
import math
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from studio_core.audio.voices import VoiceError, check_text, save_voice, speak
from studio_core.config import REPO_ROOT, StudioConfig, load_config
from studio_core.motions import MotionContext, animate, sample
from studio_core.preview import PreviewError
from studio_core.preview.common import (
    REFERENCE,
    Box,
    Log,
    font,
    matched_scale,
    quiet,
    rest_box,
)
from studio_core.rig import Rig, ground_offset_px, load_rig
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
LINE = "Hi Pip! Do you want to play in the meadow?"
SUBJECT_AT, PIP_AT = (0.36, 0.92), (0.66, 0.92)  # feet, as fractions of the frame
VIEWS = ("front", "three_quarter")  # rig.schema.json view names
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


def voice_file(film: FilmFolder, character_id: str) -> Path:
    return film.root / "characters" / character_id / "voice.json"


def ensure_background(film: FilmFolder, background: str, log: Log = quiet) -> None:
    """Copy the meadow fixture in if the film lacks it; any other missing background is refused."""
    if background in film.backgrounds():
        return
    if background != FIXTURE_BACKGROUND.name:
        raise SpecError(f"no background {background!r}; backgrounds: {film.backgrounds()}")
    shutil.copytree(FIXTURE_BACKGROUND, film.root / "backgrounds" / background)
    log(f"added the placeholder background {background}")


def ensure_voice(film: FilmFolder, character_id: str, log: Log = quiet) -> str:
    """The character's voice ids, casting the placeholder only if it has none."""
    path = voice_file(film, character_id)
    if not path.is_file():
        save_voice(film.root, character_id, PLACEHOLDER_VOICE)
        log(f"{character_id} had no voice: cast the placeholder af_bella (c13) in {path.name}")
    voice = json.loads(path.read_text())
    return ", ".join(v["id"] for v in voice.get("voices", [])) or voice.get("speaker", "?")


# --------------------------------------------------------------------------- outputs


def contact_sheet(
    frame_files: list[Path], keys: list[tuple[str, int]], face: Box, out: Path
) -> Path:
    """A 2x2 grid: per key frame, the frame and a square close-up of the face (`face` in design
    px, y down), under a label."""
    thumb_w, thumb_h, close, label_h, gap = 960, 540, 540, 44, 12
    cell_w, cell_h = thumb_w + close, label_h + thumb_h
    sheet = Image.new("RGB", (2 * cell_w + gap, 2 * cell_h + gap), (250, 250, 247))
    draw, label_font = ImageDraw.Draw(sheet), font(26)
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
        draw.text((x + 12, y + 8), text, font=label_font, fill=(40, 40, 60))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


# --------------------------------------------------------------------------- the preview


@dataclass(frozen=True)
class PuppetPreview:
    """What preview_puppet made and measured."""

    shot_id: str
    video: Path  # shots/<shot>/shot.mp4, or out/puppet_preview.mp4
    contact_sheet: Path  # shots/<shot>/contact_sheet.png, or out/contact_sheet.png
    shot_dir: Path  # shot.json, scene.sif (opens in Synfig Studio), shot.mp4
    view: str
    facing: str  # "left" / "right"
    scale: float
    duration_s: float
    line_id: str
    line_cached: bool  # the take already existed (same text, same voice)
    voice: str  # the voice's ids, e.g. "af_bella"
    key_frames: list[tuple[str, int]]  # (label, frame index), as on the contact sheet
    warnings: list[str]  # shot_spec.check's warnings about the finished shot
    seconds: float  # wall time of the whole preview


def preview_puppet(
    film: FilmFolder,
    character_id: str,
    *,
    view: str = "front",
    background: str = "meadow",
    line: str = LINE,
    scale: float | None = None,
    size: tuple[int, int] | None = None,
    out: Path | None = None,
    cast_placeholder: bool = False,
    cfg: StudioConfig | None = None,
    log: Log | None = None,
) -> PuppetPreview:
    """Stage, render and summarise the puppet test shot (see the module docstring).

    `scale` defaults to Pip's standing height; `size` renders smaller than 1920x1080 (e.g.
    (640, 360)). Refusals raise PreviewError, or the SpecError, RigError or VoiceError of the
    step that refused; the character, its view, its voice, the background and the line are all
    checked before anything is written."""
    say = log or quiet
    t0 = time.monotonic()
    cfg = cfg or load_config()
    cid = character_id
    if cid == REFERENCE:
        raise PreviewError("Pip is the reference puppet; preview another character")
    if view not in VIEWS:
        raise PreviewError(f"no view {view!r}; views: {', '.join(VIEWS)}")
    if cid not in film.characters():
        raise PreviewError(
            f"{cid} has no rig at {film.rig_file(cid)}; build the puppet first "
            f"(characters: {', '.join(film.characters()) or 'none'})"
        )
    rig_view = pick_view(load_rig(film.rig_file(cid)), view)
    if "face" not in rig_view:
        raise PreviewError(f"{cid}'s {view} view has no face block: it can't blink or talk")
    facing = facing_toward(SUBJECT_AT, PIP_AT)
    arm = wave_side(rig_view, arm_toward(facing))
    if not cast_placeholder and not voice_file(film, cid).is_file():
        raise PreviewError(
            f"{cid} has no voice yet; cast one first (audio_mcp set_voice), then preview again"
        )
    if background not in film.backgrounds() and background != FIXTURE_BACKGROUND.name:
        raise SpecError(f"no background {background!r}; backgrounds: {film.backgrounds()}")
    problems = check_text(line)  # speak checks it too, but only after the setup below
    if problems:
        raise VoiceError(f"the line can't be spoken: {'; '.join(problems)}")

    if REFERENCE not in film.characters():
        register_rig(film, REFERENCE)
        say("added Pip (the placeholder puppet)")
    ensure_background(film, background, say)
    pip_view = load_rig(film.rig_file(REFERENCE)).view("front")
    scale = scale if scale is not None else matched_scale(rig_view, pip_view)

    voice = ensure_voice(film, cid, say)
    spoken = speak(film.root, cid, [{"text": line}], cfg=cfg)[0]
    if spoken.cues is None:
        raise PreviewError(f"line {spoken.line_id} has no mouth cues")
    say(f"line {spoken.line_id} ({voice}, {spoken.duration_s:.2f} s, cached: {spoken.cached})")

    tl = Timeline()
    duration = tl.duration(spoken.duration_s)
    subject, pip = plan_actions(tl, spoken.duration_s, arm)
    # Every edit checks and saves the whole spec, like the director's tool calls.
    create_shot(film, SHOT, duration, background, replace=True)
    place_character(film, SHOT, cid, list(SUBJECT_AT), view=view, scale=scale, facing=facing)
    place_character(film, SHOT, REFERENCE, list(PIP_AT), view="front")
    for who, actions in ((cid, subject), (REFERENCE, pip)):
        add_expression(film, SHOT, who, "happy", 0.0)
        for a in actions:
            add_action(film, SHOT, who, a["motion"], a["start_s"], params=a.get("params"))
    add_dialogue(film, SHOT, cid, spoken.line_id, tl.talk_s)
    warnings = check(film, load(film, SHOT))[1]  # warnings about the finished shot only
    for w in warnings:
        say(f"warning: {w}")
    say(
        f"shot {SHOT}: {duration} s; {cid} ({view} view, facing {facing}) at scale {scale}, "
        "Pip at 1"
    )

    width, height = size or (DESIGN.width, DESIGN.height)
    say(f"rendering {SHOT} at {width}x{height} ...")
    rendered = render_shot(film.root, SHOT, size=size, cfg=cfg)
    try:
        keys = key_frames(rig_view, subject, load_cues(spoken.cues), tl, len(rendered.frames))
        face = screen_box(rig_view, SUBJECT_AT, scale, part=rig_view["face"]["part"], facing=facing)
        folder = out if out is not None else rendered.sif.parent
        sheet = contact_sheet(rendered.frames, keys, face, folder / "contact_sheet.png")
        video = rendered.mp4
        if out is not None:
            video = out / "puppet_preview.mp4"
            shutil.copy2(rendered.mp4, video)
    finally:
        if rendered.frames:
            shutil.rmtree(rendered.frames[0].parent, ignore_errors=True)
    return PuppetPreview(
        shot_id=SHOT,
        video=video,
        contact_sheet=sheet,
        shot_dir=rendered.sif.parent,
        view=view,
        facing=facing,
        scale=scale,
        duration_s=duration,
        line_id=spoken.line_id,
        line_cached=spoken.cached,
        voice=voice,
        key_frames=keys,
        warnings=warnings,
        seconds=time.monotonic() - t0,
    )
