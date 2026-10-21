# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10"]
# ///
"""Spike: generate a working OpenToonz scene (.tnz) from scratch, then render it headless.

    uv run scripts/spikes/opentoonz_scene.py                       # write project + scene only
    uv run scripts/spikes/opentoonz_scene.py --render              # + tcomposer PNGs + ffmpeg MP4
    uv run scripts/spikes/opentoonz_scene.py --render --frames 24  # quick partial render

What it builds (a 4 s, 24 fps, 1920x1080 meadow shot):
  * an OpenToonz *project* folder (``<out>/<name>_otprj.xml`` + ``scenes/scenes.xml``), so
    tcomposer resolves the project from the scene path instead of falling back to the sandbox;
  * flat placeholder art as PNG levels in ``<out>/inputs`` (sky, hills, ground, bushes, a
    balloon, and a 4-drawing walk cycle for "Pip" as a PNG sequence ``pip.0001.png``..);
  * ``<out>/scenes/meadow_multiplane.tnz`` with 6 level columns, two pegbars (Peg2 is a child
    of Peg1), keyframed move/rotate/scale channels with ease and linear interpolation, and a
    multiplane camera: each layer sits at its own Z depth (``noScaleZ`` keeps its on-screen size),
    so a camera pan produces parallax; the camera also animates Z and scale at the end.

The XML layout mirrors what OpenToonz 1.8 itself writes (checked against a scene saved by the
app via ToonzScript). See docs/spikes/opentoonz.md for the format notes.
Safe to re-run: everything under --out is regenerated.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

DPI = 120  # OpenToonz "standard dpi": 16 x 9 inch camera at 1920 x 1080 => 1 px = 1/120 inch
FPS = 24
FRAMES = 96
SS = 3  # supersampling for smooth edges

TCOMPOSER = Path.home() / "Applications/OpenToonz.app/Contents/MacOS/tcomposer"
# OpenToonz "stuff" folder (config, profiles, fx presets), unpacked from the .pkg's
# Scripts/stuff.tar.bz2. The installer would put it in /Applications/OpenToonz/OpenToonz_stuff
# (needs admin); we pass it to tcomposer with -TOONZROOT instead.
STUFF = Path.home() / "ai-studio/tools/opentoonz-stuff"
DEFAULT_OUT = Path.home() / "ai-studio/scratch/opentoonz-spike/gen"


# --------------------------------------------------------------------------------------------
# Placeholder art (no AI): flat shapes, drawn SS x larger and downsampled.
# --------------------------------------------------------------------------------------------


def canvas(w: int, h: int, fill=(0, 0, 0, 0)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (w * SS, h * SS), fill)
    return img, ImageDraw.Draw(img)


def finish(img: Image.Image) -> Image.Image:
    return img.resize((img.width // SS, img.height // SS), Image.Resampling.LANCZOS)


def s(*v: float) -> list[float]:
    return [x * SS for x in v]


LINE = (70, 52, 46, 255)


def draw_sky(w: int, h: int) -> Image.Image:
    img, d = canvas(w, h)
    top, bottom = (120, 182, 238), (205, 232, 250)
    for y in range(h * SS):
        t = y / (h * SS)
        d.line(
            [(0, y), (w * SS, y)],
            fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)),
        )
    d.ellipse(s(w * 0.62, 120, w * 0.62 + 170, 290), fill=(255, 224, 120, 255))
    for cx, cy, k in [(0.12, 230, 1.0), (0.35, 150, 0.8), (0.55, 330, 1.2), (0.82, 200, 0.9)]:
        x, y = w * cx, cy
        for dx, dy, r in [(0, 0, 70), (60, -25, 60), (120, 0, 65), (60, 20, 70)]:
            r *= k
            d.ellipse(
                s(x + dx * k - r, y + dy - r * 0.7, x + dx * k + r, y + dy + r * 0.7),
                fill=(255, 255, 255, 235),
            )
    return finish(img)


def draw_hills(w: int, h: int) -> Image.Image:
    img, d = canvas(w, h)
    for cx, top, rx, col in [
        (0.10, 560, 900, (120, 186, 110)),
        (0.38, 600, 1100, (104, 172, 98)),
        (0.68, 540, 1000, (120, 186, 110)),
        (0.95, 590, 900, (104, 172, 98)),
    ]:
        x = w * cx
        d.ellipse(s(x - rx, top, x + rx, top + 1400), fill=(*col, 255))
    d.rectangle(s(0, 800, w, h), fill=(98, 160, 92, 255))
    return finish(img)


def draw_ground(w: int, h: int) -> Image.Image:
    """Z=0 plane: the strip Pip walks on, so his feet don't skate against the scenery."""
    img, d = canvas(w, h)
    d.rectangle(s(0, 120, w, h), fill=(134, 196, 100, 255))
    d.rectangle(s(0, 200, w, 290), fill=(222, 196, 150, 255))  # path
    for i in range(0, w, 260):
        x = i + 80 * math.sin(i)
        d.ellipse(s(x, 150, x + 26, 176), fill=(255, 255, 255, 255))
        d.ellipse(s(x + 8, 158, x + 18, 168), fill=(250, 210, 80, 255))
        d.ellipse(s(x + 120, 330, x + 170, 350), fill=(160, 150, 140, 255))
    return finish(img)


