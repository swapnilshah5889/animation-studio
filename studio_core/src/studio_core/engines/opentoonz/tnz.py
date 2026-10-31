# ruff: noqa: E501
"""Writing OpenToonz scene (`.tnz`) XML: levels, columns, pegbars with keyframes, Plastic."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

DPI = 120
FPS = 24
TCOMPOSER = Path.home() / "Applications/OpenToonz.app/Contents/MacOS/tcomposer"
STUFF = Path.home() / "ai-studio/tools/opentoonz-stuff"
STAGE_INCH = 53.33333  # Stage units per inch (Plastic skeletons are written in these)
CAMERA_XML = (
    "<camera><cameraSize>16 9</cameraSize><cameraRes>1920 1080</cameraRes>"
    "<cameraXPrevalence>1</cameraXPrevalence><interestRect>0 0 -1 -1</interestRect></camera>"
)


def linear_channel(tag: str, values: list[float]) -> str:
    """One linear keyframe per frame (frame 0 = xsheet row 1)."""
    if not values:
        return f"<{tag}><default>0</default></{tag}>"
    parts, prev = [], None
    for f, v in enumerate(values):
        body = f"<prev>{v:.6g}</prev>" if prev is not None else ""
        parts.append(f"<L>{body}{f} {v:.6g}</L>")
        prev = v
    return (
        f"<{tag}><default>{values[0]:.6g}</default><keyframes>{''.join(parts)}</keyframes></{tag}>"
    )


def const_channel(tag: str, v: float) -> str:
    return f"<{tag}><default>{v:.6g}</default></{tag}>"


@dataclass
class Peg:
    id: str
    parent: str = "Table"
    center: tuple[float, float] = (0.0, 0.0)  # pivot, inches, in the drawing's own space
    channels: dict[str, list[float] | float] = field(default_factory=dict)
    plastic: str = ""
    camera: str = ""

    def xml(self) -> str:
        cx, cy = self.center
        act = ' activeboth="yes"' if self.id.startswith("Camera") else ""
        out = [
            f'<pegbar id="{self.id}"{act}><parent handle="B" id="{self.parent}" parentHandle="B">'
            "</parent><isOpened>0</isOpened>",
            f"<center>{cx:.6g} {cy:.6g} {-cx:.6g} {-cy:.6g}</center><status>0</status>",
        ]
        for tag in ("x", "y", "z", "so", "sx", "sy", "sc", "rot"):
            if tag in self.channels:
                v = self.channels[tag]
                out.append(linear_channel(tag, v) if isinstance(v, list) else const_channel(tag, v))
        out.append(self.plastic)
        out.append("<nodePos>1.234e+09 5.678e+09</nodePos>" + self.camera + "</pegbar>")
        return "".join(out)


def plastic_sd(joints: list[tuple[float, float]], bend_deg: list[float]) -> str:
    """A 3-vertex skeleton (root, mid, end; pixels from the image centre, y up) whose END vertex
    carries the per-frame bend angle: the segment mid->end rotates about mid by that angle."""
    k = STAGE_INCH / DPI
    names = ["Root", "Vertex 2", "Vertex 3"]
    verts = "".join(
        f'<Vertex><name>"{n}"</name><number>{i + 1}</number>'
        f"<pos>{x * k:.5f} {y * k:.5f}</pos><interpolate>1</interpolate></Vertex>"
        for i, (n, (x, y)) in enumerate(zip(names, joints, strict=True))
    )
    vd = f'<Name>"Vertex 3"</Name><Hook>3</Hook><VD>{linear_channel("Angle", bend_deg)}</VD>'
    return (
        f"<plasticSD><VertexDeforms>{vd}</VertexDeforms>"
        "<SkelIdsParam><default>1</default></SkelIdsParam>"
        f"<Skeletons><SkelId>1</SkelId><Skeleton><V>3 {verts}</V><E>2 0 1 1 2</E></Skeleton>"
        "</Skeletons></plasticSD>"
    )


@dataclass
class Column:
    level: str
    cells: list[tuple[int, int, int]]  # (row, count, drawing number); one drawing each
    peg: Peg
    mesh: bool = False


def build_tnz(
    levels: dict[str, str],
    columns: list[Column],
    camera: Peg,
    frames: int,
    out: str,
    transparent: bool = False,
) -> str:
    ids = iter(range(1, 100_000))
    level_ids = {n: next(ids) for n in levels}
    lv = "".join(
        f'<level id=\'{level_ids[n]}\'>{n} <info dpix="{DPI}" dpiy="{DPI}"/><path>"{p}"</path></level>'
        for n, p in levels.items()
    )
    cols, terminal, pegs = [], [], [camera.xml(), Peg("Table", "None").xml()]
    for i, c in enumerate(columns, start=1):
        c.peg.id = f"Col{i}"
        pegs.append(c.peg.xml())
        cells = "".join(
            f"<cell>{r} {n} <level id='{level_ids[c.level]}'/>{d:04d} 0</cell>"
            for r, n, d in c.cells
        )
        if c.mesh:
            cols.append(
                f"<meshColumn id='{next(ids)}'><status>0</status><cells>{cells}</cells></meshColumn>"
            )
            continue
        col_id, fx_id = next(ids), next(ids)
        terminal.append(f"<fxnode><Toonz_columnFx id='{fx_id}'/></fxnode>")
        cols.append(
            f"<levelColumn id='{col_id}'><status>0</status><cells>{cells}</cells><fx>"
            f"<Toonz_columnFx id='{fx_id}'><params></params><ports></ports><numberId>0</numberId>"
            f'<name>LevelColumn</name><fxId>""</fxId><opened>0</opened></Toonz_columnFx></fx></levelColumn>'
        )
    xs, of = next(ids), next(ids)
    node = lambda tag, i, ports="": (  # noqa: E731
        f"<{tag} id='{i}'><params></params><ports>{ports}</ports><numberId>0</numberId>"
        f'<name>{"Xsheet" if "xsheet" in tag else "Output"}</name><fxId>""</fxId><opened>0</opened></{tag}>'
    )
    return (
        f'<tnz framecount="{frames}" version="71.1"><generator>"animation-studio bakeoff"</generator>'
        f'<properties><cameras>{CAMERA_XML}</cameras><outputs><output name="main">'
        f"<range>0 {frames - 1}</range><step>1</step><shrink>1</shrink><fps>{FPS}</fps>"
        f'<path>"{out}"</path><bpp>32</bpp><resquality>1</resquality></output></outputs>'
        f"<bgColor>255 255 255 {0 if transparent else 255}</bgColor></properties>"
        f"<levelSet><levels>{lv}</levels></levelSet>"
        f"<xsheet><columns>{''.join(cols)}</columns><pegbars>{''.join(pegs)}"
        "<grid_dimension>1</grid_dimension></pegbars>"
        f"<fxnodes><terminal>{''.join(terminal)}</terminal>"
        f"<xsheet>{node('Toonz_xsheetFx', xs)}</xsheet>"
        f"<output>{node('Toonz_outputFx', of, f'<source><Toonz_xsheetFx id={chr(39)}{xs}{chr(39)}/></source>')}</output>"
        "</fxnodes></xsheet></tnz>\n"
    )


def write_project(root: Path) -> Path:
    (root / "scenes").mkdir(parents=True, exist_ok=True)
    (root / "inputs").mkdir(exist_ok=True)
    (root / "outputs").mkdir(exist_ok=True)
    folders = "".join(
        f'<folder name="{f}" path="{f}"/>'
        for f in ("inputs", "drawings", "scenes", "extras", "outputs", "palettes", "scripts")
    )
    (root / f"{root.name}_otprj.xml").write_text(
        f"<project><version>70 1</version><folders>{folders}</folders></project>\n"
    )
    (root / "scenes" / "scenes.xml").write_text(
        '<parentProject type="projectFolder">\n  ".."\n</parentProject>\n'
    )
    return root / "scenes"


def render(
    scene: Path, out_dir: Path, frames: int, threads: int = 1, shrink: int = 1, first: int = 1
) -> dict:
    """tcomposer; reports what is on disk (it can crash at exit after writing every frame)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(TCOMPOSER),
        str(scene),
        "-o",
        str(out_dir / "f.png"),
        "-range",
        str(first),
        str(frames),
        "-nthreads",
        str(threads),
        "-shrink",
        str(shrink),
        "-TOONZROOT",
        str(STUFF),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    made = sorted(out_dir.glob("f.*.png"))
    return {
        "returncode": proc.returncode,
        "frames": len(made),
        "wall_s": round(wall, 2),
        "stderr_tail": proc.stderr[-400:],
    }
