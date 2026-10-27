"""Spike 4B.4: can a limb bend instead of two rigid rectangles? (docs/spikes/bending-limbs.md)

Renders a bent elbow (70 deg) and a bent knee (-70 deg) of Pip's limbs three ways with the
Synfig CLI, and measures each:

  B  baseline  two bone-linked parts; the child part carries a joint cap (a disc of the figure's
               own pixels around the joint), as puppet/build.py does today
  A  skeleton  ONE limb image + a Skeleton Deformation layer over a 2-bone chain
  C  overlap   two parts; the forearm extends under the upper arm, the upper arm fades out over
               the joint with a linear alpha ramp

The sif builder (studio_core.sif) is used read-only. Two things it lacks are subclassed here
(Bone width/tipwidth, the skeleton_deformation layer): that is the generator work item.

Run:  uv run --project studio_core python scripts/spikes/bend_limb.py
Out:  renders/spikes/bending-limbs/ (git-ignored): work/, contact-sheet.png, results.json
"""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from studio_core.sif.bones import Bone, BoneLink
from studio_core.sif.layers import Canvas, Group, ImportLayer, Layer, Rectangle
from studio_core.sif.units import Space
from studio_core.sif.values import Angle, Color, Transform, Vec, value_xml

ROOT = Path(__file__).resolve().parents[2]
PARTS = ROOT / "tests/fixtures/characters/pip/parts"
OUT = ROOT / "renders/spikes/bending-limbs"
SYNFIG = "synfig"

S = 0.025  # world units per image pixel (3 screen px at 120 px/unit)
SHOULDER = Vec(0.0, 3.0)  # where the limb's first pivot sits on the 1920x1080 canvas
BG = Color(0.93, 0.92, 0.86)


# ------------------------------------------------------------------ the limbs (Pip's rig.json)
@dataclass(frozen=True)
class Limb:
    name: str
    upper: str
    lower: str
    upper_pivot: tuple[int, int]  # px in the part image
    joint_in_upper: int  # y of the joint in the upper part (rig attach.at_px)
    lower_pivot: tuple[int, int]
    swing: float  # the upper bone's turn from hanging straight down, degrees (CCW)
    bend: float  # the lower bone's turn relative to the upper, degrees (CCW)


ELBOW = Limb("elbow", "upper_arm", "forearm", (28, 20), 132, (26, 18), 20.0, 70.0)
KNEE = Limb("knee", "thigh", "shin", (32, 16), 118, (32, 14), 25.0, -70.0)


@dataclass
class Art:
    """The limb drawn straight, plus the per-variant part images cut from it."""

    straight: Image.Image
    cx: int  # x of the limb axis
    shoulder_y: int  # y of the first pivot
    joint_y: int  # y of the joint
    upper_len: float  # px between pivot and joint
    lower_len: float  # px from joint to the end of the lower part's art
    half_w: float


def straight_limb(limb: Limb) -> Art:
    up = Image.open(PARTS / f"{limb.upper}.png").convert("RGBA")
    lo = Image.open(PARTS / f"{limb.lower}.png").convert("RGBA")
    cx = max(up.width, lo.width) // 2
    shoulder_y = limb.upper_pivot[1]
    joint_y = shoulder_y + (limb.joint_in_upper - limb.upper_pivot[1])
    height = joint_y - limb.lower_pivot[1] + lo.height
    img = Image.new("RGBA", (cx * 2, height))
    img.alpha_composite(lo, (cx - limb.lower_pivot[0], joint_y - limb.lower_pivot[1]))
    img.alpha_composite(up, (cx - limb.upper_pivot[0], 0))  # upper arm over the forearm
    return Art(
        img,
        cx,
        shoulder_y,
        joint_y,
        joint_y - shoulder_y,
        height - joint_y,
        min(up.width, lo.width) / 2,
    )


def _mask_rows(
    img: Image.Image, y0: int, y1: int, ramp: tuple[int, int] | None = None
) -> Image.Image:
    """img[y0:y1] at full width; optionally fade alpha from 1 at ramp[0] to 0 at ramp[1]."""
    crop = img.crop((0, y0, img.width, y1))
    if ramp is not None:
        a = crop.getchannel("A")
        px = a.load()
        for y in range(crop.height):
            t = 1.0 - min(max((y + y0 - ramp[0]) / (ramp[1] - ramp[0]), 0.0), 1.0)
            for x in range(crop.width):
                px[x, y] = round(px[x, y] * t)
        crop.putalpha(a)
    return crop


