# Step 0: Environment setup + benchmarks (Mac)

**Goal:** every tool and model the v1 pipeline needs is installed, verified from the command line, and
benchmarked on the owner's Mac (M4, 24 GB). Nothing is built yet beyond the scripts needed to prove
it all works.

**Out of scope:** MCP servers, the Windows laptop, the Krita plugin, LoRA training, Temporal.

## Owner checkpoints (stop and ask)

1. **Image checkpoint choice:** propose 2–3 SDXL-based flat cartoon / children's-book checkpoints,
   each with sample images, license, and whether commercial use is allowed. The owner picks one
   before you download.
2. **macOS security prompts:** if Gatekeeper blocks an app, or a tool needs Rosetta 2, **stop and ask
   the owner** to approve it in System Settings. Don't bypass Gatekeeper yourself.
3. **Benchmarks review** at the end.

## Conventions set up in this step

- **Large files outside the repo**, under `~/ai-studio/`:
  ```
  ~/ai-studio/
    comfyui/        ComfyUI checkout + its own uv venv
    models/         shared weights not managed by ComfyUI or Ollama
    tools/          standalone binaries (e.g. rhubarb)
    sfx-library/    CC0 sound effects (populated in Step 3)
    qdrant-data/    Qdrant storage volume
  ```
  Ollama keeps its own model store. ComfyUI models go under `~/ai-studio/comfyui/models/`.
- **Per-machine config:** `config/studio.example.toml` (committed) and `config/studio.toml`
  (git-ignored) hold paths to binaries, ports and model names. The Windows machine will have its own
  copy later. Code reads paths from config, never hard-coded.
- **Python:** root `pyproject.toml` as a **uv workspace**, Python 3.12, with `ruff` and `pytest`
  configured. Heavy ML stacks (ComfyUI, ACE-Step, TTS) get **their own isolated environments** so
  dependency conflicts can't spread.

## Tasks

### 0.1 Doctor script first
Create `scripts/doctor.py` (run with `uv run scripts/doctor.py`). It checks every tool and model below
and prints `OK` / `MISSING` / `FAIL`, with versions and paths read from `config/studio.toml`. Run it
now (mostly red) and keep running it as you go until it's all green.

### 0.2 Apps and CLIs
Verify formula and cask names with `brew info` / `brew search` before installing. Install:

| Tool | How | Verify |
|---|---|---|
| uv | Homebrew formula | `uv --version` |
| Synfig Studio | Homebrew cask, or the official macOS build | Find the **`synfig` CLI inside the app bundle**, record its path in config, run `synfig --version` |
| Kdenlive | Homebrew cask | App opens |
| MLT `melt` CLI | Homebrew formula (`mlt`) or the binary bundled with Kdenlive | `melt -version` |
| Krita | Homebrew cask (used later, install now) | App opens |
| Rhubarb Lip Sync | GitHub release (DanielSWolf/rhubarb-lip-sync) into `~/ai-studio/tools/rhubarb/` | `rhubarb --version`. **Check the architecture.** If it's x86_64 only, ask the owner about Rosetta 2. |
| vtracer | Python package, in the `studio_core` env | Vectorize a test PNG to SVG |
| ffmpeg | Already installed | `ffmpeg -version` |

### 0.3 Repo skeleton
- Root `pyproject.toml` (uv workspace), `studio_core/` package skeleton, `scripts/`, `config/`,
  `infra/`, `tests/`.
- `infra/docker-compose.yml` with **Qdrant** (volume at `~/ai-studio/qdrant-data`, port 6333).
  Start it and verify the health endpoint.
- Extend `.gitignore` for anything new.

### 0.4 Ollama models
- Check the current tags in the Ollama library, then pull **two director candidates** (Qwen3 14B,
  gpt-oss-20b) and **one 7–8B vision model** (Qwen-VL family).
- Write `scripts/check_tool_calling.py`: give each director model one dummy tool
  (e.g. `get_weather(city)`) and confirm it emits a valid tool call. Record the results.
- Confirm explicit unloading works (`keep_alive: 0`) and measure load and unload time.

### 0.5 ComfyUI (native, Metal/MPS)
- Clone into `~/ai-studio/comfyui`. Create a uv venv on Python 3.12 and install PyTorch (macOS arm64
  wheels include MPS) and the requirements.
