"""Regenerate the saved text-to-image workflows in comfy_workflows/ from the style builder.

    uv run scripts/export_workflows.py

The saved files are the default style ("storybook") with the sample puppet-sheet prompt; they
exist so a human can load them in the ComfyUI UI. Code builds workflows with
studio_core.comfy_graphs.txt2img for any style. A test checks the files match the builder.
"""

from __future__ import annotations

import json
import sys

from studio_core.comfy_graphs import txt2img
from studio_core.config import REPO_ROOT
from studio_core.models import load_manifest

SAMPLE_STYLE = "storybook"
SAMPLE_PROMPT = (
    "a cheerful little rabbit character for a preschool cartoon, full body, front view, standing "
    "in a neutral pose with arms held slightly away from the body, plain white background"
)
EXPORTS = {
    "txt2img_sdxl.json": {"fast": False, "filename_prefix": "txt2img_sdxl"},
    "txt2img_sdxl_lightning.json": {"fast": True, "filename_prefix": "txt2img_sdxl_lightning"},
}


def build(name: str) -> dict:
    return txt2img(load_manifest(), SAMPLE_STYLE, SAMPLE_PROMPT, **EXPORTS[name])


def main() -> int:
    for name in EXPORTS:
        path = REPO_ROOT / "comfy_workflows" / name
        path.write_text(json.dumps(build(name), indent=2) + "\n")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
