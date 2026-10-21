# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10"]
# ///
"""Spike: author an OpenToonz Plastic (mesh + skeleton) deformation entirely from code.

    uv run scripts/spikes/opentoonz_plastic.py --render

Builds a project with one PNG drawing (a flower on a stem) used twice:
  * Col1 = the texture, parented to Col2 (a *mesh column*) - this is the Plastic binding;
  * Col2 = a hand-generated triangle mesh (``flower_mesh.0001.mesh``, plain-text, no app needed)
    whose stage object carries ``<plasticSD>``: a 3-vertex skeleton (Root -> Vertex 2 ->
    Vertex 3 up the stem) plus keyframed per-vertex ``Angle`` channels, so the stem sways;
  * Col3 = the same drawing without deformation, for comparison.
Then renders 48 frames with tcomposer and encodes an MP4.

Coordinate spaces (from the OpenToonz 1.8 source, plasticdeformerfx.cpp / meshifypopup.cpp):
mesh vertices are pixels at the mesh dpi with the origin at the image centre (y up); skeleton
vertices are in Stage units (1 inch = 53.33333), i.e. pixels * 53.33333 / dpi.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from opentoonz_scene import (
    CAMERA_XML,
    DPI,
    SS,
    Key,
    channel,
    encode,
    render,
    write_project,
)
from PIL import Image, ImageDraw

STAGE_INCH = 53.33333
W, H = 160, 480  # flower drawing, pixels
DEFAULT_OUT = Path.home() / "ai-studio/scratch/opentoonz-spike/plastic"


def draw_flower(path: Path) -> None:
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    line = (70, 52, 46, 255)
    d.rounded_rectangle(
        [(W / 2 - 14) * SS, 120 * SS, (W / 2 + 14) * SS, (H - 4) * SS],
        radius=12 * SS,
        fill=(88, 170, 90, 255),
        outline=line,
        width=3 * SS,
    )
    for y in range(150, H - 20, 40):  # stripes make the bend easy to see
        d.line(
            [(W / 2 - 13) * SS, y * SS, (W / 2 + 13) * SS, (y + 12) * SS],
            fill=(60, 130, 66, 255),
            width=5 * SS,
        )
    cx, cy = W / 2, 80
    for dx, dy in [(0, -42), (40, -13), (25, 34), (-25, 34), (-40, -13)]:
        d.ellipse(
            [(cx + dx - 32) * SS, (cy + dy - 32) * SS, (cx + dx + 32) * SS, (cy + dy + 32) * SS],
            fill=(250, 150, 190, 255),
            outline=line,
            width=3 * SS,
        )
    d.ellipse(
        [(cx - 26) * SS, (cy - 26) * SS, (cx + 26) * SS, (cy + 26) * SS],
        fill=(255, 214, 90, 255),
        outline=line,
        width=3 * SS,
    )
    img.resize((W, H), Image.Resampling.LANCZOS).save(path)


def mesh_text(nx: int = 5, ny: int = 13) -> str:
    """A regular triangle grid over the whole drawing, as an uncompressed .mesh file.

    TIStream accepts plain text (only files starting with 'T' are treated as LZ4-compressed),
    so no OpenToonz code is needed to write meshes. Faces list 3 *edge* indices, CCW (y up).
    """
    xs = [-W / 2 + W * i / (nx - 1) for i in range(nx)]
    ys = [-H / 2 + H * j / (ny - 1) for j in range(ny)]
    verts = [(x, y) for y in ys for x in xs]
    edges: dict[tuple[int, int], int] = {}

    def edge(a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in edges:
            edges[key] = len(edges)
        return edges[key]

    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            p00, p10 = j * nx + i, j * nx + i + 1
            p01, p11 = (j + 1) * nx + i, (j + 1) * nx + i + 1
            for a, b, c in ((p00, p10, p11), (p00, p11, p01)):
                faces.append((edge(a, b), edge(b, c), edge(c, a)))
    v = " ".join(f"{x:g} {y:g}" for x, y in verts)
    e = " ".join(f"{a} {b}" for a, b in edges)  # dict keeps insertion order == index
    f = " ".join(f"{a} {b} {c}" for a, b, c in faces)
    return (
        f"<header><version>1 19</version><dpi>{DPI} {DPI}</dpi></header>\n"
        f"<mesh><V>{len(verts)} {v}</V><E>{len(edges)} {e}</E><F>{len(faces)} {f}</F></mesh>\n"
    )


def plastic_sd(frames: int) -> str:
    """Skeleton up the stem + keyframed Angle per vertex (degrees, relative to rest pose)."""
    k = STAGE_INCH / DPI  # pixels -> Stage units
    bones = [("Root", 1, -230), ("Vertex 2", 2, 0), ("Vertex 3", 3, 170)]  # (name, number, y px)
    last = frames - 1
    sway = {
        "Vertex 2": [Key(0, 0), Key(last // 4, 22), Key(3 * last // 4, -22), Key(last, 0)],
        "Vertex 3": [Key(0, 0), Key(last // 4, 28), Key(3 * last // 4, -28), Key(last, 0)],
    }
    vds = "".join(
        f'<Name>"{name}"</Name><Hook>{num}</Hook><VD>{channel("Angle", sway[name])}</VD>'
        for name, num, _ in bones
        if name in sway
    )
    verts = "".join(
        f'<Vertex><name>"{name}"</name><number>{num}</number><pos>{7 * k:.4f} {y * k:.4f}</pos>'
        f"<interpolate>1</interpolate></Vertex>"
        for name, num, y in bones
    )
    return (
        f"<plasticSD><VertexDeforms>{vds}</VertexDeforms>"
        f"<SkelIdsParam><default>1</default></SkelIdsParam>"
        f"<Skeletons><SkelId>1</SkelId><Skeleton><V>{len(bones)} {verts}</V>"
        f"<E>2 0 1 1 2</E></Skeleton></Skeletons></plasticSD>"
    )


def pegbar(pid: str, parent: str, extra: str = "", camera: str = "") -> str:
    act = ' activeboth="yes"' if pid.startswith("Camera") else ""
    return (
        f'<pegbar id="{pid}"{act}><parent handle="B" id="{parent}" parentHandle="B"></parent>'
        f"<isOpened>0</isOpened><center>0 0 0 0</center><status>0</status>{extra}"
        f"<nodePos>1.234e+09 5.678e+09</nodePos>{camera}</pegbar>"
    )


def build(frames: int) -> str:
    fx = (
        "<params></params><ports></ports><numberId>0</numberId><name>LevelColumn</name>"
        '<fxId>""</fxId><opened>0</opened>'
    )
    cells = lambda lvl: f"<cells><cell>0 {frames} <level id='{lvl}'/>0001 0</cell></cells>"  # noqa: E731
    return f"""<tnz framecount="{frames}" version="71.1">