def draw_bushes(w: int, h: int) -> Image.Image:
    img, d = canvas(w, h)
    for x in range(0, w, 700):
        for dx, r in [(0, 150), (130, 190), (280, 140)]:
            d.ellipse(
                s(x + dx - r, h - r * 1.1, x + dx + r, h + r),
                fill=(58, 128, 70, 255),
                outline=(40, 96, 52, 255),
                width=4 * SS,
            )
    return finish(img)


def draw_balloon(w: int, h: int) -> Image.Image:
    img, d = canvas(w, h)
    d.line(s(w / 2, 170, w / 2 + 6, h - 2), fill=LINE, width=3 * SS)
    d.ellipse(s(10, 10, w - 10, 190), fill=(232, 76, 84, 255), outline=LINE, width=4 * SS)
    d.ellipse(s(35, 40, 60, 80), fill=(255, 190, 190, 255))
    d.polygon(s(w / 2 - 10, 196, w / 2 + 10, 196, w / 2, 182), fill=(232, 76, 84, 255))
    return finish(img)


def draw_pip(frame: int, w: int = 300, h: int = 400) -> Image.Image:
    """4-drawing walk cycle: feet swap, body bobs; frame 3 blinks."""
    img, d = canvas(w, h)
    fur, shade, pink = (246, 240, 232, 255), (226, 214, 202, 255), (244, 176, 180, 255)
    bob = [0, -10, 0, -10][frame]
    feet = [(-50, 30), (-20, -10), (30, -50), (-10, 20)][frame]
    for fx, lift in [(w / 2 - 55 + feet[0] * 0.5, 0), (w / 2 + 55 + feet[1] * 0.5, 0)]:
        d.ellipse(
            s(fx - 38, h - 44 - lift, fx + 38, h - 4 - lift), fill=shade, outline=LINE, width=3 * SS
        )
    body_top = 150 + bob
    d.ellipse(s(40, body_top, w - 40, h - 30 + bob), fill=fur, outline=LINE, width=4 * SS)
    for ex in (w / 2 - 50, w / 2 + 50):  # ears
        d.ellipse(
            s(ex - 28, 10 + bob, ex + 28, body_top + 40), fill=fur, outline=LINE, width=4 * SS
        )
        d.ellipse(s(ex - 13, 30 + bob, ex + 13, body_top + 20), fill=pink)
    d.ellipse(s(40, body_top, w - 40, h - 30 + bob), fill=fur, outline=LINE, width=4 * SS)
    eye_y = body_top + 75
    for ex in (w / 2 - 40, w / 2 + 40):
        if frame == 2:
            d.line(s(ex - 12, eye_y, ex + 12, eye_y), fill=LINE, width=4 * SS)
        else:
            d.ellipse(s(ex - 11, eye_y - 15, ex + 11, eye_y + 15), fill=LINE)
        d.ellipse(s(ex - 26, eye_y + 22, ex - 2, eye_y + 36), fill=pink)
    d.arc(s(w / 2 - 18, eye_y + 15, w / 2 + 18, eye_y + 42), 20, 160, fill=LINE, width=3 * SS)
    return finish(img)


