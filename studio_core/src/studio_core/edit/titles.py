"""Title cards: text centred on a plain backdrop, as a short silent clip.

Pillow draws one PNG at the film's size; ffmpeg turns it into an H.264 clip with a silent stereo
AAC track (so every clip in the film has the same streams and melt mixes audio the same way).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from studio_core.audio import ffmpeg
from studio_core.config import StudioConfig, load_config

BACKDROP = (255, 246, 224)  # warm cream
INK = (74, 52, 38)  # dark brown
FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_w: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(trial, font=font) > max_w:
            lines.append(word)
        elif lines:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def draw_card(text: str, subtitle: str | None, size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, BACKDROP)
    draw = ImageDraw.Draw(img)
    main, small = _font(h // 8), _font(h // 18)
    lines = _wrap(draw, text, main, int(w * 0.8))
    line_h = int(h / 8 * 1.25)
    sub_h = int(h / 18 * 2) if subtitle else 0
    y = (h - len(lines) * line_h - sub_h) // 2
    for line in lines:
        draw.text((w / 2, y), line, font=main, fill=INK, anchor="mt")
        y += line_h
    if subtitle:
        draw.text((w / 2, y + h // 36), subtitle, font=small, fill=INK, anchor="mt")
    return img


def render_title(
    out: Path,
    text: str,
    subtitle: str | None,
    duration_s: float,
    size: tuple[int, int],
    fps: int,
    cfg: StudioConfig | None = None,
) -> Path:
    """Write the card as `out` (an .mp4); returns it. Same inputs, same clip."""
    out.parent.mkdir(parents=True, exist_ok=True)
    png = out.with_suffix(".png")
    draw_card(text, subtitle, size).save(png)
    ffmpeg.run(
        [
            *("-loop", "1", "-framerate", str(fps), "-i", str(png)),
            *("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"),
            *("-t", f"{duration_s:.3f}", "-shortest"),
            *("-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-r", str(fps)),
            *("-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)),
        ],
        cfg or load_config(),
    )
    return out
