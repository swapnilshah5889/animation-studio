"""A rig from a ready-made cast: Kenney "Toon Characters 1" (CC0, D-100).

Mia's four rounds of home-made art did not reach the bar, so this builds a rig from professionally
drawn parts instead. The vector source (`Vector/<character>.svg`) is a sprite sheet of symbols
(`arm`, `leg`, `legBend`, `hand`, `body`, `bodyBack`, `head`, `headFocus`, `headShock`, `headBack`)
placed per pose. Each symbol's origin is its joint (the arm's rounded cap, the leg's hip, the
head's chin), and the `idle` cell of the sheet gives the rest layout. We re-render every symbol
from the SVG at `px_per_unit` (the PNG parts are only ~100 px wide, soft at 1080p) and write the
same `rig.json` the engines already read (one view, bones with joints and limits, parts with
pivots, a draw order). Variants of one part (leg / legBend, head / headFocus / headShock /
headBack, body / bodyBack) share ONE canvas and pivot, so an engine can swap the texture per frame
without any stretch (`frames[].part_images`).

Needs `cairosvg` (and Homebrew's cairo: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`) at build
time only; the engines never import it.
"""

from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"

GROUPS: dict[str, list[str]] = {  # canvas group -> symbol names sharing it
    "leg": ["leg", "legBend"],
    "arm": ["arm"],
    "hand": ["hand", "handOpen"],
    "body": ["body", "bodyBack"],
    "head": ["head", "headFocus", "headShock", "headBack"],
}
LIMITS = {
    "torso": (-15, 15),
    "head": (-25, 25),
    "upper_arm": (-30, 170),
    "hand": (-60, 60),
    "thigh": (-35, 35),
}
LEG_IN = 4.0  # units: the thighs sit this much closer together (the art leaves a wide gap)
# An open hand, drawn by code (the set has only a mitten): palm, four fingers, a thumb, pointing
# down from the wrist like the mitten. Units match the SVG sheet, origin at the wrist.
OPEN_HAND_SVG = (
    '<g fill="none" stroke="#BF7958" stroke-linecap="round" stroke-linejoin="round">'
    '<path stroke-width="2.7" d="M -6.6 6 L -7.6 12"/>'
    '<path stroke-width="2.7" d="M -4.2 7 L -4.6 13.5"/>'
    '<path stroke-width="2.7" d="M -1.7 7 L -1.2 13"/>'
    '<path stroke-width="2.5" d="M 0.6 6 L 2.2 11"/>'
    '<path stroke-width="3" d="M -7.4 3.5 L -12 7.5"/>'
    "</g>"
    '<path fill="#BF7958" d="M -8 0 Q -8.5 -2 -5 -2.4 L 0 -2.4 Q 3.4 -2 3 0 L 3 6 '
    'Q 2.6 9 -2.5 9 Q -8 9 -8 6 Z"/>'
    '<path fill="#A8623F" d="M 3 0 L 3 6 Q 2.6 9 -2.5 9 Q 0.5 8 1 4 Z"/>'
)
DRAW_ORDER = [
    "pelvis",
    "thigh_l",
    "thigh_r",
    "upper_arm_l",
    "upper_arm_r",
    "torso",
    "hand_l",
    "hand_r",
    "head",
]


@dataclass
class Placed:
    name: str  # symbol group (leg, arm, ...)
    origin: tuple[float, float]  # sheet units
    sign: int  # +1, or -1 for the mirrored (right-hand) copy


def _mat(s: str) -> list[float]:
    return [float(v) for v in re.findall(r"-?[\d.]+(?:e-?\d+)?", s)]