<generator>"animation-studio plastic spike"</generator>
<properties><cameras><camera>{CAMERA_XML[8:-9]}</camera></cameras>
<outputs><output name="main"><range>0 {frames - 1}</range><step>1</step><shrink>1</shrink>
<fps>24</fps><path>"+outputs/plastic.png"</path><bpp>32</bpp><resquality>1</resquality>
</output></outputs><bgColor>255 252 240 255</bgColor></properties>
<levelSet><levels>
<level id='1'>flower <info dpix="{DPI}" dpiy="{DPI}"/><path>"+inputs/flower..png"</path></level>
<level id='2'>flower_mesh <info dpix="{DPI}" dpiy="{DPI}"/><path>"+inputs/flower_mesh..mesh"</path></level>
</levels></levelSet>
<xsheet><columns>
<levelColumn id='3'><status>0</status>{cells(1)}<fx><Toonz_columnFx id='4'>{fx}</Toonz_columnFx></fx></levelColumn>
<meshColumn id='5'><status>0</status>{cells(2)}</meshColumn>
<levelColumn id='6'><status>0</status>{cells(1)}<fx><Toonz_columnFx id='7'>{fx}</Toonz_columnFx></fx></levelColumn>
</columns>
<pegbars>
{pegbar("Camera1", "None", camera=CAMERA_XML)}
{pegbar("Table", "None")}
{pegbar("Col1", "Col2")}
{pegbar("Col2", "Table", "<x><default>-2.5</default></x>" + plastic_sd(frames))}
{pegbar("Col3", "Table", "<x><default>2.5</default></x>")}
<grid_dimension>1</grid_dimension></pegbars>
<fxnodes><terminal><fxnode><Toonz_columnFx id='4'/></fxnode><fxnode><Toonz_columnFx id='7'/></fxnode></terminal>
<xsheet><Toonz_xsheetFx id='8'><params></params><ports></ports><numberId>0</numberId><name>Xsheet</name><fxId>""</fxId><opened>0</opened></Toonz_xsheetFx></xsheet>
<output><Toonz_outputFx id='9'><params></params><ports><source><Toonz_xsheetFx id='8'/></source></ports><numberId>0</numberId><name>Output</name><fxId>""</fxId><opened>0</opened></Toonz_outputFx></output>
</fxnodes></xsheet></tnz>
"""  # noqa: E501


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--frames", type=int, default=48)
    ap.add_argument("--render", action="store_true")
    args = ap.parse_args()

    root: Path = args.out.expanduser().resolve()
    if root.exists():
        shutil.rmtree(root)
    scenes = write_project(root)
    (root / "inputs").mkdir()
    draw_flower(root / "inputs" / "flower.0001.png")
    (root / "inputs" / "flower_mesh.0001.mesh").write_text(mesh_text())
    tnz = scenes / "plastic_flower.tnz"
    tnz.write_text(build(args.frames))
    print(f"wrote {tnz}")
    if args.render:
        frames_dir = root / "outputs" / "frames"
        render(tnz, frames_dir, args.frames, "all")
        encode(frames_dir, root / "outputs" / "plastic_flower.mp4")


if __name__ == "__main__":
    main()