def make_parts(art: Art, variant: str, work: Path) -> dict[str, tuple[Path, tuple[int, int]]]:
    """Write the PNGs one variant needs. Returns name -> (file, pivot_px in that file)."""
    work.mkdir(parents=True, exist_ok=True)
    img, cx, jy = art.straight, art.cx, art.joint_y
    if variant == "A":
        img.save(work / "limb.png")
        return {"limb": (work / "limb.png", (cx, art.shoulder_y))}
    if variant == "B":  # cap: a disc of the figure's own pixels, owned by the child part
        r = round(art.half_w)
        lower = img.crop((0, jy - r, img.width, img.height))
        disc = Image.new("L", lower.size, 0)
        ImageDraw.Draw(disc).ellipse((cx - r, 0, cx + r, 2 * r), fill=255)
        below = Image.new("L", lower.size, 0)
        ImageDraw.Draw(below).rectangle((0, r, lower.width, lower.height), fill=255)
        lower.putalpha(ImageChops.multiply(lower.getchannel("A"), ImageChops.lighter(disc, below)))
        upper = img.crop((0, 0, img.width, jy + 1))
        lower_pivot = (cx, r)
    else:  # C: forearm extends under the upper arm; the upper arm fades over the joint
        ramp = round(art.half_w * 0.75)
        ext = ramp + 6
        lower = img.crop((0, jy - ext, img.width, img.height))
        upper = _mask_rows(img, 0, jy + ramp, (jy - ramp, jy + ramp))
        lower_pivot = (cx, ext)
    upper.save(work / "upper.png")
    lower.save(work / "lower.png")
    return {
        "upper": (work / "upper.png", (cx, art.shoulder_y)),
        "lower": (work / "lower.png", lower_pivot),
    }


# ------------------------------------------------------- generator pieces the builder lacks
@dataclass(eq=False)
class WideBone(Bone):
    """A Bone that also writes width/tipwidth: the REST bone's width is the deformation's
    influence radius (pixels outside every rest bone's capsule vanish)."""

    width: float = 0.0

    def to_xml(self) -> ET.Element:
        el = super().to_xml()
        for tag, value in (("width", self.width), ("tipwidth", self.width)):
            ET.SubElement(el, tag).append(value_xml(float(value)))
        return el


@dataclass
class SkeletonDeformation(Layer):
    """Bends every layer below it in the same canvas. pairs = (rest bone, pose bone)."""

    pairs: list[tuple[Bone, Bone]] = field(default_factory=list)
    point1: Vec = field(default_factory=lambda: Vec(-1, 1))
    point2: Vec = field(default_factory=lambda: Vec(1, -1))
    nx: int = 24
    ny: int = 48
    TYPE = "skeleton_deformation"
    VERSION = "0.2"

    def params(self) -> dict[str, object]:
        return {
            "bones": _Pairs(self.pairs),
            "point1": self.point1,
            "point2": self.point2,
            "x_subdivisions": self.nx,
            "y_subdivisions": self.ny,
        }


@dataclass
class _Pairs:
    pairs: list[tuple[Bone, Bone]]

    def to_xml(self) -> ET.Element:
        el = ET.Element("static_list", type="pair_bone_object_bone_object")
        for rest, pose in self.pairs:
            comp = ET.SubElement(
                ET.SubElement(el, "entry"), "composite", type="pair_bone_object_bone_object"
            )
            for tag, b in (("first", rest), ("second", pose)):
                ET.SubElement(ET.SubElement(comp, tag), "bone", type="bone_object", guid=b.guid)
        return el


# ------------------------------------------------------------------------------ the scenes
def _bones(limb: Limb, art: Art, bent: bool, *, rest_pair: bool, width: float):
    """Pose chain (the rig's own bones) and, for A, a static rest chain."""
    swing, bend = (limb.swing, limb.bend) if bent else (0.0, 0.0)
    ul, ll = art.upper_len * S, art.lower_len * S

    def chain(ns: str, up_deg: float, lo_deg: float):
        up = WideBone("upper", None, SHOULDER, Angle(-90 + up_deg), ul, namespace=ns, width=width)
        lo = WideBone("lower", up, Vec(ul, 0), Angle(lo_deg), ll, namespace=ns, width=width)
        return up, lo

    pose = chain("pose", swing, bend)
    rest = chain("rest", 0.0, 0.0) if rest_pair else None
    return pose, rest