def idle_layout(svg_path: Path, sheet_xml: Path) -> dict[str, Placed]:
    """Where each symbol sits in the `idle` cell of the sheet (the rest pose)."""
    root = ET.parse(svg_path).getroot()
    poses = next(g for g in root.iter(SVG + "g") if g.get("id") == "poses")
    rect = None
    for st in ET.parse(sheet_xml).getroot().iter("SubTexture"):
        if st.get("name") == "idle":
            rect = tuple(int(st.get(k)) for k in ("x", "y", "width", "height"))
    assert rect, "no idle pose in the tilesheet"
    out: dict[str, Placed] = {}
    for kid in poses:
        m = _mat(kid.get("transform", ""))
        if not (rect[0] <= m[4] <= rect[0] + rect[2] and rect[1] <= m[5] <= rect[1] + rect[3]):
            continue
        for use in kid.iter(SVG + "use"):
            href = use.get(XLINK, "")
            name = href.removeprefix("#").split("_0_Layer0")[0]
            if name not in {s for g in GROUPS.values() for s in g} | {"shadow"}:
                continue
            tag = name
            key = f"{tag}_{'l' if m[0] > 0 else 'r'}" if tag in ("leg", "arm", "hand") else tag
            out.setdefault(key, Placed(tag, (m[4], m[5]), 1 if m[0] > 0 else -1))
    return out


def _render(defs: ET.Element, ids: list[str], px: float, pad: int = 60) -> Image.Image:
    import cairosvg

    grads = "".join(
        ET.tostring(e, encoding="unicode")
        for e in defs
        if e.tag in (SVG + "radialGradient", SVG + "linearGradient")
    )
    byid = {e.get("id"): e for e in defs.iter() if e.get("id")}
    inner = "".join(ET.tostring(byid[i], encoding="unicode") for i in ids)
    uses = "".join(f'<use xlink:href="#{i}"/>' for i in ids)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{2 * pad * px}" height="{2 * pad * px}" '
        f'viewBox="{-pad} {-pad} {2 * pad} {2 * pad}">'
        f"<defs>{grads}{inner}</defs>{uses}</svg>"
    )
    png = cairosvg.svg2png(bytestring=svg.encode())
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _render_raw(body: str, px: float, pad: int = 60) -> Image.Image:
    import cairosvg

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{2 * pad * px}" height="{2 * pad * px}" '
        f'viewBox="{-pad} {-pad} {2 * pad} {2 * pad}">{body}</svg>'
    )
    return Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode()))).convert("RGBA")


def _symbol_ids(defs: ET.Element, name: str) -> list[str]:
    ids = {e.get("id") for e in defs.iter() if e.get("id")}
    return sorted(i for i in ids if i and i.startswith(name + "_0_Layer0"))


