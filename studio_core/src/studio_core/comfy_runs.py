"""Running ComfyUI graphs for a film: start, make room, run, collect, record (task 4.1, D-047).

    run = run_graph(film_root, "design", graph, out_dir=..., params={...}, seed=1234)
    run.outputs           # images copied into the film folder
    free_comfy()          # before LLM or music work (one large model at a time)

What every image job needs, in one place:

- **The style** comes from the film (`film_style`): the film's locked style, or the machine's
  default when the film has none yet (D-025). Graph builders take it as a parameter.
- **Room on the GPU** (`make_room_for_images`): Ollama's models are unloaded, and the job is
  refused while music is being composed (ACE-Step needs the whole budget, D-041). ComfyUI is
  started on demand (`scripts/comfy_server.sh`) and waited for.
- **A record next to every output:** `run.json` holds the exact graph, the parameters, the seed,
  the style, ComfyUI's version and the timings. Any image can be regenerated, or explained,
  from its folder.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio_core.comfy import Comfy, ComfyError
from studio_core.config import REPO_ROOT, StudioConfig, load_config
from studio_core.ollama import Ollama

START_SCRIPT = REPO_ROOT / "scripts" / "comfy_server.sh"
START_TIMEOUT_S = 180


class ImageJobError(RuntimeError):
    """An image job was refused or failed. The message says what to fix."""


@dataclass
class RunRecord:
    kind: str  # e.g. "design", "background", "depth"
    style: str | None
    seed: int | None
    params: dict[str, Any]
    graph: dict[str, Any]
    outputs: list[str] = field(default_factory=list)  # relative to the run folder
    seconds: float = 0.0
    comfyui: str = ""
    created: str = ""

    def save(self, folder: Path) -> Path:
        path = folder / "run.json"
        path.write_text(json.dumps(asdict(self), indent=1) + "\n")
        return path


def film_style(film_root: Path, cfg: StudioConfig | None = None) -> str:
    """The film's locked style, or the machine's default style if the film has none yet."""
    cfg = cfg or load_config()
    film_json = film_root / "film.json"
    if film_json.is_file():
        style = json.loads(film_json.read_text()).get("style")
        if style:
            return style
    return cfg.get("comfyui", "default_style", "storybook")


def composing_music() -> bool:
    """True while ACE-Step is generating (it needs the whole memory budget)."""
    probe = subprocess.run(["pgrep", "-f", "acestep_compose.py"], capture_output=True, text=True)
    return bool(probe.stdout.strip())


def make_room_for_images(cfg: StudioConfig) -> list[str]:
    """Unload Ollama's models; refuse while music is composing. Returns what was unloaded."""
    if composing_music():
        raise ImageJobError("music is being composed (ACE-Step); wait for it to finish")
    client = Ollama(cfg.get("services", "ollama_url"))
    try:
        names = [m["name"] for m in client.loaded()]
    except OSError:
        return []  # Ollama not running
    for name in names:
        client.unload(name)
    return names


def ensure_comfy(cfg: StudioConfig, start: bool = True) -> Comfy:
    """A client for a running ComfyUI, starting it (scripts/comfy_server.sh) if needed."""
    comfy = Comfy(cfg.get("services", "comfyui_url"))
    try:
        comfy.system_stats()
        return comfy
    except OSError:
        if not start:
            raise ImageJobError(
                "ComfyUI isn't running; start it with scripts/comfy_server.sh"
            ) from None
    subprocess.run(["bash", str(START_SCRIPT)], check=True, capture_output=True)
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            comfy.system_stats()
            return comfy
        except OSError:
            time.sleep(2)
    raise ImageJobError(f"ComfyUI didn't start within {START_TIMEOUT_S}s; see its server.log")


def run_graph(
    film_root: Path,
    kind: str,
    graph: dict[str, Any],
    *,
    out_dir: Path,
    params: dict[str, Any] | None = None,
    seed: int | None = None,
    style: str | None = None,
    names: list[str] | None = None,
    uploads: dict[str, Path] | None = None,
    cfg: StudioConfig | None = None,
) -> RunRecord:
    """Run one graph and keep its outputs in `out_dir` (created fresh), with a run.json.

    `names` renames the outputs in order (e.g. ["candidate_1.png"]); `uploads` maps a graph
    LoadImage input value to a local image to upload first (its uploaded name is substituted)."""
    cfg = cfg or load_config()
    make_room_for_images(cfg)
    comfy = ensure_comfy(cfg)
    graph = json.loads(json.dumps(graph))  # don't mutate the caller's graph
    for placeholder, path in (uploads or {}).items():
        uploaded = comfy.upload_image(path)
        for node in graph.values():
            for key, value in node["inputs"].items():
                if value == placeholder:
                    node["inputs"][key] = uploaded
    try:
        with tempfile.TemporaryDirectory() as tmp:
            produced, seconds = comfy.run(graph, Path(tmp))
            if out_dir.exists():
                shutil.rmtree(out_dir)
            out_dir.mkdir(parents=True)
            outputs = []
            for i, path in enumerate(sorted(produced)):
                name = names[i] if names and i < len(names) else path.name
                shutil.move(str(path), out_dir / name)
                outputs.append(name)
    except ComfyError as e:
        raise ImageJobError(f"ComfyUI refused the {kind} graph: {e}") from None
    version = comfy.system_stats().get("system", {}).get("comfyui_version", "")
    record = RunRecord(
        kind=kind,
        style=style,
        seed=seed,
        params=params or {},
        graph=graph,
        outputs=outputs,
        seconds=round(seconds, 2),
        comfyui=version,
        created=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    record.save(out_dir)
    return record


def free_comfy(cfg: StudioConfig | None = None) -> bool:
    """Ask a running ComfyUI to unload its models. False if it isn't running."""
    cfg = cfg or load_config()
    try:
        Comfy(cfg.get("services", "comfyui_url")).free_memory()
        return True
    except OSError:
        return False
