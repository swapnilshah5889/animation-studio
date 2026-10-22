"""Stage benchmarks for this machine. Results are appended to docs/benchmarks.md as Markdown tables.

One subcommand per pipeline stage:

    uv run scripts/benchmark.py llm        # director LLMs: load, tok/s, memory, unload time
    uv run scripts/benchmark.py vision     # vision QA model: seconds per frame check
    uv run scripts/benchmark.py sdxl       # SDXL 1024x1024: normal steps vs speed LoRA
    uv run scripts/benchmark.py styles     # every downloaded style: character + background + grid
    uv run scripts/benchmark.py segment    # SAM 2 and depth: seconds per image (ComfyUI API)
    uv run scripts/benchmark.py tts        # Kokoro real-time factor
    uv run scripts/benchmark.py music      # ACE-Step: seconds per 30 s of music
    uv run scripts/benchmark.py rhubarb    # seconds per 10 s of audio
    uv run scripts/benchmark.py synfig     # seconds per 1080p frame, simple rigged sample
    uv run scripts/benchmark.py encode     # ffmpeg and melt: 60 s at 1080p
    uv run scripts/benchmark.py switch     # unload one big model and load the next

Add --dry-run to print the table without touching docs/benchmarks.md. Scratch files go to
~/ai-studio/scratch/bench (outside the repo). Close other heavy apps first: numbers are only
comparable on a quiet machine.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from studio_core.comfy import Comfy
from studio_core.comfy_graphs import txt2img
from studio_core.config import REPO_ROOT, StudioConfig, expand_path, load_config
from studio_core.memwatch import GB, MemoryWatch
from studio_core.models import comfy_models_dir, load_manifest
from studio_core.ollama import Ollama, Timings

BENCH_MD = REPO_ROOT / "docs" / "benchmarks.md"
SCRATCH = Path.home() / "ai-studio" / "scratch" / "bench"
WORKFLOWS = REPO_ROOT / "comfy_workflows"


# --------------------------------------------------------------------------- helpers


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def report(title: str, body: str, notes: list[str], dry_run: bool) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    section = f"\n### {title}\n\n_Measured {stamp}._\n\n{body}\n"
    if notes:
        section += "\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    print(section)
    if not dry_run:
        with BENCH_MD.open("a") as fh:
            fh.write(section)
        print(f"(appended to {BENCH_MD.relative_to(REPO_ROOT)})")


def timed(cmd: list[str], **kwargs: Any) -> tuple[float, subprocess.CompletedProcess[str]]:
    start = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return elapsed, proc


def timed_with_footprint(cmd: list[str], **kwargs: Any) -> tuple[float, float, str]:
    """Run under /usr/bin/time -l. Returns (seconds, peak memory footprint GB, stdout).

    On Apple Silicon the "peak memory footprint" includes GPU (Metal) allocations, because GPU
    memory is ordinary unified memory owned by the process.
    """
    elapsed, proc = timed(["/usr/bin/time", "-l", *cmd], **kwargs)
    footprint = 0.0
    for line in proc.stderr.splitlines():
        if "peak memory footprint" in line:
            footprint = int(line.split()[0]) / GB
    return elapsed, footprint, proc.stdout


def audio_seconds(path: Path, cfg: StudioConfig) -> float:
    _, proc = timed(
        [
            str(cfg.path("tools", "ffprobe")),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    return float(proc.stdout.strip())


def env_python(cfg: StudioConfig, name: str) -> Path:
    """Interpreter of an isolated env from [envs] in config/studio.toml."""
    return expand_path(cfg.get("envs", name)["python"])


def unload_everything(client: Ollama) -> list[str]:
    """Unload every Ollama model so each measurement starts from the same memory state."""
    names = [m["name"] for m in client.loaded()]
    for name in names:
        client.unload(name)
    return names


# --------------------------------------------------------------------------- LLM


DIRECTOR_TASK = (
    "You are the director of a children's animated film studio. Read the studio architecture "
    "below, then write a JSON shot list for a 20-second scene in which a small rabbit named Pip "
    "finds a lost kite in a meadow and returns it to a friend. Use 4 shots. Each shot needs id, "
    "duration_s, background, camera, characters (with actions and expressions) and dialogue. "
    "Answer with JSON only.\n\n"
)


def think_for(model: str, requested: bool | str) -> bool | str:
    """gpt-oss cannot switch reasoning off, only lower it; map False to its lowest level."""
    if model.startswith("gpt-oss") and requested is False:
        return "low"
    return requested


def bench_llm(cfg: StudioConfig, args: argparse.Namespace) -> None:
    client = Ollama(cfg.get("services", "ollama_url"))
    models = args.models or cfg.get("ollama", "director_models")
    context_doc = (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text()
    evicted = unload_everything(client)

    rows, notes = [], []
    for model in models:
        load_s = client.load(model)
        resident = next((m for m in client.loaded() if m["name"] == model), {})
        runs = []
        with MemoryWatch() as mem:
            for i in range(args.runs):
                # A different first line per run defeats Ollama's prompt (KV) cache, so prompt
                # processing is really measured each time.
                prompt = f"Run {i + 1}.\n" + DIRECTOR_TASK + context_doc
                resp = client.chat(
                    model,
                    [{"role": "user", "content": prompt}],
                    think=think_for(model, args.think),
                    options={"num_predict": args.max_tokens, "temperature": 0, "num_ctx": 8192},
                )
                runs.append(Timings.from_response(resp))
        unload_s = client.unload(model)
        avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
        rows.append(
            [
                model,
                f"{resident.get('size', 0) / GB:.1f} GB",
                f"{load_s:.1f}",
                f"{avg([r.prompt_tokens for r in runs]):.0f}",
                f"{avg([r.prompt_tps for r in runs]):.0f}",
                f"{avg([r.gen_tps for r in runs]):.1f}",
                f"{unload_s:.2f}",
                f"{mem.peak_used / GB:.1f} GB / {mem.min_free_pct}%",
            ]
        )
    if evicted:
        notes.append(f"Unloaded first so every model starts cold: {', '.join(evicted)}.")
    notes.append(
        f"{args.runs} runs per model, num_ctx 8192, temperature 0, up to {args.max_tokens} "
        f"generated tokens, think={args.think} (gpt-oss: 'low', it cannot be switched off). "
        "Prompt = director task + ARCHITECTURE.md."
    )
    notes.append("Cold load = wall clock from SSD to ready. Peak used = whole-system memory.")
    headers = [
        "Model",
        "In memory",
        "Cold load s",
        "Prompt tok",
        "Prompt tok/s",
        "Gen tok/s",
        "Unload s",
        "Peak used / min free",
    ]
    report("Director LLMs", table(headers, rows), notes, args.dry_run)


def bench_vision(cfg: StudioConfig, args: argparse.Namespace) -> None:
    client = Ollama(cfg.get("services", "ollama_url"))
    model = args.model or cfg.get("ollama", "vision_model")
    image = Path(args.image).expanduser()
    b64 = base64.b64encode(image.read_bytes()).decode()
    question = (
        "You check frames of a children's cartoon. Describe this image as JSON with keys "
        "'characters' (list), 'background' (string), 'problems' (list of visual defects) and "
        "'kid_safe' (boolean)."
    )
    unload_everything(client)
    load_s = client.load(model)
    times, answer = [], ""
    with MemoryWatch() as mem:
        for _ in range(args.runs):
            start = time.perf_counter()
            resp = client.generate(model, question, images=[b64], options={"temperature": 0})
            times.append(time.perf_counter() - start)
            answer = resp.get("response", "")
    resident = next((m for m in client.loaded() if m["name"] == model), {})
    client.unload(model)
    rows = [
        [
            model,
            f"{resident.get('size', 0) / GB:.1f} GB",
            f"{load_s:.1f}",
            f"{min(times):.1f}",
            f"{sum(times) / len(times):.1f}",
            mem.summary(),
        ]
    ]
    notes = [f"Image: {image.name}. {args.runs} runs.", f"Sample answer: `{answer.strip()[:200]}`"]
    headers = ["Model", "In memory", "Cold load s", "Best s/frame", "Avg s/frame", "Memory"]
    report("Vision QA", table(headers, rows), notes, args.dry_run)


# --------------------------------------------------------------------------- ComfyUI


def load_workflow(name: str) -> dict[str, Any]:
    return json.loads((WORKFLOWS / name).read_text())


def set_inputs(workflow: dict[str, Any], class_type: str, **inputs: Any) -> None:
    """Set inputs on every node of a class (workflows here have one node per class)."""
    for node in workflow.values():
        if node["class_type"] == class_type:
            node["inputs"].update(inputs)


def bench_sdxl(cfg: StudioConfig, args: argparse.Namespace) -> None:
    comfy = Comfy(cfg.get("services", "comfyui_url"))
    unload_everything(Ollama(cfg.get("services", "ollama_url")))
    out = SCRATCH / "sdxl"
    variants = [
        ("normal", "txt2img_sdxl.json", {}),
        ("speed LoRA", "txt2img_sdxl_lightning.json", {}),
    ]
    rows = []
    for label, wf_name, _ in variants:
        wf = load_workflow(wf_name)
        times = []
        with MemoryWatch() as mem:
            for i in range(args.runs + 1):  # +1 warm-up (model load, Metal shader compile)
                set_inputs(wf, "KSampler", seed=1000 + i)
                _, elapsed = comfy.run(wf, out)
                times.append(elapsed)
        sampler = next(n["inputs"] for n in wf.values() if n["class_type"] == "KSampler")
        rows.append(
            [
                label,
                sampler["steps"],
                sampler["cfg"],
                f"{times[0]:.1f}",
                f"{min(times[1:]):.1f}",
                f"{sum(times[1:]) / args.runs:.1f}",
                mem.summary(),
            ]
        )
    comfy.free_memory()
    headers = ["Variant", "Steps", "CFG", "First (cold) s", "Best s", "Avg s", "Memory"]
    notes = [f"1024x1024, batch 1, {args.runs} warm runs after one cold run, ComfyUI HTTP API."]
    report("SDXL text-to-image", table(headers, rows), notes, args.dry_run)


STYLE_SUBJECTS = {
    "character": (
        "a cheerful little rabbit character for a preschool cartoon, full body, front view, "
        "standing in a neutral pose with arms held slightly away from the body, plain white "
        "background",
        (1024, 1024),
    ),
    "background": (
        "a sunny meadow with soft rolling hills, a few round trees and flowers, a winding path, "
        "wide establishing shot, no characters, background for a children's cartoon",
        (1344, 768),
    ),
}


def make_grid(rows: list[tuple[str, list[tuple[str, Path]]]], out: Path) -> Path:
    """Label + thumbnails per row, so the owner can compare styles at a glance."""
    from PIL import Image, ImageDraw, ImageFont

    thumb_h, label_w, pad = 300, 260, 12
    font = ImageFont.load_default(size=20)
    cells = [[(cap, Image.open(path).convert("RGB")) for cap, path in cols] for _, cols in rows]
    widths = [sum(int(im.width * thumb_h / im.height) + pad for _, im in row) for row in cells]
    grid = Image.new(
        "RGB", (label_w + max(widths) + pad, len(rows) * (thumb_h + 40) + pad), "white"
    )
    draw = ImageDraw.Draw(grid)
    for r, ((label, _), row) in enumerate(zip(rows, cells, strict=True)):
        y = pad + r * (thumb_h + 40)
        draw.multiline_text((pad, y + 10), label, fill="black", font=font, spacing=6)
        x = label_w
        for caption, im in row:
            w = int(im.width * thumb_h / im.height)
            grid.paste(im.resize((w, thumb_h)), (x, y))
            draw.text((x, y + thumb_h + 6), caption, fill="black", font=font)
            x += w + pad
    grid.save(out)
    return out


def bench_styles(cfg: StudioConfig, args: argparse.Namespace) -> None:
    comfy = Comfy(cfg.get("services", "comfyui_url"))
    manifest = load_manifest()
    models_dir = comfy_models_dir(cfg)
    style_ids = args.styles or [
        st
        for st in manifest.styles
        if all(f.is_present(models_dir) for f in manifest.style_files(st))
    ]
    out = Path.home() / "ai-studio" / "scratch" / "style-compare"
    out.mkdir(parents=True, exist_ok=True)
    unload_everything(Ollama(cfg.get("services", "ollama_url")))

    rows, grid_rows = [], []
    with MemoryWatch() as mem:
        for style_id in style_ids:
            comfy.free_memory()  # each style starts cold, like a real switch
            style = manifest.styles[style_id]
            runs = [("character", True), ("character", False), ("background", False)]
            times, images = {}, []
            for subject, fast in runs:
                prompt, (w, h) = STYLE_SUBJECTS[subject]
                variant = "fast" if fast else "normal"
                wf = txt2img(
                    manifest,
                    style_id,
                    prompt,
                    fast=fast,
                    seed=args.seed,
                    width=w,
                    height=h,
                    filename_prefix=f"{style_id}_{subject}_{variant}",
                )
                paths, seconds = comfy.run(wf, out)
                steps = style.settings(fast)["steps"]
                times[(subject, variant)] = f"{seconds:.0f} ({steps} st)"
                images.append((f"{subject}, {variant} ({steps} steps, {seconds:.0f}s)", paths[0]))
            commercial = manifest.style_commercial(style_id)
            rows.append(
                [
                    style_id,
                    commercial,
                    times[("character", "fast")],
                    times[("character", "normal")],
                    times[("background", "normal")],
                ]
            )
            grid_rows.append((f"{style_id}\ncommercial: {commercial}", images))
    comfy.free_memory()
    grid = make_grid(grid_rows, out / "grid.png")
    headers = [
        "Style",
        "Commercial",
        "Character fast s (first incl. load)",
        "Character normal s",
        "Background normal s (1344x768)",
    ]
    notes = [
        f"Same seed ({args.seed}) and prompts for every style; the style adds its own trigger "
        "words and negative prompt (config/models.toml). Each style starts cold (model load is in "
        "its first column).",
        f"Image grid (not committed, generated media): `{grid}`",
        f"Memory across the run: {mem.summary()}",
    ]
    report("Style comparison (switcher)", table(headers, rows), notes, args.dry_run)


def bench_segment(cfg: StudioConfig, args: argparse.Namespace) -> None:
    comfy = Comfy(cfg.get("services", "comfyui_url"))
    image_name = comfy.upload_image(Path(args.image).expanduser())
    rows = []
    for label, wf_name in (
        ("SAM 2", "sam2_points.json"),
        ("Depth Anything V2 Small", "depth_anything_v2.json"),
    ):
        wf = load_workflow(wf_name)
        set_inputs(wf, "LoadImage", image=image_name)
        times = []
        with MemoryWatch() as mem:
            for _ in range(args.runs + 1):
                comfy.free_memory() if not times else None  # first run cold
                _, elapsed = comfy.run(wf, SCRATCH / "segment")
                times.append(elapsed)
        rows.append([label, f"{times[0]:.1f}", f"{min(times[1:]):.2f}", mem.summary()])
    comfy.free_memory()
    headers = ["Model", "Cold s", "Warm s/image", "Memory"]
    report("SAM 2 and depth", table(headers, rows), [f"Input: {args.image}"], args.dry_run)


# --------------------------------------------------------------------------- audio


SAMPLE_LINES = [
    "Hi Bunny! Look what I found in the tall grass. It's a red kite with a long yellow tail!",
    "Oh, thank you, Pip! I thought the wind had carried it all the way to the mountains.",
]


def bench_tts(cfg: StudioConfig, args: argparse.Namespace) -> None:
    out = SCRATCH / "tts"
    out.mkdir(parents=True, exist_ok=True)
    rows, walls = [], []
    for device in ("mps", "cpu"):  # a small model: is the GPU even worth it?
        cmd = [
            str(env_python(cfg, "kokoro")),
            str(REPO_ROOT / "scripts" / "audio" / "kokoro_say.py"),
            "--out-dir",
            str(out),
            "--voice",
            cfg.get("audio", "kokoro_voice"),
            "--device",
            device,
            "--repeat",
            str(args.runs),
            *SAMPLE_LINES,
        ]
        elapsed, footprint, stdout = timed_with_footprint(cmd)
        result = json.loads(stdout.strip().splitlines()[-1])
        walls.append(f"{device} {elapsed:.1f}s")
        rows.append(
            [
                f"Kokoro-82M ({result['device']})",
                f"{result['load_s']:.1f}",
                f"{result['audio_s']:.1f}",
                f"{result['synth_s']:.1f}",
                f"{result['synth_s'] / result['audio_s']:.3f}",
                f"{footprint:.1f} GB",
            ]
        )
    headers = ["Model", "Load s", "Audio s", "Synth s", "RTF (lower = faster)", "Peak footprint"]
    notes = [
        f"RTF = synthesis time / audio duration, {args.runs} passes over 2 lines after a warm-up.",
        f"Whole-process wall clock (includes Python and torch import): {', '.join(walls)}.",
    ]
    report("Text-to-speech", table(headers, rows), notes, args.dry_run)


def bench_rhubarb(cfg: StudioConfig, args: argparse.Namespace) -> None:
    rhubarb = cfg.path("tools", "rhubarb")
    wav = Path(args.wav).expanduser()
    dialog = Path(args.dialog).expanduser() if args.dialog else None
    seconds = audio_seconds(wav, cfg)
    cmd = [str(rhubarb), "-f", "json", "--machineReadable", str(wav)]
    if dialog:
        cmd += ["--dialogFile", str(dialog)]
    times = [timed(cmd)[0] for _ in range(args.runs)]
    per10 = min(times) / seconds * 10
    rows = [["rhubarb (pocketSphinx)", f"{seconds:.1f}", f"{min(times):.1f}", f"{per10:.1f}"]]
    headers = ["Tool", "Audio s", "Best wall s", "s per 10 s of audio"]
    report(
        "Lip-sync (Rhubarb)",
        table(headers, rows),
        [f"Input {wav.name}, dialog text {'given' if dialog else 'not given'}."],
        args.dry_run,
    )


def bench_music(cfg: StudioConfig, args: argparse.Namespace) -> None:
    out = SCRATCH / "music"
    unload_everything(Ollama(cfg.get("services", "ollama_url")))
    cmd = [
        str(env_python(cfg, "ace_step")),
        str(REPO_ROOT / "scripts" / "audio" / "acestep_compose.py"),
        "--out-dir",
        str(out),
        "--duration",
        str(args.duration),
        "--precision",
        args.precision,
        *(["--no-mlx-dit"] if args.no_mlx_dit else []),
        *(["--no-mlx-vae"] if args.no_mlx_vae else []),
    ]
    with MemoryWatch() as mem:
        elapsed, footprint, stdout = timed_with_footprint(cmd)
    result = json.loads(stdout.strip().splitlines()[-1])
    rows = [
        [
            f"ACE-Step 1.5 turbo ({'PyTorch/MPS' if args.no_mlx_dit else 'MLX'} DiT, "
            f"{args.precision}, {'PyTorch' if args.no_mlx_vae else 'MLX'} VAE, "
            f"{args.duration:g} s)",
            f"{result['load_s']:.0f}",
            f"{result['gen_s']:.0f}",
            f"{elapsed:.0f}",
            f"{footprint:.1f} GB",
            mem.summary(),
        ]
    ]
    headers = ["Model", "Load s", "Generate s", "Process wall s", "Peak footprint", "System"]
    notes = [
        *result.get("notes", []),
        "Peak footprint counts the process's own pages, including GPU/MLX buffers and pages that "
        "were compressed or swapped; it can exceed physical RAM.",
    ]
    report("Music (ACE-Step)", table(headers, rows), notes, args.dry_run)


# --------------------------------------------------------------------------- engines


def bench_synfig(cfg: StudioConfig, args: argparse.Namespace) -> None:
    synfig = cfg.path("tools", "synfig")
    sif = Path(args.sif).expanduser()
    out = SCRATCH / "synfig"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    cmd = [
        str(synfig),
        str(sif),
        "-t",
        "png",
        "-w",
        "1920",
        "-h",
        "1080",
        "--begin-time",
        "0",
        "--end-time",
        f"{args.frames - 1}f",
        "-o",
        str(out / "f.png"),
    ]
    if args.threads:
        cmd += ["-T", str(args.threads)]
    with MemoryWatch() as mem:
        elapsed, _ = timed(cmd)
    frames = len(list(out.glob("*.png")))
    rows = [[sif.name, frames, f"{elapsed:.1f}", f"{elapsed / max(frames, 1):.2f}", mem.summary()]]
    headers = ["Scene", "Frames", "Total s", "s per 1080p frame", "Memory"]
    report("Synfig render", table(headers, rows), [f"Command: `{' '.join(cmd[1:])}`"], args.dry_run)


def make_frames(cfg: StudioConfig, seconds: int, fps: int) -> Path:
    """A 1080p PNG sequence (what Synfig hands to the encoder), generated once and cached."""
    frames = SCRATCH / f"frames_{seconds}s_{fps}fps"
    if len(list(frames.glob("*.png"))) == seconds * fps:
        return frames
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    timed(
        [
            str(cfg.path("tools", "ffmpeg")),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1920x1080:rate={fps}:duration={seconds}",
            str(frames / "%05d.png"),
        ]
    )
    return frames


def bench_encode(cfg: StudioConfig, args: argparse.Namespace) -> None:
    ffmpeg, melt = cfg.path("tools", "ffmpeg"), cfg.path("tools", "melt")
    fps, seconds = 24, 60
    frames = make_frames(cfg, seconds, fps)
    out = SCRATCH / "encode"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for label, codec in (
        ("ffmpeg libx264 (CPU)", ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]),
        ("ffmpeg h264_videotoolbox (HW)", ["-c:v", "h264_videotoolbox", "-b:v", "12M"]),
    ):
        elapsed, _ = timed(
            [
                str(ffmpeg),
                "-y",
                "-v",
                "error",
                "-framerate",
                str(fps),
                "-i",
                str(frames / "%05d.png"),
                *codec,
                "-pix_fmt",
                "yuv420p",
                str(out / "ff.mp4"),
            ]
        )
        rows.append([label, f"{elapsed:.1f}", f"{seconds / elapsed:.1f}x"])

    # melt: (a) the PNG sequence itself. MLT's image producers read a folder as a sequence with
    # the ".all.png" resource and ttl=1 (one frame per image); printf-style %05d is not accepted.
    # (b) re-encoding a finished 60 s MP4, which is what edit_mcp does when assembling shots.
    consumer = [
        "-profile",
        "atsc_1080p_24",
        "-consumer",
        f"avformat:{out / 'melt.mp4'}",
        "vcodec=libx264",
        "crf=18",
        "preset=medium",
        "an=1",
    ]
    for label, source in (
        ("melt libx264 from PNG sequence", [f"{frames}/.all.png", "ttl=1"]),
        ("melt libx264 re-encoding an MP4", [str(out / "ff.mp4")]),
    ):
        elapsed, _ = timed([str(melt), "-silent", "-quiet", *source, *consumer])
        rows.append([label, f"{elapsed:.1f}", f"{seconds / elapsed:.1f}x"])
    headers = ["Encoder", "Seconds for 60 s of 1080p24", "Speed vs real time"]
    report(
        "Encode (60 s, 1080p)",
        table(headers, rows),
        ["Input: 1440-frame 1080p PNG sequence (what Synfig produces)."],
        args.dry_run,
    )


def bench_switch(cfg: StudioConfig, args: argparse.Namespace) -> None:
    """LLM -> SDXL -> LLM: the hand-over cost the director pays between stages."""
    client = Ollama(cfg.get("services", "ollama_url"))
    comfy = Comfy(cfg.get("services", "comfyui_url"))
    model = args.model or cfg.get("ollama", "director_models")[0]
    wf = load_workflow("txt2img_sdxl_lightning.json")
    unload_everything(client)
    comfy.free_memory()

    rows = []
    with MemoryWatch() as mem:
        client.load(model)
        client.chat(model, [{"role": "user", "content": "Say hi."}], think=False)
        unload_s = client.unload(model)
        _, cold_img = comfy.run(wf, SCRATCH / "switch")
        _, warm_img = comfy.run(wf, SCRATCH / "switch")
        start = time.perf_counter()
        comfy.free_memory()
        time.sleep(0.5)
        free_s = time.perf_counter() - start
        load_s = client.load(model)
    client.unload(model)
    rows.append(
        [
            f"{model} -> SDXL",
            f"{unload_s:.2f}",
            f"{cold_img - warm_img:.1f}",
            f"{unload_s + cold_img - warm_img:.1f}",
        ]
    )
    rows.append([f"SDXL -> {model}", f"{free_s:.2f}", f"{load_s:.1f}", f"{free_s + load_s:.1f}"])
    headers = ["Switch", "Unload/free s", "Extra load s", "Total switch cost s"]
    notes = [
        "SDXL extra load = first image minus a warm image (speed-LoRA workflow).",
        f"Memory across the whole sequence: {mem.summary()}",
    ]
    report("Stage switching", table(headers, rows), notes, args.dry_run)


# --------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print only, don't append to benchmarks.md"
    )
    sub = parser.add_subparsers(dest="stage", required=True)

    commands: dict[str, Callable[[StudioConfig, argparse.Namespace], None]] = {}

    def add(
        name: str, fn: Callable[[StudioConfig, argparse.Namespace], None], **defaults: Any
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        p.add_argument("--runs", type=int, default=defaults.get("runs", 3))
        commands[name] = fn
        return p

    p = add("llm", bench_llm, runs=2)
    p.add_argument("--models", nargs="*")
    p.add_argument("--max-tokens", type=int, default=400)
    p.add_argument(
        "--think", type=lambda v: {"true": True, "false": False}.get(v, v), default=False
    )
    p = add("vision", bench_vision)
    p.add_argument("--model")
    p.add_argument("--image", required=True)
    add("sdxl", bench_sdxl, runs=2)
    p = add("styles", bench_styles, runs=1)
    p.add_argument("--styles", nargs="*")
    p.add_argument("--seed", type=int, default=42)
    p = add("segment", bench_segment)
    p.add_argument("--image", required=True)
    add("tts", bench_tts, runs=3)
    p = add("music", bench_music, runs=1)
    p.add_argument("--no-mlx-dit", action="store_true")
    p.add_argument("--precision", choices=["fp32", "bf16", "fp16"], default="fp32")
    p.add_argument("--no-mlx-vae", action="store_true")
    p.add_argument("--duration", type=float, default=30.0)
    p = add("rhubarb", bench_rhubarb)
    p.add_argument("--wav", required=True)
    p.add_argument("--dialog")
    p = add("synfig", bench_synfig, runs=1)
    p.add_argument("--sif", required=True)
    p.add_argument("--frames", type=int, default=48)
    p.add_argument("--threads", type=int, default=0)
    add("encode", bench_encode, runs=1)
    p = add("switch", bench_switch, runs=1)
    p.add_argument("--model")

    args = parser.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    commands[args.stage](load_config(), args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