def build_scene(
    limb: Limb,
    art: Art,
    variant: str,
    bent: bool,
    work: Path,
    *,
    nested: bool = False,
    grid: tuple[int, int] = (24, 96),
) -> Canvas:
    parts = make_parts(art, variant, work)
    canvas = Canvas(
        width=1920, height=1080, fps=24, frames=1, ppu=120, name=f"{limb.name} {variant}"
    )
    canvas.layers.append(Rectangle("bg", color=BG, point1=Vec(-9, 5), point2=Vec(9, -5)))
    (pu, pl), rest = _bones(limb, art, bent, rest_pair=variant == "A", width=art.half_w * S * 1.1)
    canvas.bones = [pu, pl] + (list(rest) if rest else [])
    space = Space(canvas.width, canvas.height, 1 / S)  # part pixels -> units (S per pixel)

    def part(name: str, bone: Bone, key: str) -> Group:
        file, pivot = parts[key]
        w, h = Image.open(file).size
        img = ImportLayer.with_pivot(name, f"{file.name}", (w, h), pivot, space)
        # the art hangs down (-y); a bone's +x runs along it, so turn the art by +90 deg
        return Group(name, children=[img], transform=BoneLink(bone, Transform(angle=Angle(90))))

    if variant == "A":
        file, pivot = parts["limb"]
        w, h = Image.open(file).size
        img = ImportLayer("limb", file=file.name)
        tl = Vec(SHOULDER.x - pivot[0] * S, SHOULDER.y + pivot[1] * S)
        br = Vec(SHOULDER.x + (w - pivot[0]) * S, SHOULDER.y - (h - pivot[1]) * S)
        img.tl, img.br = tl, br
        deform = SkeletonDeformation(
            "deform",
            pairs=[(rest[0], pu), (rest[1], pl)],
            point1=Vec(tl.x - 0.3, tl.y + 0.2),
            point2=Vec(br.x + 0.3, br.y - 0.2),
            nx=grid[0],
            ny=grid[1],
        )
        layers: list[Layer] = [Group("limb", children=[img, deform])]
    elif variant == "B":  # child over parent: the cap is the child's
        layers = [part("upper", pu, "upper"), part("lower", pl, "lower")]
    else:  # C: forearm first, the fading upper arm over it
        layers = [part("lower", pl, "lower"), part("upper", pu, "upper")]
    if nested:  # the scene places a character with a scaled + moved group (D-027)
        layers = [
            Group(
                "placement",
                children=layers,
                transform=Transform(offset=Vec(1.5, -0.5), scale=Vec(0.6, 0.6)),
            )
        ]
    canvas.layers += layers
    return canvas


# ---------------------------------------------------------------------------- rendering
def render(sif: Path, png: Path, size: tuple[int, int] = (1920, 1080)) -> float:
    cmd = [SYNFIG, str(sif), "-t", "png", "-o", str(png), "-w", str(size[0]), "-h", str(size[1])]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=sif.parent)
    dt = time.perf_counter() - t0
    if proc.returncode != 0 or not png.exists():
        raise RuntimeError(f"synfig failed on {sif}: {proc.stderr[-800:]}")
    errs = [ln for ln in proc.stderr.splitlines() if "error" in ln.lower()]
    if errs:
        raise RuntimeError(f"{sif}: {errs}")
    return dt


def silhouette_px(png: Path) -> int:
    im = Image.open(png).convert("RGB")
    bg = Image.new("RGB", im.size, tuple(round(c * 255) for c in (BG.r, BG.g, BG.b)))
    diff = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 12 else 0)
    return sum(diff.histogram()[255:])


def max_diff(a: Path, b: Path) -> int:
    d = ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB"))
    return max(hi for _, hi in d.getextrema())


def content_box(png: Path) -> tuple[int, int, int, int]:
    im = Image.open(png).convert("RGB")
    bg = Image.new("RGB", im.size, tuple(round(c * 255) for c in (BG.r, BG.g, BG.b)))
    box = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    assert box
    return box


