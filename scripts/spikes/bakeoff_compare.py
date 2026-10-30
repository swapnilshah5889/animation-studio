"""Engine bake-off: one labelled side-by-side video of the same shots.

    uv run --project studio_core python scripts/spikes/bakeoff_compare.py OUT.mp4 \
        [--engines synfig-rigid,synfig-bend,blender-workbench,opentoonz-plastic]

2x2 grid at 1920x1080 (each tile 960x540), shot A (5 s) then shot B (3 s, with the line l002 at
0.5 s), 24 fps. Reads ~/ai-studio/scratch/engine-bakeoff/out/<engine>/<shot>/.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WORK = Path.home() / "ai-studio/scratch/engine-bakeoff"
LABEL = {
    "synfig-rigid": "Synfig, rigid limbs (today)",
    "synfig-bend": "Synfig, bendable limbs (baseline)",
    "blender-workbench": "Blender, mesh deform",
    "blender-eevee": "Blender EEVEE",
    "blender-cycles": "Blender Cycles",
    "opentoonz-plastic": "OpenToonz, Plastic mesh",
    "opentoonz-rigid": "OpenToonz, rigid",
}

ap = argparse.ArgumentParser()
ap.add_argument("out", type=Path)
ap.add_argument("--engines", default="synfig-rigid,synfig-bend,blender-workbench,opentoonz-plastic")
a = ap.parse_args()
engines = a.engines.split(",")
font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
tmp = WORK / "compare_frames"
shutil.rmtree(tmp, ignore_errors=True)
tmp.mkdir()


def frames(engine: str, shot: str) -> list[Path]:
    d = WORK / "out" / engine / shot
    d = d / "frames" if (d / "frames").is_dir() else d
    return sorted(d.glob("*.png"))


n = 0
for shot in ("s01_sh01", "s02_sh01"):
    sets = [frames(e, shot) for e in engines]
    for i in range(min(len(s) for s in sets)):
        canvas = Image.new("RGB", (1920, 1080))
        for k, (eng, s) in enumerate(zip(engines, sets, strict=True)):
            tile = Image.open(s[i]).convert("RGB").resize((960, 540))
            d = ImageDraw.Draw(tile)
            d.rectangle([0, 0, 11 + 15 * len(LABEL[eng]), 42], fill=(0, 0, 0))
            d.text((8, 6), LABEL[eng], fill=(255, 255, 255), font=font)
            canvas.paste(tile, ((k % 2) * 960, (k // 2) * 540))
        canvas.save(tmp / f"{n:04d}.png")
        n += 1
# audio: silence for shot A (5 s), then the line at 0.5 s into shot B
wav = WORK / "film/audio/dialogue/l002.wav"
subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-framerate",
        "24",
        "-i",
        str(tmp / "%04d.png"),
        "-i",
        str(wav),
        "-filter_complex",
        "[1:a]adelay=5500|5500,apad[a]",
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(a.out),
    ],
    check=True,
)
shutil.rmtree(tmp)
print(a.out, n, "frames")