- Install ComfyUI-Manager, then well-maintained custom nodes for **SAM 2** and **Depth Anything V2**.
  Record which ones and why in DECISIONS.md.
- After owner checkpoint 1, download the chosen SDXL checkpoint and a **few-step speed LoRA**
  (Lightning/Hyper/DMD2 style; check licenses), **SAM 2** (small or base), and **Depth Anything V2
  Small** (Apache-2.0; larger sizes are non-commercial).
- Run ComfyUI headless on `127.0.0.1:8188`. Write `scripts/comfy_smoke.py`, which submits a text-to-image
  workflow **through the HTTP API**, waits for completion, and saves the image. Save the workflow
  (API format) to `comfy_workflows/txt2img_sdxl.json`.
- Also smoke-test one SAM 2 workflow and one depth workflow on the generated image. Save both
  workflows.

### 0.6 Audio stack (each in its own env)
- **Kokoro-82M** (via the `kokoro` package or `mlx-audio`): voice one sample line to WAV.
- **Chatterbox** (optional): install and test if it goes smoothly. Otherwise record why it was skipped.
- **ACE-Step:** verify Apple Silicon support, then generate a 30-second instrumental.
- **Rhubarb:** run it on the Kokoro sample **with the dialogue text passed in**, and output JSON
  mouth cues.

### 0.7 Engine smoke tests
- **Synfig:** render a tiny `.sif` (one of Synfig's bundled examples, or a minimal hand-written XML)
  to a PNG sequence via the CLI, then to MP4 with ffmpeg.
- **MLT:** render a minimal MLT XML (a color clip plus the Kokoro WAV) to MP4 with `melt`.

### 0.8 Benchmarks → `docs/benchmarks.md`
Write `scripts/benchmark.py` (one subcommand per stage, results appended as Markdown tables) and
measure:

| Stage | Metric |
|---|---|
| Director LLMs | Load time, prompt tokens/s, generation tokens/s, peak memory |
| Vision model | Seconds per frame check |
| SDXL | Seconds per 1024×1024 image: normal steps vs. speed LoRA |
| SAM 2 / depth | Seconds per image |
| Kokoro / Chatterbox | Real-time factor |
| ACE-Step | Seconds per 30 s of music |
| Rhubarb | Seconds per 10 s of audio |
| Synfig | Seconds per 1080p frame for a simple rigged sample |
| melt / ffmpeg | Seconds to encode 60 s at 1080p |
| Stage switching | Time to unload one model and load the next |

Also note memory pressure during the heaviest stages.

### 0.9 Docs
- `docs/MODELS.md`: every model, with source, license, commercial use (yes/no), size and location.
- `docs/DECISIONS.md`: checkpoint, custom nodes, TTS choice, and any deviations.
- `docs/learning/local-inference-on-apple-silicon.md`: unified memory, MPS vs. MLX vs. Ollama
  (llama.cpp), why one model at a time, quantization basics.
- `docs/learning/model-licenses.md`: Apache/MIT vs. OpenRAIL vs. non-commercial, and what that means
  for publishing films.
- `docs/PROGRESS.md`: what's done, what's verified, open questions.
- **Write the Step 1 brief** (`docs/steps/STEP-1-synfig.md`) for owner review.

## Done when

Verified 2026-10-19 (details in `docs/PROGRESS.md` and `docs/benchmarks.md`):

- [x] `uv run scripts/doctor.py` is all green: 38 OK + 1 DEFER (Synfig Studio GUI, which the owner
      installs at Step 1, D-014), exit code 0
- [x] Director candidates both pass the tool-calling check (or the failure is documented):
      qwen3:14b 5/5; gpt-oss:20b 3/5 first try, 4/5 after a retry (documented, D-024)
- [x] A text-to-image, a SAM 2 and a depth workflow each run through the ComfyUI **HTTP API** from a
      script (`scripts/comfy_smoke.py`)
- [x] Kokoro voices a line, Rhubarb produces mouth cues for it, and ACE-Step produces 30 s of music
- [x] Synfig CLI and `melt` each render an MP4 (`scripts/smoke_engines.py`)
- [x] Qdrant is running via `infra/docker-compose.yml`
- [x] `docs/benchmarks.md` is filled in, and `MODELS.md` lists every model with its license
- [x] PROGRESS.md is updated and the Step 1 brief is written (`docs/steps/STEP-1-synfig.md`, draft)
- [x] Work committed in small commits (local only; nothing pushed)
