# ruff: noqa: E501, B007
"""Spike D-093: one character designed for rigging, proved with a 6 s clip.

    uv run --project studio_core python scripts/spikes/rigged_character_test.py WORK_DIR [--probe]
        [--skip-render]

WORK_DIR (default ~/ai-studio/scratch/rigged-character-test) gets:
  film/characters/mia     the flat puppet (`studio_core.puppet.flat`), audio linked from films/real-15s
  bake_wide.json, bake_close.json   one motion, two camera tracks (a matching cut with a short cross-fade)
  frames_wide/, frames_close/       Blender (transparent) renders of Mia only, 1920x1080
  clip.mp4, sheet.png               the result (composited over a layered 2.5D parallax plate)
  --probe: the old bake-off close-up (shot B) with the NEW Mia on magenta, defects counted the
           same way as the old Mia's (bakeoff_metrics.py), at 960x540, numbers in probe.json
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from studio_core.config import REPO_ROOT
from studio_core.engines.bake import FPS, bake_shot
from studio_core.engines.blender.launch import render
from studio_core.engines.face_sprite import write_sprites
from studio_core.puppet.flat import FlatSpec, build_flat_puppet

W, H = 1920, 1080
SECONDS = 6.0
N = round(SECONDS * FPS)
SCALE = 0.88  # round 3: the taller Mia (785 px) at 0.88 is as tall on screen as before
LINES = [("l001", 1.9), ("l003", 4.1)]


def setup_film(work: Path) -> Path:
    film = work / "film"
    build_flat_puppet(FlatSpec(), film / "characters" / "mia")
    audio = film / "audio"
    if not audio.exists():
        audio.symlink_to(REPO_ROOT / "films/real-15s/audio", target_is_directory=True)
    return film


def shot_spec(camera: dict, background: str = "plate", transparent: bool = True) -> dict:
    return {
        "schema_version": 1,
        "id": "rigged_test",
        "duration_s": SECONDS,
        "background": background,
        "transparent": transparent,
        "smooth": {},
        "characters": [
            {
                "id": "mia",
                "scale": SCALE,
                "position": [0.10, 0.92],
                "facing": "right",
                "path": [{"time_s": 1.7, "position": [0.42, 0.92], "ease": "ease_in_out"}],
                "actions": [
                    {"motion": "blink", "start_s": 0.0, "duration_s": SECONDS},
                    {"motion": "idle_breathe", "start_s": 0.0},
                    {
                        "motion": "walk_step",
                        "start_s": 0.0,
                        "duration_s": 1.7,
                        "params": {"energy": 0.55},
                    },
                    {
                        "motion": "wave_real",
                        "start_s": 1.7,
                        "params": {"energy": 0.6, "speed": 1.5, "side": "right", "principles": 0.4},
                    },
                    {"motion": "talk_gesture", "start_s": 3.6, "params": {"energy": 0.45}},
                ],
                "expressions": [
                    {"expr": "happy", "start_s": 0.0},
                    {"expr": "excited", "start_s": 1.8},
                    {"expr": "happy", "start_s": 3.7},
                ],
                "look": [
                    {"time_s": 0.0, "yaw": 0.0},
                    {"time_s": 3.3, "yaw": 0.0},
                    {"time_s": 4.0, "yaw": 0.55},
                    {"time_s": 5.0, "yaw": 0.55},
                    {"time_s": 5.8, "yaw": 0.0},
                ],
                "poses": [
                    {"time_s": 0.0, "bones": {"head": 0}},
                    {"time_s": 4.0, "bones": {"head": 7}},
                    {"time_s": 5.0, "bones": {"head": 7}},
                    {"time_s": 5.8, "bones": {"head": 0}},
                ],
            }
        ],
        "dialogue": [
            {"character": "mia", "line_id": lid, "text": "", "start_s": t} for lid, t in LINES
        ],
        "camera": camera,
    }


# One continuous camera (D-096): a real push-in from the walking framing to the close-up. The
# first clip dissolved between two framings and showed two Mias for five frames.
CAM = {
    "move": "track",
    "keys": [
        {"time_s": 0.0, "zoom": 1.0, "cx": 860, "cy": 540},
        {"time_s": 2.4, "zoom": 1.08, "cx": 830, "cy": 600},
        {"time_s": 3.8, "zoom": 1.28, "cx": 806, "cy": 630},
        {"time_s": 6.0, "zoom": 1.3, "cx": 806, "cy": 632},
    ],
}
# round 3: no key may crop the head or the boots; studio_core.framing.check_framing holds it
CAM_WIDE = CAM_CLOSE = CAM


# --------------------------------------------------------------------------- the 2.5D plate
LAYERS = (  # (name, parallax factor): 0 = fixed to the screen, 1 = moves with the camera like Mia
    ("sky", 0.0),
    ("far", 0.15),
    ("mid", 0.4),
    ("trees", 0.7),
    ("ground", 1.0),
    ("fore", 1.3),
)
CW, CH = 2880, 1620  # a layer canvas, centred on the stage: room for pan and zoom


def _blob(d: ImageDraw.ImageDraw, pts, fill):
    d.polygon(pts, fill=fill)


def make_layers() -> dict[str, Image.Image]:
    """Flat-style layers in Mia's palette family (solid fills, no gradients, no outlines)."""
    SS = 2
    out = {}

    def canvas():
        return Image.new("RGBA", (CW * SS, CH * SS), (0, 0, 0, 0))

    def fin(im):
        return im.resize((CW, CH), Image.LANCZOS)

    ox, oy = (CW - W) // 2, (CH - H) // 2  # stage origin inside the canvas

    def P(x, y):
        return ((x + ox) * SS, (y + oy) * SS)

    im = canvas()
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, CW * SS, CH * SS], fill="#bfe6ee")  # one flat sky colour
    d.rectangle(
        [0, int((oy + 560) * SS), CW * SS, CH * SS], fill="#d6efe6"
    )  # a pale band at the horizon
    for cx, cy, s in ((380, 170, 1.0), (1180, 110, 0.8), (1700, 230, 1.15)):  # flat clouds
        for dx, dy, r in ((-60, 8, 38), (-14, -12, 52), (44, 4, 42), (86, 14, 28)):
            d.ellipse(
                [
                    P(cx + dx * s - r * s, cy + dy * s - r * s),
                    P(cx + dx * s + r * s, cy + dy * s + r * s),
                ],
                fill="#ffffff",
            )
    d.ellipse([P(1500 - 70, 90 - 70), P(1500 + 70, 90 + 70)], fill="#fde9a0")  # the sun
    out["sky"] = fin(im)

    def hills(base, amp, period, colour, phase, step=40):
        im = canvas()
        d = ImageDraw.Draw(im)
        pts = [
            P(
                x,
                base
                - amp * math.sin((x + phase) / period)
                - 0.4 * amp * math.sin((x + phase) / (period * 0.43)),
            )
            for x in range(-ox - 40, W + ox + 40, step)
        ]
        pts += [(CW * SS, CH * SS), (0, CH * SS)]
        d.polygon(pts, fill=colour)
        return fin(im)

    out["far"] = hills(640, 90, 210, "#a9d7b0", 40)
    out["mid"] = hills(730, 70, 160, "#86c795", 200)

    im = canvas()
    d = ImageDraw.Draw(im)
    for x, h, r in (
        (140, 250, 92),
        (470, 210, 78),
        (820, 280, 100),
        (1330, 230, 84),
        (1650, 270, 96),
        (1900, 220, 80),
        (-160, 260, 90),
        (2180, 240, 88),
    ):
        base = 790
        d.rounded_rectangle([P(x - 13, base - h), P(x + 13, base + 6)], radius=8, fill="#8d6347")
        d.ellipse([P(x - r, base - h - r * 0.9), P(x + r, base - h + r * 0.9)], fill="#5aa86c")
        d.ellipse(
            [P(x - r * 0.25, base - h - r * 0.7), P(x + r * 0.7, base - h + r * 0.1)],
            fill="#6cba7c",
        )
    out["trees"] = fin(im)

    im = canvas()
    d = ImageDraw.Draw(im)  # the ground plane Mia stands on
    d.rectangle([P(-ox - 50, 800), (CW * SS, CH * SS)], fill="#73b87f")
    d.rectangle([P(-ox - 50, 815), (CW * SS, CH * SS)], fill="#68ad75")
    d.polygon(
        [P(-ox - 50, 975), P(W + ox + 50, 975), P(W + ox + 50, 1010), P(-ox - 50, 1010)],
        fill="#e7cf9a",
    )  # a path
    d.polygon(
        [P(-ox - 50, 1010), P(W + ox + 50, 1010), P(W + ox + 50, CH), P(-ox - 50, CH)],
        fill="#5da06b",
    )
    for x in range(-ox, W + ox, 130):  # a low fence behind
        d.rounded_rectangle([P(x, 770), P(x + 14, 840)], radius=4, fill="#d9b98a")
    d.rectangle([P(-ox, 790), P(W + ox, 802)], fill="#d9b98a")
    d.rectangle([P(-ox, 818), P(W + ox, 828)], fill="#d9b98a")
    out["ground"] = fin(im)

    im = canvas()
    d = ImageDraw.Draw(im)  # foreground tufts and flowers, low and at the sides
    for x in (-ox + 90, 150, 330, 1560, 1790, W + ox - 120):
        for dx in (-22, 0, 22):
            d.polygon(
                [P(x + dx - 9, 1090), P(x + dx, 1010 - abs(dx)), P(x + dx + 9, 1090)],
                fill="#4f9660",
            )
    for x, y, c in ((260, 1050, "#f06a6a"), (1640, 1044, "#fff2a8"), (1880, 1056, "#f9a3c0")):
        d.ellipse([P(x - 12, y - 12), P(x + 12, y + 12)], fill=c)
        d.line([P(x, y + 10), P(x, y + 46)], fill="#4f9660", width=5 * SS)
    out["fore"] = fin(im)
    return out


