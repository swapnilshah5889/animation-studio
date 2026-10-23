"""Owner checkpoint 4 (Step 4, task 4.7): a generated place, split into layers, during a slow pan.

    uv run scripts/preview_background.py                         # the meadow, a 6 s pan right
    uv run scripts/preview_background.py --character kit        # with Kit standing on the ground
    uv run scripts/preview_background.py --background lake --move slow_pan_left --seconds 8
    uv run scripts/preview_background.py --move pull_out --zoom 0.8   # zooming out shows the edges

A background is a folder films/<film>/backgrounds/<id>/ with layers.json (schemas/
background.schema.json): layers far to near, every PNG the same size (e.g. 2880x1080, the frame
plus room to pan), each with a `parallax` factor. This script stages one test shot with it and
the camera move, renders it through the Synfig backend (studio_core.shot.render_shot, the path
synfig_mcp uses), and checks that the move never shows a hole. Exit status 0 = no hole.

The shot is s00_sh02 (scene 00 sits outside the story's numbering, so it never collides with a
real shot, nor with preview_puppet's s00_sh01). It is replaced on every run. The camera move
runs over the whole shot, so a shot of `--seconds` is also the move's length. With `--character`
the puppet stands on the ground plane (parallax 1) at the bottom centre, scaled to Pip's
standing height like every puppet, blinking and breathing: it shows the scale of the place and
that the ground layer slides with it.

The hole check (two independent checks; both must pass):

1. Pixels. A hole is a pixel that no layer covers: in the Synfig scene the only thing behind the
   layers is the backdrop rectangle. The backdrop colour is not a safe marker as it is (art,
   sky gradients especially, can contain exactly that colour; the meadow fixture does), so the
   render uses a **probe copy** of the background: backgrounds/<id>_probe/ holds copies of the
   layer PNGs and a layers.json whose backdrop is a pure sentinel colour (magenta #ff00ff, or
   the first of a few others that no layer's art comes close to). Then any sentinel-coloured
   pixel in a frame is a hole, whatever the art looks like, and holes show up magenta in the MP4
   and the contact sheet. Sentinels use only 0 and 255 per channel, so no colour transform in
   the renderer can move them. Every 4th frame (`--every`), the key frames and the last frame
   are counted; a pixel within `--tolerance` per channel of the sentinel counts. The probe folder
   is deleted afterwards and the shot is pointed back at the real background (scene.sif is
   rebuilt), so the film is left as it was, plus the shot.
2. Geometry. A layer plane shifts by -pan * parallax and the camera zooms about the frame centre
   (studio_core.scene), so at every frame the layer's image covers x in
   (+-W/2 -+ pan*parallax) * zoom and y in (+-H/2) * zoom. An *edge entering the frame* is an
   image edge inside the 1920x1080 view. The pan and zoom come from `camera_tracks`, sampled at
   every frame. An edge only matters where the art is visible along it, so an edge whose pixel
   row or column is fully transparent (e.g. a foreground layer that is empty at its sides) is a
   note, not a failure. This also catches a nearer layer whose cut-off edge slides into view
   while a farther layer still covers the hole behind it, which the pixel check can't see.

Outputs (renders/ is git-ignored; every run overwrites them; `--out` picks another folder):
    renders/background-preview/<film>-<background>/background_preview.mp4
    renders/background-preview/<film>-<background>/contact_sheet.png
The contact sheet shows the frames at the start, 1/4, 1/2, 3/4 and the end of the move, each with
its pan offset and hole count, and a panel with the layers' spare room (how much further a pan
could go before that layer's edge shows). The shot stays in the film (shots/s00_sh02/: shot.json,
scene.sif to open in Synfig Studio, shot.mp4). Its frames are deleted.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from preview_puppet import ensure_film, matched_scale, probe

from studio_core.config import REPO_ROOT, load_config
from studio_core.motions import Key, sample
from studio_core.rig import RigError, load_rig
from studio_core.scene import (
    CAMERA_MOVES,
    DESIGN,
    Background,
    SceneError,
    camera_tracks,
    load_background,
)
from studio_core.shot import build_shot, load_shot, render_shot, shot_dir
from studio_core.shot_spec import (
    FPS,
    PLACEHOLDER_RIG,
    FilmFolder,
    SpecError,
    add_action,
    add_expression,
    check,
    create_shot,
    load,
    place_character,
    set_background,
    set_camera,
)
from studio_core.sif import Animated

SHOT = "s00_sh02"
STAND_AT = (0.5, 0.92)  # the puppet's feet, as fractions of the frame
REFERENCE = "pip"  # the placeholder puppet every puppet is scaled to
# Pure 0/255 colours: no gamma or colour-space step can change them. The first one that the art
# stays clear of becomes the probe backdrop.
SENTINELS = ("#ff00ff", "#00ff00", "#ffff00", "#00ffff", "#ff0000", "#0000ff")
PIXEL_TOL = (
    6  # per channel, when matching the sentinel in a frame (and keeping the art clear of it)
)
ALPHA_VISIBLE = 8  # of 255: art with less alpha than this doesn't count as drawn
EDGE_EPS_PX = 0.5  # an edge this far inside the frame (design px) is "entering"
SIDES = ("left", "right", "top", "bottom")

Colour = tuple[int, int, int]
Box = tuple[int, int, int, int]


# --------------------------------------------------------------------------- the art (pure-ish)


def hex_rgb(value: str) -> Colour:
    h = value.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


@dataclass(frozen=True)
class LayerArt:
    """What the checks need to know about one layer's PNG."""

    name: str
    parallax: float
    size_px: tuple[int, int]
    visible_edges: dict[str, bool]  # side -> is any art visible along that edge row/column?
    clashes: frozenset[str]  # candidate sentinels this layer's art comes close to