def make_assets(inputs: Path) -> dict[str, tuple[int, int]]:
    """Write every level image; returns {file name: (w, h)} for the report."""
    inputs.mkdir(parents=True, exist_ok=True)
    out: dict[str, Image.Image] = {
        "sky.0001.png": draw_sky(3600, 1500),
        "hills.0001.png": draw_hills(3600, 1150),
        "ground.0001.png": draw_ground(3840, 420),
        "bushes.0001.png": draw_bushes(4800, 420),
        "balloon.0001.png": draw_balloon(140, 420),
    }
    for i in range(4):
        out[f"pip.{i + 1:04d}.png"] = draw_pip(i)
    for name, img in out.items():
        img.save(inputs / name)
    return {k: v.size for k, v in out.items()}


# --------------------------------------------------------------------------------------------
# .tnz model: just enough of the format to express levels, columns, pegbars, keyframes, camera.
# --------------------------------------------------------------------------------------------


@dataclass
class Key:
    """One keyframe. ``frame`` is 0-based (xsheet row 1 == frame 0).

    ``interp`` is the interpolation of the segment that *starts* at this key (OpenToonz stores it
    on the left key): "L" linear, "C" constant, "Ep" ease-in/out in percent of the segment.
    ``ease`` = (ease_in %, ease_out %) used by "Ep" segments touching this key.
    """

    frame: int
    value: float
    interp: str = "Ep"
    ease: tuple[float, float] = (33.0, 33.0)


def channel(tag: str, keys: list[Key] | None = None, default: float = 0.0) -> str:
    if not keys:
        return f"<{tag}><default>{default:g}</default></{tag}>"
    parts = []
    prev: Key | None = None
    for k in sorted(keys, key=lambda k: k.frame):
        body = ""
        if prev is not None:  # <prev> describes the incoming segment, typed by the previous key
            if prev.interp == "Ep":
                body += f"<prev>{k.value:g} {-k.ease[0]:g}</prev>"
            elif prev.interp == "L":
                body += f"<prev>{k.value:g}</prev>"
        if k.interp == "Ep":
            body += f"{k.frame} {k.value:g} {k.ease[1]:g}"
        else:
            body += f"{k.frame} {k.value:g}"
        parts.append(f"<{k.interp}>{body}</{k.interp}>")
        prev = k
    return (
        f"<{tag}><default>{keys[0].value:g}</default>"
        f"<keyframes>{''.join(parts)}</keyframes></{tag}>"
    )


@dataclass
class StageObject:
    """A pegbar-tree node: Camera1, Table, PegN or ColN. Lengths are in inches."""

    id: str
    parent: str = "Table"
    center: tuple[float, float] = (0.0, 0.0)  # pivot, in the object's own space
    no_scale_z: float = 0.0  # compensates Z scaling so the layer keeps its drawn size
    channels: dict[str, list[Key] | float] = field(default_factory=dict)  # x y z so rot sx sy sc
    name: str = ""

    def xml(self, camera_xml: str = "") -> str:
        cx, cy = self.center
        attrs = f'id="{self.id}"' + (' activeboth="yes"' if self.id.startswith("Camera") else "")
        out = [
            f"<pegbar {attrs}>",
            f'<parent handle="B" id="{self.parent}" parentHandle="B"></parent>',
        ]
        if self.name:
            out.append(f'<name>"{self.name}"</name>')
        # center = pivot; offset (stored negated) = same amount, so moving the pivot doesn't
        # move the drawing (this is what the GUI writes when you drag the centre).
        out += [
            "<isOpened>0</isOpened>",
            f"<center>{cx:g} {cy:g} {-cx:g} {-cy:g}</center>",
            "<status>0</status>",
        ]
        if self.no_scale_z:
            out.append(f"<noScaleZ>{self.no_scale_z:g}</noScaleZ>")
        for tag in ("x", "y", "z", "so", "sx", "sy", "sc", "rot"):
            if tag in self.channels:
                v = self.channels[tag]
                out.append(channel(tag, v) if isinstance(v, list) else channel(tag, default=v))
        out.append("<nodePos>1.234e+09 5.678e+09</nodePos>")
        out.append(camera_xml)
        out.append("</pegbar>")
        return "\n".join(out)


CAMERA_XML = (
    "<camera><cameraSize>16 9</cameraSize><cameraRes>1920 1080</cameraRes>"
    "<cameraXPrevalence>1</cameraXPrevalence><interestRect>0 0 -1 -1</interestRect>"
    "</camera>"
)


@dataclass
class Column:
    level: str  # level name
    cells: list[tuple[int, int, int, int]]  # (row, count, start fid, fid increment)
    obj: StageObject
    blur: list[Key] | float | None = None  # optional STD_blurFx between column and xsheet