def view_of(layer: Image.Image, factor: float, cam: tuple[float, float, float]) -> Image.Image:
    """The layer as the camera (zoom, cx, cy in stage px) sees it: a layer at factor 0 stays put,
    factor 1 moves and scales with the camera. Bilinear crop of the big canvas."""
    zoom, cx, cy = cam
    z = 1 + (zoom - 1) * factor
    lx, ly = W / 2 + (cx - W / 2) * factor, H / 2 + (cy - H / 2) * factor  # centre in stage px
    ox, oy = (CW - W) / 2, (CH - H) / 2
    box = (lx + ox - W / 2 / z, ly + oy - H / 2 / z, lx + ox + W / 2 / z, ly + oy + H / 2 / z)
    return layer.transform((W, H), Image.EXTENT, box, Image.BILINEAR)


def to_screen(p: tuple[float, float], cam: tuple[float, float, float]) -> tuple[float, float]:
    zoom, cx, cy = cam
    return ((p[0] - cx) * zoom + W / 2, (p[1] - cy) * zoom + H / 2)


def shadow(cam, foot_px: tuple[float, float], width: float) -> Image.Image:
    sx, sy = to_screen(foot_px, cam)
    z = cam[0]
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)
    rx, ry = width * z, width * 0.16 * z
    d.ellipse([sx - rx, sy - ry, sx + rx, sy + ry], fill=255)
    return layer.filter(ImageFilter.GaussianBlur(10 * z)).point(lambda v: int(v * 0.30))