def near_colour(rgb: np.ndarray, colour: Colour, tol: int) -> np.ndarray:
    """Which pixels of an (..., 3) uint8 array are within `tol` per channel of `colour`."""
    diff = np.abs(rgb.astype(np.int16) - np.array(colour, dtype=np.int16))
    return diff.max(axis=-1) <= tol


def inspect_layer(
    layer: dict[str, Any],
    folder: Path,
    size_px: tuple[int, int],
    candidates: tuple[str, ...] = SENTINELS,
    tol: int = PIXEL_TOL,
) -> LayerArt:
    """Read one layer image: refuse a size that is not the background's, find where its art
    touches the image edges, and which candidate sentinel colours its art comes within `tol` of."""
    path = folder / layer["file"]
    rgba = np.asarray(Image.open(path).convert("RGBA"))
    if (rgba.shape[1], rgba.shape[0]) != tuple(size_px):
        raise SceneError(
            f"layer {layer['name']!r} is {rgba.shape[1]}x{rgba.shape[0]} px ({layer['file']}) but "
            f"layers.json says every layer is {size_px[0]}x{size_px[1]}"
        )
    drawn = rgba[..., 3] >= ALPHA_VISIBLE
    edges = {
        "left": bool(drawn[:, 0].any()),
        "right": bool(drawn[:, -1].any()),
        "top": bool(drawn[0, :].any()),
        "bottom": bool(drawn[-1, :].any()),
    }
    art = rgba[..., :3][drawn]
    clashes = frozenset(c for c in candidates if near_colour(art, hex_rgb(c), tol).any())
    return LayerArt(layer["name"], float(layer["parallax"]), tuple(size_px), edges, clashes)  # type: ignore[arg-type]


def pick_sentinel(arts: list[LayerArt], candidates: tuple[str, ...] = SENTINELS) -> str | None:
    """The first candidate colour that no layer's art comes close to, or None."""
    taken = set().union(*(a.clashes for a in arts)) if arts else set()
    return next((c for c in candidates if c not in taken), None)