def build_tnz(
    levels: dict[str, str],
    columns: list[Column],
    pegbars: list[StageObject],
    camera: StageObject,
    frames: int,
    out_png: str,
) -> str:
    """Return the full .tnz XML. ``levels`` maps level name -> path (as OpenToonz writes it)."""
    ids = iter(range(1, 10_000))
    level_ids = {name: next(ids) for name in levels}

    props = f"""<properties>
<cameras><camera><cameraSize>16 9</cameraSize><cameraRes>1920 1080</cameraRes>
<cameraXPrevalence>1</cameraXPrevalence><interestRect>0 0 -1 -1</interestRect></camera></cameras>
<outputs><output name="main">
<range>0 {frames - 1}</range><step>1</step><shrink>1</shrink>
<applyShrinkToViewer>0</applyShrinkToViewer>
<fps>{FPS}</fps><path>"{out_png}"</path><bpp>32</bpp><multimedia>0</multimedia>
<threadsIndex>2</threadsIndex><maxTileSizeIndex>0</maxTileSizeIndex><subcameraPrev>0</subcameraPrev>
<stereoscopic>0 0.05</stereoscopic><resquality>1</resquality><fieldprevalence>0</fieldprevalence>
<gamma>1</gamma><timestretch>25 25</timestretch>
</output></outputs>
<bgColor>255 255 255 255</bgColor><markers>6 0</markers><subsampling>1 1</subsampling>
<fieldguide>16 1.77778</fieldguide>
</properties>"""

    lv = ["<levelSet><levels>"]
    for name, path in levels.items():
        lv.append(
            f"<level id='{level_ids[name]}'>{name} "
            f'<info dpix="{DPI}" dpiy="{DPI}"/><path>"{path}"</path></level>'
        )
    lv.append('</levels><folder name="Cast" type="default"><levels>')
    lv.append("".join(f"<level id='{i}'/>" for i in level_ids.values()))
    lv.append("</levels></folder></levelSet>")

    cols, terminal_refs, internal = ["<columns>"], [], []
    for c in columns:
        col_id, fx_id = next(ids), next(ids)
        if c.blur is None:  # column feeds the xsheet node directly
            terminal_refs.append(f"<Toonz_columnFx id='{fx_id}'/>")
        else:  # column -> blur fx -> xsheet node; the fx is defined once under <internal>
            blur_id = next(ids)
            value = (
                channel("value", c.blur)
                if isinstance(c.blur, list)
                else channel("value", default=c.blur)
            )
            internal.append(
                f"<fxnode><STD_blurFx id='{blur_id}'><params>{value}</params>"
                f"<ports><Source><Toonz_columnFx id='{fx_id}'/></Source></ports>"
                f'<numberId>{blur_id}</numberId><fxId>""</fxId><opened>0</opened>'
                f"</STD_blurFx></fxnode>"
            )
            terminal_refs.append(f"<STD_blurFx id='{blur_id}'/>")
        cells = "".join(
            f"<cell>{r} {n} <level id='{level_ids[c.level]}'/>{fid:04d} {inc}</cell>"
            for r, n, fid, inc in c.cells
        )
        cols.append(
            f"<levelColumn id='{col_id}'><status>0</status><cells>{cells}</cells>"
            f"<fx><Toonz_columnFx id='{fx_id}'><params></params><ports></ports>"
            f'<numberId>0</numberId><name>LevelColumn</name><fxId>""</fxId><opened>0</opened>'
            f"</Toonz_columnFx></fx></levelColumn>"
        )
    cols.append("</columns>")

    peg = ["<pegbars>", camera.xml(CAMERA_XML), StageObject("Table", parent="None").xml()]
    peg += [p.xml() for p in pegbars] + [c.obj.xml() for c in columns]
    peg.append("<grid_dimension>1</grid_dimension></pegbars>")

    xsh_fx, out_fx = next(ids), next(ids)
    terminal = "".join(f"<fxnode>{ref}</fxnode>" for ref in terminal_refs)
    fxnodes = (
        f"<fxnodes><internal>{''.join(internal)}</internal><terminal>{terminal}</terminal>"
        f"<xsheet><Toonz_xsheetFx id='{xsh_fx}'><params></params><ports></ports>"
        f'<numberId>0</numberId><name>Xsheet</name><fxId>""</fxId><opened>0</opened>'
        f"</Toonz_xsheetFx></xsheet>"
        f"<output><Toonz_outputFx id='{out_fx}'><params></params><ports><source>"
        f"<Toonz_xsheetFx id='{xsh_fx}'/></source></ports><numberId>0</numberId>"
        f'<name>Output</name><fxId>""</fxId><opened>0</opened></Toonz_outputFx></output>'
        f"<grid_dimension>1</grid_dimension></fxnodes>"
    )

    return "\n".join(
        [
            f'<tnz framecount="{frames}" version="71.1">',
            '<generator>"animation-studio spike"</generator>',
            props,
            *lv,
            "<xsheet>",
            *cols,
            *peg,
            fxnodes,
            "</xsheet>",
            "</tnz>",
            "",
        ]
    )