def composite(layers, frame_png: Path, cam, foot_px) -> Image.Image:
    base = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    for name, f in LAYERS:
        if name == "fore":
            break
        base.alpha_composite(view_of(layers[name], f, cam))
    sh = Image.new("RGBA", (W, H), (40, 70, 50, 0))
    sh.putalpha(shadow(cam, foot_px, 105 * SCALE))
    base.alpha_composite(sh)
    base.alpha_composite(Image.open(frame_png).convert("RGBA"))
    base.alpha_composite(view_of(layers["fore"], 1.3, cam))
    return base.convert("RGB")


# --------------------------------------------------------------------------- run
def foot_px(bake: dict, f: int) -> tuple[float, float]:
    """Where the ground under the hips is, in stage px (y down): the root joint's x, the ground line."""
    ch = bake["characters"][0]
    root = next(b for b, sp in ch["bones"].items() if sp["parent"] is None)
    return (ch["frames"][f]["bones"][root][0], H * 0.92)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "work",
        type=Path,
        nargs="?",
        default=Path.home() / "ai-studio/scratch/rigged-character-test",
    )
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--tag", default="v2", help="output names: clip_<tag>.mp4, sheet_<tag>.png")
    a = ap.parse_args()
    work = a.work.expanduser()
    work.mkdir(parents=True, exist_ok=True)
    film = setup_film(work)

    if a.probe:
        probe(work, film)
        return

    bake = bake_shot(film, shot_spec(CAM))
    write_sprites(bake, work / "sprites")
    (work / "bake.json").write_text(json.dumps(bake))
    if not a.skip_render:
        stats = render(
            work / "bake.json",
            work / "frames",
            engine="EEVEE",
            size=f"{W}x{H}",
            samples=8,
        )
        print(stats)
    layers = make_layers()
    out = work / "final_frames"
    out.mkdir(exist_ok=True)
    for f in range(N):
        cam = tuple(bake["camera_track"][f])
        composite(layers, work / "frames" / f"{f:04d}.png", cam, foot_px(bake, f)).save(
            out / f"{f:04d}.png"
        )
    mux(work, out, a.tag)
    sheet(work, out, bake, a.tag)


