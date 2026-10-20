"""ComfyUI smoke test through the HTTP API: text-to-image, then SAM 2 and depth on that image.

    scripts/comfy_server.sh                     # start ComfyUI first
    uv run scripts/comfy_smoke.py               # fast (Lightning) txt2img + SAM 2 + depth
    uv run scripts/comfy_smoke.py --normal      # also the 25-step txt2img workflow

Outputs go to ~/ai-studio/scratch/smoke/comfy/. Ollama models are unloaded first (Mac memory
rule: one large model at a time) and ComfyUI's memory is freed at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from studio_core.comfy import Comfy
from studio_core.config import REPO_ROOT, load_config
from studio_core.ollama import Ollama

WORKFLOWS = REPO_ROOT / "comfy_workflows"
OUT = Path.home() / "ai-studio" / "scratch" / "smoke" / "comfy"


def load(name: str) -> dict:
    return json.loads((WORKFLOWS / name).read_text())


def node(workflow: dict, class_type: str) -> dict:
    return next(n for n in workflow.values() if n["class_type"] == class_type)


def check_image(path: Path, size: tuple[int, int] | None = None) -> str:
    with Image.open(path) as im:
        extrema = im.convert("L").getextrema()
        assert extrema[0] != extrema[1], f"{path.name} is a flat image {extrema}"
        if size:
            assert im.size == size, f"{path.name} is {im.size}, expected {size}"
        return f"{im.size[0]}x{im.size[1]} {im.mode}, luminance range {extrema}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--normal", action="store_true", help="also run the 25-step workflow")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cfg = load_config()
    comfy = Comfy(cfg.get("services", "comfyui_url"))
    stats = comfy.system_stats()
    devices = [d["name"] for d in stats.get("devices", [])]
    print(f"ComfyUI {stats['system'].get('comfyui_version')} on {devices}")

    ollama = Ollama(cfg.get("services", "ollama_url"))
    for m in ollama.loaded():
        print(f"unloading Ollama model {m['name']} (memory rule)")
        ollama.unload(m["name"])

    variants = ["txt2img_sdxl_lightning.json"] + (["txt2img_sdxl.json"] if args.normal else [])
    image = None
    for name in variants:
        wf = load(name)
        node(wf, "KSampler")["inputs"]["seed"] = args.seed
        paths, seconds = comfy.run(wf, OUT / "txt2img")
        image = paths[0]
        print(f"OK {name}: {seconds:.1f}s -> {image} ({check_image(image, (1024, 1024))})")

    assert image is not None
    uploaded = comfy.upload_image(image)

    wf = load("sam2_points.json")
    node(wf, "LoadImage")["inputs"]["image"] = uploaded
    # Point prompt at the image centre, where the character stands in the puppet-sheet prompt.
    node(wf, "Sam2Segmentation")["inputs"]["coordinates_positive"] = json.dumps(
        [{"x": 512, "y": 480}, {"x": 512, "y": 600}]
    )
    paths, seconds = comfy.run(wf, OUT / "sam2")
    with Image.open(paths[0]) as mask:
        histogram = mask.convert("L").histogram()  # 256 bins of pixel counts
        covered = sum(histogram[128:]) / (mask.width * mask.height)
    assert 0.01 < covered < 0.9, f"mask covers {covered:.1%} of the image"
    print(f"OK sam2_points.json: {seconds:.1f}s -> {paths[0]} (mask covers {covered:.1%})")

    wf = load("depth_anything_v2.json")
    node(wf, "LoadImage")["inputs"]["image"] = uploaded
    paths, seconds = comfy.run(wf, OUT / "depth")
    print(f"OK depth_anything_v2.json: {seconds:.1f}s -> {paths[0]} ({check_image(paths[0])})")

    comfy.free_memory()
    print("ComfyUI memory freed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