def build_kenney_puppet(
    character_dir: Path, folder: Path, px_per_unit: int = 12, name: str | None = None
) -> dict[str, Any]:
    """Write rig.json + part PNGs into `folder` from a Kenney character folder (the one with
    `Vector/` and `Tilesheet/`)."""
    svg_path = next((character_dir / "Vector").glob("*.svg"))
    sheet_xml = next((character_dir / "Tilesheet").glob("*_sheet.xml"))
    layout = idle_layout(svg_path, sheet_xml)
    root = ET.parse(svg_path).getroot()
    defs = next(d for d in root if d.tag == SVG + "defs")
    pdir = folder / "parts" / "front"
    pdir.mkdir(parents=True, exist_ok=True)
    px = px_per_unit

    canvases: dict[
        str, dict[str, Any]
    ] = {}  # group -> {"box": (x0,y0,x1,y1) units, "imgs": {sym: img}}
    for group, symbols in GROUPS.items():
        renders = {
            s: _render_raw(OPEN_HAND_SVG, px)
            if s == "handOpen"
            else _render(defs, _symbol_ids(defs, s), px)
            for s in symbols
        }
        pad = 60
        boxes = [im.getchannel("A").getbbox() for im in renders.values()]
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes)
        y1 = max(b[3] for b in boxes)
        if group == "leg":  # the foot point (bottom centre) sits under the hip: the gait solver
            m = max(pad * px - x0, x1 - pad * px)  # and the foot rules both assume it
            x0, x1 = int(pad * px - m), int(pad * px + m)
        canvases[group] = {
            "box_px": (x0, y0, x1, y1),
            "pad": pad,
            "imgs": {s: im.crop((x0, y0, x1, y1)) for s, im in renders.items()},
        }

    def pivot(group: str, sign: int) -> tuple[float, float]:
        x0, y0, x1, _y1 = canvases[group]["box_px"]
        pad = canvases[group]["pad"]
        o = pad * px  # the symbol origin in the render
        w = x1 - x0
        px_x = (o - x0) if sign > 0 else (w - (o - x0))
        return (round(px_x, 1), round(o - y0, 1))

    def size(group: str) -> tuple[int, int]:
        x0, y0, x1, y1 = canvases[group]["box_px"]
        return (x1 - x0, y1 - y0)

    def to_img(group: str, sign: int, origin: tuple[float, float], p: tuple[float, float]):
        pv = pivot(group, sign)
        return (
            round(
                pv[0] + (p[0] - origin[0]) * px, 1
            ),  # (the mirrored image already faces the sheet)
            round(pv[1] + (p[1] - origin[1]) * px, 1),
        )

    # one PNG per part (the right-hand limbs are the mirrored image)
    files: dict[str, str] = {}
    variants: dict[str, str] = {}
    for part, (group, sym, sign) in {
        "thigh_l": ("leg", "leg", 1),
        "thigh_r": ("leg", "leg", -1),
        "upper_arm_l": ("arm", "arm", 1),
        "upper_arm_r": ("arm", "arm", -1),
        "torso": ("body", "body", 1),
        "hand_l": ("hand", "hand", 1),
        "hand_r": ("hand", "hand", -1),
        "head": ("head", "head", 1),
    }.items():
        img = canvases[group]["imgs"][sym]
        if sign < 0:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        img.save(pdir / f"{part}.png")
        files[part] = f"parts/front/{part}.png"
    for sym, group in (
        ("legBend", "leg"),
        ("bodyBack", "body"),
        ("headFocus", "head"),
        ("headShock", "head"),
        ("headBack", "head"),
        ("handOpen", "hand"),
    ):
        for sign, tag in ((1, ""), (-1, "_mirror")):
            if tag and group not in ("leg", "hand"):
                continue
            img = canvases[group]["imgs"][sym]
            if sign < 0:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            fn = f"{sym}{tag}.png"
            img.save(pdir / fn)
            variants[f"{sym}{tag}"] = f"parts/front/{fn}"

    L = layout
    body_o = L["body"].origin
    head_o = L["head"].origin
    arm_o = {"l": L["arm_l"].origin, "r": L["arm_r"].origin}
    hand_o = {"l": L["hand_l"].origin, "r": L["hand_r"].origin}
    leg_o = {
        "l": (L["leg_l"].origin[0] - LEG_IN, L["leg_l"].origin[1]),
        "r": (L["leg_r"].origin[0] + LEG_IN, L["leg_r"].origin[1]),
    }

    def part(name_: str, group: str, sign: int, origin: tuple[float, float], bone: str):
        w, h = size(group)
        return {
            "file": files[name_],
            "size_px": [w, h],
            "pivot_px": list(pivot(group, sign)),
            "bone": bone,
        }

    # a pelvis behind the legs closes the see-through gap between the thighs (the reviewer read it
    # as a pasted slab): shorts colour at the top, skin below, colours sampled from the leg art
    leg_img = canvases["leg"]["imgs"]["leg"]
    lpx, lpy = pivot("leg", 1)
    shorts = leg_img.getpixel((int(lpx + 2 * px), int(lpy + 3 * px)))
    skin = leg_img.getpixel((int(lpx + 2 * px), int(lpy + 9 * px)))
    pw, ph = int(18 * px), int(15 * px)
    pelvis = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    split = int((leg_o["l"][1] - body_o[1] + 7) * px)
    for y in range(ph):
        for x in range(pw):
            pelvis.putpixel((x, y), shorts if y < split else skin)
    pelvis.save(pdir / "pelvis.png")
    files["pelvis"] = "parts/front/pelvis.png"

    parts = {
        "pelvis": {
            "file": files["pelvis"],
            "size_px": [pw, ph],
            "pivot_px": [pw / 2, 0.0],
            "bone": "torso",
        },
        "thigh_l": part("thigh_l", "leg", 1, leg_o["l"], "thigh_l"),
        "thigh_r": part("thigh_r", "leg", -1, leg_o["r"], "thigh_r"),
        "upper_arm_l": part("upper_arm_l", "arm", 1, arm_o["l"], "upper_arm_l"),
        "upper_arm_r": part("upper_arm_r", "arm", -1, arm_o["r"], "upper_arm_r"),
        "torso": part("torso", "body", 1, body_o, "torso"),
        "hand_l": part("hand_l", "hand", 1, hand_o["l"], "hand_l"),
        "hand_r": part("hand_r", "hand", -1, hand_o["r"], "hand_r"),
        "head": part("head", "head", 1, head_o, "head"),
    }

    def attach(parent: str, group: str, sign: int, origin, joint) -> dict[str, Any]:
        return {"part": parent, "at_px": list(to_img(group, sign, origin, joint))}

    head_len = (head_o[1] - body_o[1]) * -1 * px  # torso: hip (body origin) up to the head joint
    arm_len = (hand_o["l"][1] - arm_o["l"][1]) * px
    bones: dict[str, Any] = {
        "torso": {
            "role": "torso",
            "parent": None,
            "direction_deg": 90.0,
            "length_px": round(head_len, 1),
            "side": "center",
            "limits_deg": {"min": LIMITS["torso"][0], "max": LIMITS["torso"][1]},
        },
        "head": {
            "role": "head",
            "parent": "torso",
            "direction_deg": 90.0,
            "length_px": round(-canvases["head"]["box_px"][1] + canvases["head"]["pad"] * px, 1),
            "side": "center",
            "limits_deg": {"min": LIMITS["head"][0], "max": LIMITS["head"][1]},
            "attach": attach("torso", "body", 1, body_o, head_o),
        },
    }
    for tag, side, sign in (("l", "left", 1), ("r", "right", -1)):
        bones[f"upper_arm_{tag}"] = {
            "role": "upper_arm",
            "parent": "torso",
            "direction_deg": -90.0,
            "length_px": round(arm_len, 1),
            "side": side,
            "limits_deg": (
                {"min": LIMITS["upper_arm"][0], "max": LIMITS["upper_arm"][1]}
                if sign > 0
                else {"min": -LIMITS["upper_arm"][1], "max": -LIMITS["upper_arm"][0]}
            ),
            "attach": attach("torso", "body", 1, body_o, arm_o[tag]),
        }
        bones[f"hand_{tag}"] = {
            "role": "forearm",  # no elbow in this art: the mitten acts as the forearm
            "parent": f"upper_arm_{tag}",
            "direction_deg": -90.0,
            "length_px": round(14 * px, 1),
            "side": side,
            "limits_deg": {"min": LIMITS["hand"][0], "max": LIMITS["hand"][1]},
            "attach": attach(f"upper_arm_{tag}", "arm", sign, arm_o[tag], hand_o[tag]),
        }
        bones[f"thigh_{tag}"] = {
            "role": "thigh",
            "parent": "torso",
            "direction_deg": -90.0,
            "length_px": round(size("leg")[1] - pivot("leg", 1)[1], 1),
            "side": side,
            "limits_deg": {"min": LIMITS["thigh"][0], "max": LIMITS["thigh"][1]},
            "attach": attach("torso", "body", 1, body_o, leg_o[tag]),
        }
    rig = {
        "schema_version": 1,
        "id": name or character_dir.name.lower().replace(" ", "_"),
        "name": name or character_dir.name,
        "style": "flat",
        "default_view": "front",
        "views": {
            "front": {
                "root": "torso",
                "bones": bones,
                "parts": parts,
                "draw_order": DRAW_ORDER,
            }
        },
    }
    (folder / "rig.json").write_text(json.dumps(rig, indent=2) + "\n")
    (folder / "variants.json").write_text(json.dumps(variants, indent=2) + "\n")  # texture swaps
    return rig