def write_project(root: Path) -> Path:
    """Minimal OpenToonz project: <root>/<name>_otprj.xml + scenes/scenes.xml pointing back."""
    name = root.name
    (root / "scenes").mkdir(parents=True, exist_ok=True)
    (root / "outputs").mkdir(exist_ok=True)
    folders = "".join(
        f'<folder name="{f}" path="{f}"/>'
        for f in ("inputs", "drawings", "scenes", "extras", "outputs", "palettes", "scripts")
    )
    (root / f"{name}_otprj.xml").write_text(
        f"<project><version>70 1</version><folders>{folders}</folders></project>\n"
    )
    (root / "scenes" / "scenes.xml").write_text(
        '<parentProject type="projectFolder">\n  ".."\n</parentProject>\n'
    )
    return root / "scenes"


# --------------------------------------------------------------------------------------------
# The shot
# --------------------------------------------------------------------------------------------


def meadow_scene(
    frames: int,
) -> tuple[dict[str, str], list[Column], list[StageObject], StageObject]:
    last = frames - 1
    hold = [(0, frames, 1, 0)]  # one drawing held for the whole shot

    # Camera: pans 8 inches right with ease-in/out; in the last second it pushes in
    # (scale < 1 = zoom in) and moves Z toward the table, which re-spaces the planes.
    camera = StageObject(
        "Camera1",
        parent="None",
        channels={
            "x": [Key(0, 0.0), Key(last, 8.0)],
            "z": [Key(0, 0.0, "L"), Key(last - 24, 0.0), Key(last, -120.0)],
            "sc": [Key(0, 1.0, "L"), Key(last - 24, 1.0), Key(last, 0.88)],
        },
    )

    # Multiplane: Z < 0 is farther from the camera (the camera's focus distance is 1000).
    # Perspective scales a layer about the camera by p = 1000 / (1000 - Z); noScaleZ == Z
    # multiplies its drawing by (1 - Z/1000) = 1/p, so it keeps its drawn size and only the
    # parallax changes: on screen it sits at p * (position - camera) + drawing.
    # So: position = screen offset / p, and x = 4 (the pan's midpoint) centres every layer.
    def layer(col: str, z: float, screen_y: float) -> StageObject:
        p = 1000.0 / (1000.0 - z)
        return StageObject(col, no_scale_z=z, channels={"z": z, "x": 4.0, "y": screen_y / p})

    sky = layer("Col1", -3000, 0.8)  # p = 0.25: scrolls at a quarter of the camera speed
    hills = layer("Col2", -1000, -0.6)  # p = 0.5
    ground = layer("Col3", 0, -3.0)  # p = 1 (Pip's floor, so his feet don't skate)
    bushes = layer("Col6", 350, -3.1)  # p ~ 1.54, foreground; also drawn last (higher Z)

    # Peg1 carries Pip across the shot (walk path with a small step bob).
    walk = StageObject(
        "Peg1",
        name="pip_walk",
        channels={
            "x": [Key(0, -5.0, ease=(0, 20)), Key(last, 10.0, ease=(20, 0))],
            "y": [
                Key(f, -1.55 + (0.12 if (f // 6) % 2 else 0.0), "L") for f in range(0, frames, 6)
            ],
        },
    )
    # Peg2 is a child of Peg1: the balloon hand. It sways (rotation) on its own.
    sway = StageObject(
        "Peg2",
        parent="Peg1",
        name="balloon_hand",
        channels={
            "x": 1.05,
            "y": -0.35,
            "rot": [
                Key(f, (-9.0 if (i % 2) else 9.0), "Ep", (50, 50))
                for i, f in enumerate(sorted({*range(0, frames, 24), last}))
            ],
        },
    )
    # Pip himself (Col4) rides Peg1; pivot at his feet. Squash/stretch on each step (sx/sy,
    # linear) plus a slow lean (rot, eased); a "pop in" global scale over the first 8 frames.
    pip = StageObject(
        "Col4",
        parent="Peg1",
        center=(0.0, -1.6667),
        channels={
            "sx": [Key(f, 1.05 if (f // 6) % 2 == 0 else 0.97, "L") for f in range(0, frames, 6)],
            "sy": [Key(f, 0.95 if (f // 6) % 2 == 0 else 1.03, "L") for f in range(0, frames, 6)],
            "rot": [Key(0, 0.0), Key(frames // 2, -6.0), Key(last, 0.0)],
            "sc": [Key(0, 0.4, ease=(0, 0)), Key(8, 1.0)],
        },
    )
    # The balloon (Col5) hangs from Peg2: string end at Peg2's origin.
    balloon = StageObject("Col5", parent="Peg2", channels={"y": 1.75})

    walk_cells = [(r, 2, (r // 2) % 4 + 1, 0) for r in range(0, frames, 2)]  # on twos
    levels = {
        n: f"+inputs/{n}..png" for n in ("sky", "hills", "ground", "pip", "balloon", "bushes")
    }
    columns = [
        Column("sky", hold, sky, blur=4.0),  # atmospheric softening of the far planes
        Column("hills", hold, hills, blur=1.5),
        Column("ground", hold, ground),
        Column("pip", walk_cells, pip),
        Column("balloon", hold, balloon),
        # rack focus: the foreground goes soft during the final push-in (animated fx param)
        Column(
            "bushes", hold, bushes, blur=[Key(0, 0.0, "L"), Key(last - 24, 0.0), Key(last, 6.0)]
        ),
    ]
    return levels, columns, [walk, sway], camera


# --------------------------------------------------------------------------------------------


def render(scene: Path, out_dir: Path, frames: int, threads: str) -> float:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    cmd = [
        str(TCOMPOSER),
        str(scene),
        "-o",
        str(out_dir / "frame.png"),
        "-range",
        "1",
        str(frames),
        "-nthreads",
        threads,
        "-TOONZROOT",
        str(STUFF),
    ]
    print("$", " ".join(cmd))
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    tail = [ln for ln in proc.stdout.splitlines() if ln.strip() and "computed" not in ln]
    print("\n".join(tail[-6:]))
    made = sorted(out_dir.glob("frame.*.png"))
    print(
        f"tcomposer exit={proc.returncode}, {len(made)} frames, {elapsed:.2f} s wall, "
        f"{elapsed / max(len(made), 1):.3f} s/frame"
    )
    if proc.returncode != 0 or len(made) != frames:
        print(proc.stderr[-2000:], file=sys.stderr)
        raise SystemExit("render failed")
    return elapsed


def encode(frames_dir: Path, mp4: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-framerate",
        str(FPS),
        "-i",
        str(frames_dir / "frame.%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "18",
        str(mp4),
    ]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="project folder to (re)create")
    ap.add_argument("--frames", type=int, default=FRAMES)
    ap.add_argument("--render", action="store_true", help="render with tcomposer + ffmpeg")
    ap.add_argument("--threads", default="all", help="tcomposer -nthreads (single/half/all/N)")
    args = ap.parse_args()

    root: Path = args.out.expanduser().resolve()
    if root.exists():
        shutil.rmtree(root)
    scenes = write_project(root)
    sizes = make_assets(root / "inputs")
    levels, columns, pegbars, camera = meadow_scene(args.frames)
    tnz = scenes / "meadow_multiplane.tnz"
    tnz.write_text(build_tnz(levels, columns, pegbars, camera, args.frames, "+outputs/meadow.png"))
    print(f"wrote {tnz} ({tnz.stat().st_size} bytes), {len(sizes)} level images")

    if args.render:
        frames_dir = root / "outputs" / "frames"
        render(tnz, frames_dir, args.frames, args.threads)
        mp4 = root / "outputs" / "meadow_multiplane.mp4"
        encode(frames_dir, mp4)
        print(f"wrote {mp4} ({mp4.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