def probe_id(background_id: str) -> str:
    """The probe copy's id: still a valid background id (at most 40 characters)."""
    return f"{background_id[:33]}_probe"


def make_probe(background: Background, sentinel: str) -> Path:
    """backgrounds/<id>_probe next to the real background: copies of its layer PNGs and a
    layers.json whose backdrop is the sentinel. Returns the folder."""
    src = background.folder.resolve()
    dst = src.parent / probe_id(background.id)
    shutil.rmtree(dst, ignore_errors=True)
    data = {**background.data, "id": probe_id(background.id), "backdrop": sentinel}
    for layer in data["layers"]:
        source, target = (src / layer["file"]).resolve(), (dst / layer["file"]).resolve()
        if not source.is_relative_to(src) or not target.is_relative_to(dst.resolve()):
            raise SceneError(f"layer file {layer['file']!r} leaves the background folder")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (dst / "layers.json").write_text(json.dumps(data, indent=2) + "\n")
    return dst


# --------------------------------------------------------------------------- the camera (pure)


def camera_poses(
    camera: dict[str, Any] | None, fps: int, n_frames: int
) -> list[tuple[float, float]]:
    """(pan px, zoom) at every frame: the same tracks the scene is built from, sampled the way
    Synfig eases them (studio_core.motions.sample). Pan is in design px, + = camera right."""
    tracks = camera_tracks(camera, fps, n_frames)

    def values(track: Animated | float | None, default: float) -> list[float]:
        if track is None:
            return [default] * n_frames
        if not isinstance(track, Animated):
            return [float(track)] * n_frames
        keys = [Key(w.frame, w.value, w.interp) for w in track.waypoints]  # type: ignore[arg-type]
        return [float(sample(keys, f)) for f in range(n_frames)]  # type: ignore[arg-type]

    return list(zip(values(tracks.pan, 0.0), values(tracks.zoom, 1.0), strict=True))


def edge_slack(
    size_px: tuple[int, int], parallax: float, pan: float, zoom: float
) -> dict[str, float]:
    """How far each image edge lies outside the frame, in design px (negative = inside it).

    The layer's image is centred on the frame at rest and shifts left by pan * parallax; the
    camera scales everything about the frame centre by `zoom`, so the frame sees
    +-(960, 540) / zoom of the layer's own plane."""
    w, h = size_px
    half_w, half_h = DESIGN.width / 2 / zoom, DESIGN.height / 2 / zoom
    return {
        "left": w / 2 + pan * parallax - half_w,
        "right": w / 2 - pan * parallax - half_w,
        "top": h / 2 - half_h,
        "bottom": h / 2 - half_h,
    }


@dataclass(frozen=True)
class EdgeEntry:
    layer: str
    side: str
    first_frame: int  # the first frame in which the edge is inside the view
    worst_px: float  # how far inside, at the worst frame (design px)
    drawn: bool  # is there art along that edge? If not, the entry is harmless


def edge_entries(arts: list[LayerArt], poses: list[tuple[float, float]]) -> list[EdgeEntry]:
    """Every layer edge that enters the frame at some point of the move."""
    found = []
    for art in arts:
        slacks = [edge_slack(art.size_px, art.parallax, pan, zoom) for pan, zoom in poses]
        for side in SIDES:
            inside = [i for i, s in enumerate(slacks) if s[side] < -EDGE_EPS_PX]
            if inside:
                worst = -min(s[side] for s in slacks)
                found.append(EdgeEntry(art.name, side, inside[0], worst, art.visible_edges[side]))
    return found


def spare_px(art: LayerArt, poses: list[tuple[float, float]]) -> float:
    """The sideways room a layer has left at the move's tightest point, in design px: how much
    further the camera could pan before the edge of the image shows. Negative: it already shows.
    (Top and bottom are exact fits at 1080 px tall and only matter when zooming out; the edge
    check reports those.)"""
    return min(
        min(slack["left"], slack["right"])
        for slack in (edge_slack(art.size_px, art.parallax, pan, zoom) for pan, zoom in poses)
    )