def xml_stats(sif: Path) -> dict[str, int]:
    root = ET.parse(sif).getroot()
    layers = [e for e in root.iter("layer") if e.get("desc") != "bg"]
    return {
        "bytes": sif.stat().st_size,
        "elements": sum(1 for _ in root.iter()),
        "layers": len(layers),
        "bones": len(root.findall("bones/bone")),
        "png_files": len(list(sif.parent.glob("*.png"))) - 1,  # minus the render itself
    }


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "work").mkdir(parents=True)
    results: dict[str, dict] = {}
    renders: dict[tuple[str, str], Path] = {}

    # fixed cost of one synfig process + a flat background: subtracted from the timings
    empty = Canvas(1920, 1080, 24, 1, ppu=120)
    empty.layers.append(Rectangle("bg", color=BG, point1=Vec(-9, 5), point2=Vec(9, -5)))
    (OUT / "work/empty").mkdir()
    empty.save(OUT / "work/empty/scene.sif")
    base_t = statistics.median(
        render(OUT / "work/empty/scene.sif", OUT / "work/empty/o.png") for _ in range(3)
    )
    results["empty_canvas_s"] = round(base_t, 3)

    for limb in (ELBOW, KNEE):
        art = straight_limb(limb)
        for variant in "BAC":
            for bent in (False, True):
                tag = f"{limb.name}-{variant}-{'bent' if bent else 'rest'}"
                work = OUT / "work" / tag
                sif = build_scene(limb, art, variant, bent, work).save(work / "scene.sif")
                png = work / "out.png"
                times = [render(sif, png) for _ in range(3 if bent else 1)]
                renders[(f"{limb.name}-{variant}", "bent" if bent else "rest")] = png
                res = {"sif": xml_stats(sif), "silhouette_px": silhouette_px(png)}
                if bent:
                    res["render_s_median"] = round(statistics.median(times), 3)
                    res["render_s_minus_empty"] = round(statistics.median(times) - base_t, 3)
                results[tag] = res
        # rest pose must match the straight art in every variant
        for variant in "AC":
            results[f"{limb.name}-{variant}-rest"]["max_diff_vs_B_rest"] = max_diff(
                renders[(f"{limb.name}-{variant}", "rest")], renders[(f"{limb.name}-B", "rest")]
            )
        for variant in "BAC":
            r0 = results[f"{limb.name}-{variant}-rest"]["silhouette_px"]
            r1 = results[f"{limb.name}-{variant}-bent"]["silhouette_px"]
            results[f"{limb.name}-{variant}-bent"]["area_vs_rest"] = round(r1 / r0, 3)

    # A inside a scaled + moved parent group, and a denser grid
    art = straight_limb(ELBOW)
    work = OUT / "work/elbow-A-nested"
    sif = build_scene(ELBOW, art, "A", True, work, nested=True).save(work / "scene.sif")
    render(sif, work / "out.png")
    work_b = OUT / "work/elbow-B-nested"
    sif_b = build_scene(ELBOW, art, "B", True, work_b, nested=True).save(work_b / "scene.sif")
    render(sif_b, work_b / "out.png")
    results["elbow-nested-A-vs-B_silhouette_ratio"] = round(
        silhouette_px(work / "out.png") / silhouette_px(work_b / "out.png"), 3
    )
    for grid in ((12, 48), (48, 192)):
        work = OUT / f"work/elbow-A-grid{grid[0]}x{grid[1]}"
        sif = build_scene(ELBOW, art, "A", True, work, grid=grid).save(work / "scene.sif")
        ts = [render(sif, work / "out.png") for _ in range(3)]
        results[f"elbow-A-grid{grid[0]}x{grid[1]}"] = {
            "render_s_median": round(statistics.median(ts), 3),
            "silhouette_px": silhouette_px(work / "out.png"),
            "bytes": sif.stat().st_size,
        }

    # contact sheet: rows = elbow, knee; columns = B, A, C (bent); crop to a shared box per row
    cell_w, label_h = 440, 28
    rows = []
    for limb in (ELBOW, KNEE):
        pngs = [renders[(f"{limb.name}-{v}", "bent")] for v in "BAC"]
        boxes = [content_box(p) for p in pngs]
        box = (
            min(b[0] for b in boxes) - 20,
            min(b[1] for b in boxes) - 20,
            max(b[2] for b in boxes) + 20,
            max(b[3] for b in boxes) + 20,
        )
        rows.append([Image.open(p).convert("RGB").crop(box) for p in pngs])
    cell_h = max(c.height * cell_w // c.width for row in rows for c in row[:1])
    sheet = Image.new("RGB", (cell_w * 3, (cell_h + label_h) * 2), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    names = {
        "B": "B baseline: 2 parts + cap",
        "A": "A skeleton deformation",
        "C": "C overlap + alpha ramp",
    }
    for r, (limb, row) in enumerate(zip((ELBOW, KNEE), rows, strict=True)):
        for c, im in enumerate(row):
            scale = min(cell_w / im.width, cell_h / im.height)
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            sheet.paste(im, (c * cell_w, r * (cell_h + label_h) + label_h))
            draw.text(
                (c * cell_w + 6, r * (cell_h + label_h) + 8),
                f"{limb.name} {limb.bend:+.0f} deg | {names['BAC'[c]]}",
                fill=(0, 0, 0),
            )
    sheet.save(OUT / "contact-sheet.png")
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1))
    print("contact sheet:", OUT / "contact-sheet.png")


if __name__ == "__main__":
    main()