def mux(work: Path, frames: Path, tag: str) -> None:
    audio = REPO_ROOT / "films/real-15s/audio/dialogue"
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-framerate",
        str(FPS),
        "-i",
        str(frames / "%04d.png"),
    ]
    for lid, _ in LINES:
        cmd += ["-i", str(audio / f"{lid}.wav")]
    delays = "".join(
        f"[{i + 1}:a]adelay={int(t * 1000)}|{int(t * 1000)}[a{i}];"
        for i, (_, t) in enumerate(LINES)
    )
    mix = (
        "".join(f"[a{i}]" for i in range(len(LINES)))
        + f"amix=inputs={len(LINES)}:normalize=0,apad[aout]"
    )
    cmd += [
        "-filter_complex",
        delays + mix,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-t",
        str(SECONDS),
        "-c:v",
        "libx264",
        "-crf",
        "17",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        str(work / f"clip_{tag}.mp4"),
    ]
    subprocess.run(cmd, check=True)


def sheet(work: Path, frames: Path, bake: dict, tag: str) -> None:
    """6 x 2 frames across the clip, and a row of face close-ups (rest, blink, mouth shapes, the turn)."""
    tw, th = 560, 315
    picks = [round(i * (N - 1) / 11) for i in range(12)]
    img = Image.new("RGB", (tw * 6, th * 3), (255, 255, 255))
    for i, f in enumerate(picks):
        img.paste(
            Image.open(frames / f"{f:04d}.png").convert("RGB").resize((tw, th), Image.LANCZOS),
            ((i % 6) * tw, (i // 6) * th),
        )
    ch = bake["characters"][0]
    heads = {}
    for f, fr in enumerate(ch["frames"]):
        p = fr["face"]
        key = (
            "blink" if p["eye_open"] < 0.15 else None,
            "open" if p["mouth"]["open"] > 0.8 else None,
            "round" if p["mouth"]["round"] > 0.75 else None,
            "turn" if p["yaw"] > 0.5 else None,
        )
        for k in key:
            if k and k not in heads:
                heads[k] = fr["head"]
    order = ["blink", "open", "round", "turn"]
    first = ch["frames"][0]["head"]
    tiles = [first] + [heads.get(k, first) for k in order]
    cx, top, fw, fh = ch["face"]["layout"]["box"]
    cw_ = fw * 1.24
    box = (cx - cw_ / 2, top + fh * 0.12, cx + cw_ / 2, top + fh * 0.12 + cw_ * (th / (tw - 20)))
    for i, path in enumerate(tiles):
        hd = Image.open(path).convert("RGBA")
        bg = Image.new("RGBA", hd.size, "#bfe6ee")
        bg.alpha_composite(hd)
        img.paste(
            bg.convert("RGB")
            .crop(tuple(round(v) for v in box))
            .resize((tw - 20, th), Image.LANCZOS),
            (i * tw + 10, th * 2),
        )
    img.save(work / f"sheet_{tag}.png")


def probe(work: Path, film: Path) -> None:
    """The bake-off's Mia close-up (shot B) with the new Mia on the magenta probe, defects counted
    with the same checker (`preview.sweep.check_frame`) as the old numbers in engine-bakeoff/metrics.json."""
    from studio_core.preview.sweep import check_frame

    sys.path.insert(0, str(REPO_ROOT / "scripts/spikes"))
    from bakeoff_shots import shot_b

    spec = shot_b()
    spec["characters"][0]["scale"] = 1.0
    spec.update(background="probe", smooth={}, transparent=False)
    spec["characters"][0]["look"] = [
        {"time_s": 0.0, "yaw": 0.0},
        {"time_s": 0.9, "yaw": 0.4},
        {"time_s": 1.8, "yaw": 0.4},
        {"time_s": 2.6, "yaw": 0.0},
    ]
    bg = film / "backgrounds" / "probe"
    bg.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1920, 1080), (255, 0, 255)).save(bg / "plate.png")
    for mode in ("smooth",):
        bake = bake_shot(film, spec)
        write_sprites(bake, work / "probe_sprites")
        bj = work / f"probe_bake_{mode}.json"
        bj.write_text(json.dumps(bake))
        out = work / f"probe_{mode}"
        print(render(bj, out, engine="EEVEE", size="960x540", samples=8))
        counts = {
            "frames": 0,
            "frames_with_defect": 0,
            "hole": 0,
            "seam": 0,
            "detached": 0,
            "largest_px": 0,
        }
        for p in sorted(out.glob("*.png")):
            ds = check_frame(np.array(Image.open(p).convert("RGB").resize((960, 540))))
            counts["frames"] += 1
            counts["frames_with_defect"] += bool(ds)
            for d in ds:
                counts[d.kind] = counts.get(d.kind, 0) + 1
                counts["largest_px"] = max(counts["largest_px"], d.area_px)
        print(mode, counts)
        (work / f"probe_{mode}.json").write_text(json.dumps(counts))


if __name__ == "__main__":
    main()
