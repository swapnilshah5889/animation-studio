# Benchmarks (Mac, Step 0)

Measured timings for each pipeline stage on the owner's primary machine. Produced by
`scripts/benchmark.py <stage>`, which appends one section per run below. Re-run a stage after a
change and compare.

**Machine:** MacBook Pro, Apple M4 (4 performance + 6 efficiency CPU cores, 10-core GPU, Metal 4),
24 GB unified memory, macOS 26.6.2. Python 3.12.15 (uv), PyTorch 2.14.1, Ollama 0.40.6,
ComfyUI v0.42.1, Synfig 1.5.5, MLT 7.42.0, ffmpeg 9.0.2.

**Conditions:** Step 0 ran these while large model downloads were still going in the background
(network I/O, light CPU). Other apps were open (browsers, Claude, Docker Desktop with Qdrant). An
unrelated `qwen2.5:7b` was sometimes loaded in Ollama by another project; the LLM and image
benchmarks unload every Ollama model first. Treat numbers as "typical working day", not
best-case.

**How to read memory:** "Peak used" is whole-system memory in use (wired + active + compressed),
and "min free" is the kernel's free-memory percentage at the worst moment. Swap growth means the
stage pushed the Mac past its memory. "Peak footprint" is one process's own peak, including its
GPU allocations (unified memory).

## Summary

| Stage | Result on this Mac | Notes |
|---|---|---|
| Director LLM: qwen3:14b | 8.4 GB in memory, 109 prompt tok/s, **10.9 gen tok/s** | Recommended director (D-024) |
| Director LLM: gpt-oss:20b | 11.9 GB, 445 prompt tok/s, **26.2 gen tok/s** | Faster (mixture of experts), less reliable at tool calls |
| Tool calling | qwen3:14b **5/5** (7.5 s/trial thinking off, 68 s on); gpt-oss:20b 3/5 first try, 4/5 after one retry | `scripts/check_tool_calling.py` |
| Vision QA | **qwen3-vl:8b-instruct 5–7 s per frame**; thinking tag 29–32 s | D-018 |
| SDXL 1024×1024 | 25 steps: **~222 s**; Lightning 8 steps: **~51–56 s** | Measured under memory pressure (see below) |
| SAM 2 / depth | **~0.5 s** per image each (warm) | |
| Kokoro TTS | RTF **0.10** (10x faster than real time), CPU = MPS | CPU default (D-021) |
| ACE-Step 30 s music | Generate **17 s** (PyTorch DiT) / 43 s (MLX DiT); 34–72 s per process | **~30 GB footprint, swaps** |
| Rhubarb | **6.8 s per 10 s** of audio | x86_64 under Rosetta |
| Synfig 1080p | **0.03–0.04 s per frame** (simple rigs) | Re-measure with real puppets in Step 2 |
| Encode 60 s 1080p | ffmpeg x264 **9.4 s**, VideoToolbox **6.4 s**, melt (MP4 in) **8.8 s**, melt (PNGs in) 250 s | Encode shots with ffmpeg, assemble with melt |
| Stage switching | LLM → SDXL **~40 s**; SDXL → LLM **~5 s**; unloads are near-instant | |

**Memory pressure (the 24 GB constraint is real):**
- **LLMs alone are fine:** the whole system peaked at 18–20 GB with qwen3:14b or gpt-oss:20b
  loaded, with no swap.
