"""Face sprites for engines that animate images, not vectors (engine-neutral, D-030).

The Synfig back end draws the face as vector layers on the head (`face.py`). An engine that moves
textures needs the face as pixels, so this module draws the same face (eyes open or shut, a mouth
shape per Rhubarb cue letter, brows) onto the faceless head image: one PNG per (eyes, mouth)
pair a shot uses. Geometry and colours come from the rig's `face` block; the drawing is simpler
than the vector face on purpose (a cheap stand-in, the same for every engine in a comparison).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

SS = 4  # supersampling for clean edges


def _ellipse(
    d: ImageDraw.ImageDraw, c: tuple[float, float], rx: float, ry: float, **kw: Any
) -> None:
    d.ellipse([(c[0] - rx) * SS, (c[1] - ry) * SS, (c[0] + rx) * SS, (c[1] + ry) * SS], **kw)


def _mouth(d: ImageDraw.ImageDraw, at: tuple[float, float], w: float, cue: str, line: str) -> None:
    x, y = at
    lw = max(2, round(w * 0.07)) * SS
    inside, tongue, teeth = "#5a1f1f", "#d9667a", "#ffffff"
    shapes = {  # cue: (half-width factor, half-height factor)
        "C": (0.45, 0.30),
        "D": (0.52, 0.48),
        "E": (0.30, 0.26),
        "F": (0.20, 0.20),
        "H": (0.42, 0.32),
        "B": (0.45, 0.10),
        "G": (0.45, 0.10),
    }
    if cue in ("A", "X") or cue not in shapes:
        smile = cue == "X"
        d.arc(
            [
                (x - w * 0.4) * SS,
                (y - w * 0.25) * SS,
                (x + w * 0.4) * SS,
                (y + w * (0.15 if smile else 0.0)) * SS,
            ],
            20 if smile else 0,
            160 if smile else 180,
            fill=line,
            width=lw,
        )
        if not smile:
            d.line([(x - w * 0.4) * SS, y * SS, (x + w * 0.4) * SS, y * SS], fill=line, width=lw)
        return
    hx, hy = shapes[cue]
    _ellipse(d, (x, y), w * hx * 0.6, w * hy * 0.6, fill=inside, outline=line, width=lw)
    if cue in ("B", "G"):
        d.rectangle(
            [
                (x - w * hx * 0.5) * SS,
                (y - w * hy * 0.5) * SS,
                (x + w * hx * 0.5) * SS,
                (y - w * 0.01) * SS,
            ],
            fill=teeth,
        )
    if cue in ("D", "H", "C"):
        _ellipse(d, (x, y + w * hy * 0.3), w * hx * 0.35, w * hy * 0.25, fill=tongue)


def draw_head(rig_dir: Path, view: dict[str, Any], eyes: str, mouth: str) -> Image.Image:
    face = view["face"]
    head = Image.open(rig_dir / view["parts"][face["part"]]["file"]).convert("RGBA")
    big = head.resize((head.width * SS, head.height * SS), Image.LANCZOS)
    d = ImageDraw.Draw(big)
    line = face["colors"]["line"]
    size = face["eyes"]["size_px"]
    lw = max(2, round(size * 0.07)) * SS
    for side in ("left_px", "right_px"):
        cx, cy = face["eyes"][side]
        if eyes in ("closed",):
            d.arc(
                [
                    (cx - size / 2) * SS,
                    (cy - size * 0.2) * SS,
                    (cx + size / 2) * SS,
                    (cy + size * 0.3) * SS,
                ],
                200,
                340,
                fill=line,
                width=lw,
            )
        else:
            ry = size * (0.55 if eyes == "open" else 0.3)
            _ellipse(d, (cx, cy), size * 0.5, ry, fill="#ffffff", outline=line, width=lw)
            _ellipse(
                d,
                (cx, cy + size * 0.03),
                size * 0.26,
                min(ry * 0.9, size * 0.3),
                fill=face["colors"]["iris"],
            )
            _ellipse(
                d, (cx - size * 0.08, cy - size * 0.1), size * 0.07, size * 0.07, fill="#ffffff"
            )
        bx, by = face["brows"][side]
        bw = face["brows"]["width_px"]
        d.arc(
            [(bx - bw / 2) * SS, (by - 6) * SS, (bx + bw / 2) * SS, (by + 10) * SS],
            200,
            340,
            fill=line,
            width=lw,
        )
    m = face["mouth"]
    _mouth(d, tuple(m["at_px"]), m["width_px"], mouth, line)
    return big.resize(head.size, Image.LANCZOS)


def write_sprites(bake: dict[str, Any], out_dir: Path) -> None:
    """Write the head sprites a bake uses and set `frames[].head` (a file path) on each frame."""
    from studio_core.rig import load_rig

    for ch in bake["characters"]:
        if not ch.get("face"):
            continue
        rig = load_rig(Path(ch["rig_dir"]) / "rig.json")
        view = rig.view(ch["view"])
        folder = out_dir / ch["id"]
        folder.mkdir(parents=True, exist_ok=True)
        if view["face"].get("layout") and ch["frames"] and "face" in ch["frames"][0]:
            from studio_core.engines.face_flat import write_flat_sprites

            write_flat_sprites(rig.folder, view, ch["frames"], folder)  # parametric face (D-093)
            continue
        for fr in ch["frames"]:
            path = folder / f"head_{fr['eyes']}_{fr['mouth']}.png"
            if not path.exists():
                draw_head(rig.folder, view, fr["eyes"], fr["mouth"]).save(path)
            fr["head"] = str(path)