# --------------------------------------------------------------------------- the holes (pure)


@dataclass(frozen=True)
class Hole:
    frame: int
    pixels: int  # sentinel-coloured pixels in the frame
    box: Box  # (left, top, right, bottom) of all of them, in the rendered frame's pixels


def find_hole(rgb: np.ndarray, sentinel: Colour, tol: int, frame: int = 0) -> Hole | None:
    """The sentinel-coloured pixels of one (h, w, 3) frame, or None if there are none."""
    mask = near_colour(rgb, sentinel, tol)
    count = int(mask.sum())
    if count == 0:
        return None
    ys, xs = np.nonzero(mask)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return Hole(frame, count, box)


def key_indices(n_frames: int) -> list[int]:
    """The frames at the start, 1/4, 1/2, 3/4 and the end of the move (the whole shot)."""
    return [round(i * (n_frames - 1) / 4) for i in range(5)]


def sample_indices(n_frames: int, every: int) -> list[int]:
    """The frames the hole check reads: every `every`-th, the key frames, and the last frame."""
    if every < 1:
        raise ValueError("every must be at least 1")
    return sorted({*range(0, n_frames, every), *key_indices(n_frames), n_frames - 1})


def find_holes(frame_files: list[Path], indices: list[int], sentinel: str, tol: int) -> list[Hole]:
    colour = hex_rgb(sentinel)
    holes = []
    for i in indices:
        with Image.open(frame_files[i]) as img:
            hole = find_hole(np.asarray(img.convert("RGB")), colour, tol, i)
        if hole:
            holes.append(hole)
    return holes


# --------------------------------------------------------------------------- the report


@dataclass(frozen=True)
class Report:
    sampled: int
    holes: list[Hole]
    edges: list[EdgeEntry]

    @property
    def failed(self) -> bool:
        return bool(self.holes) or any(e.drawn for e in self.edges)


def summary_lines(report: Report) -> list[str]:
    """The verdicts, one per line: 'FAIL ...', 'note ...' or 'ok   ...'."""
    lines = []
    if report.holes:
        first = report.holes[0]
        worst = max(report.holes, key=lambda h: h.pixels)
        lines.append(
            f"FAIL holes in {len(report.holes)} of {report.sampled} sampled frames; first at "
            f"frame {first.frame}, worst at frame {worst.frame}: {worst.pixels} px, box {worst.box}"
        )
    else:
        lines.append(f"ok   no hole in {report.sampled} sampled frames")
    shown = [e for e in report.edges if e.drawn]
    for e in shown:
        lines.append(
            f"FAIL layer {e.layer!r}: its {e.side} edge enters the frame at frame "
            f"{e.first_frame}, up to {e.worst_px:.0f} px"
        )
    if not shown:
        lines.append("ok   no layer edge with art on it enters the frame")
    for e in report.edges:
        if not e.drawn:
            lines.append(
                f"note layer {e.layer!r}: its {e.side} edge enters the frame (frame "
                f"{e.first_frame}, {e.worst_px:.0f} px) but is transparent there"
            )
    return lines


def layer_table(arts: list[LayerArt], poses: list[tuple[float, float]]) -> list[str]:
    """One line per layer, far to near: parallax and the spare room at the tightest point."""
    rows = [f"{'layer':<14}{'parallax':>9}{'spare px':>10}"]
    for art in arts:
        rows.append(f"{art.name:<14}{art.parallax:>9.2f}{spare_px(art, poses):>10.0f}")
    return rows


# --------------------------------------------------------------------------- outputs