- **SDXL swapped** (+4.5 to +7 GB) because another app (the owner's Montage project) kept
  `qwen2.5:7b` loaded in Ollama during the run. That is exactly the failure the one-model rule
  prevents, and it inflated the SDXL times. Re-run `benchmark.py sdxl` on a quiet machine for
  clean numbers.
- **ACE-Step 1.5 is the heaviest stage:** ~30 GB process footprint, free memory down to 0–1%,
  swap +8 to +13 GB. It runs everything in float32 on MPS, and its MLX path keeps a second copy
  of the DiT. Step 3 must fix this (half precision, `PYTORCH_MPS_HIGH_WATERMARK_RATIO`, or
  ComfyUI's native ACE-Step 1.5 nodes, which manage memory themselves) before music runs inside
  a pipeline.

**Rough time budget for one 60 s film on the Mac alone** (estimate from the numbers above, not
measured): director planning 5–15 min, ~10 character/background images ~10 min (Lightning),
segmentation and depth under 1 min, voices ~1 min, lip-sync under 1 min, 2 music cues ~2 min,
vision QA on ~15 shots ~2 min, Synfig + encode a few minutes. **About 30–40 minutes**, dominated
by image generation and the LLM.

## Measurements

### Encode (60 s, 1080p)

_Measured 2026-10-19 19:06._

| Encoder | Seconds for 60 s of 1080p24 | Speed vs real time |
|---|---|---|
| ffmpeg libx264 (CPU) | 9.4 | 6.4x |
| ffmpeg h264_videotoolbox (HW) | 6.4 | 9.4x |
| melt libx264 from PNG sequence | 250.4 | 0.2x |
| melt libx264 re-encoding an MP4 | 8.8 | 6.8x |

- Input: 1440-frame 1080p PNG sequence (what Synfig produces).
- **Takeaway:** MLT is ~28x slower reading PNG sequences (Qt image producer, one decode per
  frame) than re-encoding an MP4. Pipeline rule: encode each shot's PNG frames with ffmpeg into
  `shot.mp4`, and let melt only assemble finished shot MP4s. VideoToolbox (hardware) is the
  fastest for previews; libx264 CRF 18 for finals.

### Synfig render

_Measured 2026-10-19 19:06._

| Scene | Frames | Total s | s per 1080p frame | Memory |
|---|---|---|---|---|
| `stickman.sif` (vector rig) | 48 | 2.1 | 0.04 | peak used 15.1 GB, min free 60%, swap +0.00 GB |
| `smoke.sif` (PNG parts + moving hills) | 48 | 1.4 | 0.03 | peak used 14.9 GB, min free 61%, swap +0.00 GB |

- Command: `synfig <scene>.sif -t png -w 1920 -h 1080 --begin-time 0 --end-time 47f -o f.png`
  (totals include process start-up, about 1 s).
- `stickman.sif` is the sample bundled with Synfig Studio's "add skeleton (simple)" plugin: 14 body
  parts (15 outlines + 14 regions) in a nested group / rotate / translate hierarchy, i.e. a full
  cut-out rig. It holds one pose, but render cost per frame does not depend on animation.
- `smoke.sif` is our Step 0 fixture: two imported PNG parts with a waving arm and a panning
  background group.
- **Takeaway:** simple rigs render at ~25 fps at 1080p, so a 60 s film is about a minute of Synfig
  time. Real shots with full-screen painted backgrounds and parallax layers will cost more;
  re-measure in Step 2 with a real puppet.

### Text-to-speech

_Measured 2026-10-19 19:07._

| Model | Load s | Audio s | Synth s | RTF (lower = faster) | Peak footprint |
|---|---|---|---|---|---|
| Kokoro-82M (mps) | 2.7 | 31.1 | 3.0 | 0.095 | 2.4 GB |
| Kokoro-82M (cpu) | 1.4 | 31.1 | 3.1 | 0.100 | 1.5 GB |

- RTF = synthesis time / audio duration, 3 passes over 2 lines after a warm-up.
- Whole-process wall clock (includes Python and torch import): mps 12.4s, cpu 11.0s.
- **Takeaway:** an 82M-parameter model is too small for the GPU to matter: CPU is as fast (about
  10x faster than real time), loads faster and uses less memory. TTS defaults to CPU
  (`[audio] kokoro_device`), so it can run alongside a GPU stage without breaking the
  one-big-model rule.

### Lip-sync (Rhubarb)

_Measured 2026-10-19 19:07._

| Tool | Audio s | Best wall s | s per 10 s of audio |
|---|---|---|---|
| rhubarb (pocketSphinx) | 10.3 | 7.0 | 6.8 |

- Input dialogue_2lines.wav (two Kokoro lines), dialog text given.
- Rhubarb 1.14.0 is an x86_64 binary running under Rosetta 2 (D-022); a native arm64 build would
  likely be faster. Even so, lip-sync for a 60 s film's dialogue takes well under a minute.

### SDXL text-to-image

_Measured 2026-10-19 19:53._

| Variant | Steps | CFG | First (cold) s | Best s | Avg s | Memory |
|---|---|---|---|---|---|---|
| normal | 25 | 6.0 | 203.1 | 221.9 | 222.6 | peak used 22.1 GB, min free 8%, swap +7.05 GB |
| speed LoRA | 8 | 1.0 | 65.7 | 51.1 | 55.8 | peak used 21.7 GB, min free 12%, swap +4.53 GB |

- 1024x1024, batch 1, 2 warm runs after one cold run, ComfyUI HTTP API.
- The normal variant uses CFG 6, which costs two UNet passes per step (~8 s/step); Lightning uses
  CFG 1, one pass (~3.7 s/step), and only 8 steps.
- **Contaminated:** the owner's Montage app reloaded `qwen2.5:7b` (5 GB) in Ollama during this
  run, so memory swapped. Treat these as upper bounds; re-run on a quiet machine.

### SAM 2 and depth

_Measured 2026-10-19 19:54._

| Model | Cold s | Warm s/image | Memory |
|---|---|---|---|
| SAM 2 | 2.2 | 0.51 | peak used 13.5 GB, min free 53%, swap +0.00 GB |
| Depth Anything V2 Small | 1.2 | 0.50 | peak used 13.0 GB, min free 58%, swap +0.00 GB |

- Input: /Users/uchiha/ai-studio/scratch/smoke/comfy/txt2img/txt2img_sdxl_00001_.png


### Tool calling (scripts/check_tool_calling.py)

_Measured 2026-10-19 20:14, 5 trials per model, think=None._

| Model | Valid call, 1st try | Valid after 1 retry | Uses result | No needless call | Avg s/trial |
|---|---|---|---|---|---|
| qwen3:14b | 5/5 | 5/5 | 5/5 | 5/5 | 67.5 |
| gpt-oss:20b | 3/5 | 4/5 | 4/5 | 5/5 | 86.9 |

### Tool calling (scripts/check_tool_calling.py)

_Measured 2026-10-19 20:15, 5 trials per model, think=False._

| Model | Valid call, 1st try | Valid after 1 retry | Uses result | No needless call | Avg s/trial |
|---|---|---|---|---|---|
| qwen3:14b | 5/5 | 5/5 | 5/5 | 5/5 | 7.5 |

### Director LLMs

_Measured 2026-10-19 20:18._

| Model | In memory | Cold load s | Prompt tok | Prompt tok/s | Gen tok/s | Unload s | Peak used / min free |
|---|---|---|---|---|---|---|---|
| qwen3:14b | 8.4 GB | 1.0 | 2834 | 109 | 10.9 | 0.06 | 18.4 GB / 39% |
| gpt-oss:20b | 11.9 GB | 6.6 | 2868 | 445 | 26.2 | 0.06 | 20.2 GB / 25% |

- 2 runs per model, num_ctx 8192, temperature 0, up to 400 generated tokens, think=False (gpt-oss: 'low', it cannot be switched off). Prompt = director task + ARCHITECTURE.md.
- Cold load = wall clock to ready. The model files were already in the OS file cache from the
  tool-calling runs, so these are warm-cache loads; straight after a reboot expect several seconds
  more (SSD read of 9–14 GB).
- The Montage app's `qwen2.5:7b` was reloaded by that app during these runs and shared the GPU.

### Vision QA

_Measured 2026-10-19 20:20._

| Model | In memory | Cold load s | Best s/frame | Avg s/frame | Memory |
|---|---|---|---|---|---|
| qwen3-vl:8b | 5.1 GB | 4.8 | 29.0 | 31.7 | peak used 15.0 GB, min free 55%, swap +0.00 GB |

- Image: txt2img_sdxl_00001_.png. 3 runs.
- Sample answer: `{
  "characters": [
    "A cute cartoon rabbit with white fur, large ears with pink inner parts, pink cheeks, a red scarf, teal hoodie with green accents, and brown pants"
  ],
  "background": "Light `

### Vision QA

_Measured 2026-10-19 20:26._

| Model | In memory | Cold load s | Best s/frame | Avg s/frame | Memory |
|---|---|---|---|---|---|
| qwen3-vl:8b-instruct | 5.1 GB | 1.3 | 4.9 | 7.4 | peak used 16.5 GB, min free 57%, swap +0.00 GB |

- Image: txt2img_sdxl_00001_.png. 3 runs.
- Sample answer: `{
  "characters": [
    {
      "name": "Rabbit",
      "description": "A cute, white cartoon rabbit with large ears, rosy cheeks, and a friendly smile. It is wearing a teal hoodie with a red scarf, o`

### Music (ACE-Step)

_Measured 2026-10-19 20:27._

| Model | Load s | Generate 30 s | Process wall s | Peak footprint | System |
|---|---|---|---|---|---|
| ACE-Step 1.5 turbo | 20 | 43 | 72 | 29.6 GB | peak used 22.9 GB, min free 1%, swap +12.72 GB |

- turbo DiT (MLX, the library default), 8 steps, LM off, seed 42
- caption: gentle, playful background music for a preschool cartoon, ukulele, glockenspiel, soft hand percussion, bright and happy, major key
- Peak footprint counts the process's own pages, including GPU/MLX buffers and pages that were compressed or swapped; it can exceed physical RAM.

### Music (ACE-Step)

_Measured 2026-10-19 20:28._

| Model | Load s | Generate 30 s | Process wall s | Peak footprint | System |
|---|---|---|---|---|---|
| ACE-Step 1.5 turbo (PyTorch/MPS DiT) | 9 | 17 | 34 | 29.2 GB | peak used 22.9 GB, min free 0%, swap +8.39 GB |

- turbo DiT (PyTorch/MPS), 8 steps, LM off, seed 42
- caption: gentle, playful background music for a preschool cartoon, ukulele, glockenspiel, soft hand percussion, bright and happy, major key
- Peak footprint counts the process's own pages, including GPU/MLX buffers and pages that were compressed or swapped; it can exceed physical RAM.

### Stage switching

_Measured 2026-10-19 20:30._

| Switch | Unload/free s | Extra load s | Total switch cost s |
|---|---|---|---|
| qwen3:14b -> SDXL | 0.02 | 39.5 | 39.5 |
| SDXL -> qwen3:14b | 0.50 | 4.3 | 4.8 |

- SDXL extra load = first image minus a warm image (speed-LoRA workflow).
- Memory across the whole sequence: peak used 19.7 GB, min free 29%, swap +0.00 GB

### Style comparison (switcher)

_Measured 2026-10-19 20:54._

| Style | Commercial | Character fast s (first incl. load) | Character normal s | Background normal s (1344x768) |
|---|---|---|---|---|
| storybook | yes | 40 (8 st) | 138 (25 st) | 137 (25 st) |
| dreamshaper-lightning | unclear | 48 (4 st) | 61 (6 st) | 60 (6 st) |
| animagine | yes | 37 (8 st) | 150 (28 st) | 147 (28 st) |

- Same seed (42) and prompts for every style; the style adds its own trigger words and negative prompt (config/models.toml). Each style starts cold (model load is in its first column).
- Image grid (not committed, generated media): `/Users/uchiha/ai-studio/scratch/style-compare/grid.png`
- Memory across the run: peak used 21.1 GB, min free 18%, swap +2.73 GB
- **Looks (from the grid):**
  - `storybook` gives a flat kids'-book character and vivid painted backgrounds; the fast
    8-step version is close to the normal one.
  - `dreamshaper-lightning` gives a polished, softly shaded semi-3D look and is the fastest at
    full quality (~60 s), but its license is unclear.
  - `animagine` gives a very simple chibi character (easy to cut into puppet parts) and soft anime
    backgrounds. **Its fast variant (SDXL-Lightning LoRA on Animagine) degrades into a noisy,
    textured image**, so don't use Lightning with this style. Fixed in `config/models.toml`: its
    fast variant is now 16 of its own steps (verified clean, 91 s including model load).
- Timings here are cleaner than the earlier "SDXL text-to-image" section (138 s vs 222 s for 25
  steps): less memory pressure during this run.

### Music (ACE-Step)

_Measured 2026-10-22 11:10._

| Model | Load s | Generate s | Process wall s | Peak footprint | System |
|---|---|---|---|---|---|
| ACE-Step 1.5 turbo (PyTorch/MPS DiT, bf16, PyTorch VAE, 10 s) | 7 | 6 | 21 | 9.6 GB | peak used 18.1 GB, min free 43%, swap +0.00 GB |

- turbo DiT (PyTorch/MPS), 8 steps, bf16, PyTorch VAE, LM off, seed 42
- caption: gentle, playful background music for a preschool cartoon, ukulele, glockenspiel, soft hand percussion, bright and happy, major key
- Peak footprint counts the process's own pages, including GPU/MLX buffers and pages that were compressed or swapped; it can exceed physical RAM.

### Music (ACE-Step)

_Measured 2026-10-22 11:10._

| Model | Load s | Generate s | Process wall s | Peak footprint | System |
|---|---|---|---|---|---|
| ACE-Step 1.5 turbo (PyTorch/MPS DiT, bf16, PyTorch VAE, 30 s) | 7 | 14 | 29 | 9.6 GB | peak used 18.2 GB, min free 42%, swap +0.00 GB |

- turbo DiT (PyTorch/MPS), 8 steps, bf16, PyTorch VAE, LM off, seed 42
- caption: gentle, playful background music for a preschool cartoon, ukulele, glockenspiel, soft hand percussion, bright and happy, major key
- Peak footprint counts the process's own pages, including GPU/MLX buffers and pages that were compressed or swapped; it can exceed physical RAM.

### Music (ACE-Step)

_Measured 2026-10-22 11:11._

| Model | Load s | Generate s | Process wall s | Peak footprint | System |
|---|---|---|---|---|---|
| ACE-Step 1.5 turbo (PyTorch/MPS DiT, bf16, PyTorch VAE, 60 s) | 7 | 25 | 40 | 9.7 GB | peak used 18.1 GB, min free 43%, swap +0.00 GB |

- turbo DiT (PyTorch/MPS), 8 steps, bf16, PyTorch VAE, LM off, seed 42
- caption: gentle, playful background music for a preschool cartoon, ukulele, glockenspiel, soft hand percussion, bright and happy, major key
- Peak footprint counts the process's own pages, including GPU/MLX buffers and pages that were compressed or swapped; it can exceed physical RAM.

### Music memory fix, summary (task 3.4, D-041)

_Measured 2026-10-22, 10 s cue, PyTorch/MPS DiT, Ollama and ComfyUI unloaded. The first three
rows were dry runs (`--dry-run`), copied here._

| Precision | VAE | Peak footprint | Swap | Generate s |
|---|---|---|---|---|
| fp32 (ACE-Step's MPS default) | MLX (second copy, fp32) | 21.0 GB | +5.72 GB | 10 |
| bf16 | MLX | 18.6 GB | +0.30 GB | 8 |
| fp16 | MLX | 18.5 GB | +0.26 GB | 8 |
| **bf16** | **PyTorch (the one already loaded)** | **9.6 GB** | **0** | 6 |

- With bf16 + PyTorch VAE, PyTorch held 6.85 GB allocated (8.2 GB with its cache) after
  loading. Before, the footprint was ~10 GB above PyTorch's own numbers: the MLX VAE and its
  buffers.
- Longer cues barely change the peak: 9.6 GB at 30 s, 9.7 GB at 60 s (rows above).