def _font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = (
        "/System/Library/Fonts/Menlo.ttc"
        if mono
        else "/System/Library/Fonts/Supplemental/Arial.ttf"
    )
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def contact_sheet(
    frame_files: list[Path],
    keys: list[int],
    poses: list[tuple[float, float]],
    holes: list[Hole],
    table: list[str],
    verdicts: list[str],
    out: Path,
) -> Path:
    """A 2x3 grid: the five key frames, each under a label with its pan offset and hole count,
    then a panel with the layers' spare room and the verdicts."""
    thumb_w, thumb_h, label_h, gap = 960, 540, 44, 12
    cell_h = label_h + thumb_h
    sheet = Image.new("RGB", (2 * thumb_w + gap, 3 * cell_h + 2 * gap), (250, 250, 247))
    draw, font = ImageDraw.Draw(sheet), _font(26)
    by_frame = {h.frame: h for h in holes}
    for i, frame in enumerate(keys):
        x, y = (i % 2) * (thumb_w + gap), (i // 2) * (cell_h + gap)
        with Image.open(frame_files[frame]) as img:
            sheet.paste(
                img.convert("RGB").resize((thumb_w, thumb_h), Image.LANCZOS), (x, y + label_h)
            )
        pan, zoom = poses[frame]
        hole = by_frame.get(frame)
        state = f"HOLE {hole.pixels} px" if hole else "no hole"
        text = (
            f"{i + 1}  {frame / FPS:.2f} s (frame {frame})   "
            f"pan {pan:+.0f} px  zoom {zoom:.2f}  {state}"
        )
        draw.text((x + 12, y + 8), text, font=font, fill=(190, 30, 30) if hole else (40, 40, 60))
    px, py = 1 * (thumb_w + gap), 2 * (cell_h + gap)  # the sixth cell
    mono = _font(23, mono=True)
    lines: list[tuple[str, tuple[int, int, int]]] = [(row, (40, 40, 60)) for row in table]
    for verdict in ["", *verdicts]:
        fill = (190, 30, 30) if verdict.startswith("FAIL") else (40, 40, 60)
        wrapped = textwrap.wrap(verdict, 64, subsequent_indent="     ") or [""]
        lines.extend((row, fill) for row in wrapped)
    for n, (line, fill) in enumerate(lines):
        draw.text((px + 12, py + label_h + n * 32), line, font=mono, fill=fill)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


# --------------------------------------------------------------------------- staging


def stage_shot(
    film: FilmFolder,
    background_id: str,
    args: argparse.Namespace,
    character: tuple[dict[str, Any], float] | None,
) -> None:
    """Write shots/s00_sh02/shot.json through the director's edit functions (each one checks and
    saves the whole spec)."""
    create_shot(film, SHOT, args.seconds, background_id, replace=True)
    set_camera(film, SHOT, args.move, zoom=args.zoom)
    if character is None:
        return
    view, scale = character
    place_character(film, SHOT, args.character, list(STAND_AT), scale=scale)
    add_expression(film, SHOT, args.character, "happy", 0.0)
    add_action(film, SHOT, args.character, "idle_breathe", 0.0)
    if "face" in view:  # a rig without a face can't blink
        add_action(film, SHOT, args.character, "blink", 0.0)


def plan_character(film: FilmFolder, cid: str, scale: float | None) -> tuple[dict[str, Any], float]:
    """The puppet's front view and its scale (Pip's standing height unless `scale` is given)."""
    if not film.rig_file(cid).is_file():
        sys.exit(
            f"{cid} has no rig at {film.rig_file(cid)}; build the puppet first "
            f"(characters: {', '.join(film.characters()) or 'none'})"
        )
    view = load_rig(film.rig_file(cid)).view("front")
    pip = load_rig(PLACEHOLDER_RIG / "rig.json").view("front")
    return view, scale or matched_scale(view, pip)


def restore_background(film: FilmFolder, background_id: str, probe_dir: Path) -> None:
    """Point the shot back at the real background, rebuild its scene.sif, drop the probe copy."""
    try:
        if film.shot_file(SHOT).is_file():
            set_background(film, SHOT, background_id)
            built = build_shot(film.root, load_shot(film.root, SHOT))
            built.canvas.save(shot_dir(film.root, SHOT) / "scene.sif")
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--film", default="step4-demo")
    ap.add_argument("--background", default="meadow", help="a background of the film")
    ap.add_argument("--character", help="a character of the film, standing on the ground")
    ap.add_argument("--scale", type=float, help="the character's scale (default: Pip's height)")
    ap.add_argument("--move", choices=CAMERA_MOVES, default="slow_pan_right")
    ap.add_argument("--zoom", type=float, help="the camera's starting zoom (0.5-3, default 1)")
    ap.add_argument("--seconds", type=float, default=6.0, help="shot (= camera move) length")
    ap.add_argument("--every", type=int, default=4, help="hole-check every Nth frame")
    ap.add_argument("--tolerance", type=int, default=PIXEL_TOL, help="sentinel match, per channel")
    ap.add_argument("--size", help="render size WxH (default: 1920x1080)")
    ap.add_argument("--out", type=Path, help="output folder (default: renders/background-preview/)")
    args = ap.parse_args()
    size = tuple(int(v) for v in args.size.split("x")) if args.size else None
    out = args.out or (
        REPO_ROOT / "renders" / "background-preview" / f"{args.film}-{args.background}"
    )
    cfg = load_config()
    t0 = time.monotonic()

    try:
        film = ensure_film(cfg.path("paths", "films"), args.film)
        if not film.background_file(args.background).is_file():
            sys.exit(f"no background {args.background!r}; backgrounds: {film.backgrounds()}")
        background = load_background(film.background_file(args.background))
        w_px, h_px = background.data["size_px"]
        arts = [
            inspect_layer(lay, background.folder, (w_px, h_px), tol=args.tolerance)
            for lay in background.data["layers"]
        ]
        sentinel = pick_sentinel(arts)
        if sentinel is None:
            sys.exit("every sentinel colour appears in the art; add one to SENTINELS")
        character = plan_character(film, args.character, args.scale) if args.character else None

        probe_dir = make_probe(background, sentinel)
        try:
            stage_shot(film, probe_id(background.id), args, character)
            for w in check(film, load(film, SHOT))[1]:
                print(f"warning: {w}")
            rendered = render_shot(film.root, SHOT, size=size, audio=False, cfg=cfg)  # type: ignore[arg-type]
        finally:
            restore_background(film, background.id, probe_dir)
    except (SpecError, SceneError, RigError) as e:
        sys.exit(f"refused: {e}")
    render_s = time.monotonic() - t0
    n_frames = len(rendered.frames)

    spec = load(film, SHOT)
    poses = camera_poses(spec.get("camera"), FPS, n_frames)
    keys = key_indices(n_frames)
    indices = sample_indices(n_frames, args.every)
    holes = find_holes(rendered.frames, indices, sentinel, args.tolerance)
    report = Report(len(indices), holes, edge_entries(arts, poses))
    verdicts, table = summary_lines(report), layer_table(arts, poses)

    sheet = contact_sheet(
        rendered.frames, keys, poses, holes, table, verdicts, out / "contact_sheet.png"
    )
    mp4 = out / "background_preview.mp4"
    shutil.copy2(rendered.mp4, mp4)
    shutil.rmtree(rendered.frames[0].parent)
    who = f" with {args.character} (scale {character[1]})" if character else ""
    print(
        f"shot {SHOT}: {args.background}{who}, {args.move}, {args.seconds} s, {w_px}x{h_px} layers"
    )
    print(
        f"hole check: probe backdrop {sentinel} (the real one is {background.data.get('backdrop')})"
    )
    print(*table, sep="\n")
    print(*verdicts, sep="\n")
    print(
        f"rendered and checked in {time.monotonic() - t0:.0f} s "
        f"({render_s:.0f} s to render): {probe(mp4, cfg)}"
    )
    print(f"video: {mp4}")
    print(f"contact sheet: {sheet}")
    print(f"shot: {rendered.sif.parent}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
