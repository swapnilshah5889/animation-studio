# Local inference on Apple Silicon

How models actually run on the M4 Mac, and why the pipeline follows the rules it does.
Numbers for this machine are in [`../benchmarks.md`](../benchmarks.md).

## Unified memory: one pool for CPU and GPU

On a PC, the GPU has its own VRAM (the Windows laptop: 4 GB) and model weights must be copied
across PCIe into it. On Apple Silicon the CPU, GPU and Neural Engine share **one pool of RAM**
(24 GB here). There is no copy: a tensor allocated for the GPU is just memory.

Consequences:

- **The GPU can use most of RAM, not a fixed VRAM size.** macOS caps GPU-wired memory at roughly
  two thirds to three quarters of RAM by default (`sysctl iogpu.wired_limit_mb` shows an override
  if one is set; 0 means the default). On 24 GB that is about **16 GB for models**, which is the
  number AGENTS.md uses. Everything else (macOS, Docker's VM, browsers, our Python processes)
  lives in the remaining ~8 GB.
- **Memory bandwidth, not compute, limits LLM speed.** Generating one token means reading every
  weight once. The M4 has about 120 GB/s of bandwidth, so a 9 GB model can produce at most
  ~13 tokens/s, and a 14 GB one ~8–9 tokens/s (mixture-of-experts models such as gpt-oss read only
  the active experts per token, so they beat this estimate). Prompt processing is compute-bound and
  much faster per token.
- **Swapping is the failure mode.** If two big models are resident at once, macOS compresses and
  then swaps memory to SSD. Nothing crashes; everything just gets 10–100× slower. Watch
  `memory_pressure` or Activity Monitor's memory-pressure graph (green / yellow / red).

## Why one large model at a time

A 9–14 GB director LLM plus a 7 GB SDXL checkpoint (plus its VAE, text encoders and activations)
does not fit in ~16 GB. So every stage must **explicitly release** the previous model:

- Ollama: send `keep_alive: 0` (see `studio_core/ollama.py: Ollama.unload`). By default Ollama
  keeps a model loaded for 5 minutes after the last request, which would silently eat the memory
  ComfyUI needs.
- ComfyUI: `POST /free {"unload_models": true, "free_memory": true}` (see
  `studio_core/comfy.py: Comfy.free_memory`).
- Separate Python processes (TTS, music): exit the process; the OS reclaims everything.

The director's stage machine (Step 5) calls these between stages. Step 0 measures how long a
switch costs (see "Stage switching" in the benchmarks).

## Three ways to run a model here

| Runtime | What it is | Used for | Notes |
|---|---|---|---|
| **Ollama** (llama.cpp inside) | C++ inference engine with Metal kernels, GGUF model files, an HTTP API | Director LLM, vision QA | Fastest and simplest for LLMs. Handles quantized weights, tool-calling templates, model loading/unloading. |
| **PyTorch + MPS** | PyTorch's Metal Performance Shaders backend (`device="mps"`) | ComfyUI (SDXL, SAM 2, depth), Kokoro, ACE-Step | Runs ordinary PyTorch code on the GPU. Some ops are missing and fall back to CPU (`PYTORCH_ENABLE_MPS_FALLBACK=1`); fp16 support is good, bf16 partial. |
| **MLX** | Apple's own array framework, designed for unified memory | Optional (e.g. `mlx-audio`) | Often faster than PyTorch-MPS for transformers; smaller ecosystem. |

We use whichever runtime the tool supports best and keep each heavy stack in its **own Python
environment** (D-009, D-016), because PyTorch versions and pins conflict between projects.

## Quantization basics

Weights are trained in 16- or 32-bit floats. **Quantization** stores them in fewer bits:

- **Q4_K_M** (GGUF, llama.cpp): about 4.5 bits per weight, grouped with per-block scales. A 14B
  model shrinks from ~28 GB (fp16) to ~9 GB with a small quality loss. This is Ollama's default.
- **Q8_0**: ~8.5 bits per weight, near-lossless, twice the size of Q4.
- **MXFP4**: the 4-bit floating-point format gpt-oss ships in natively (it was trained for it), so
  the 20B model is ~14 GB without a separate quantization step.
- **fp16** for image models: SDXL checkpoints are ~6.5–7 GB in fp16. Diffusion models are more
  sensitive to aggressive quantization than LLMs, so we keep them at fp16.

Rule of thumb: memory ≈ parameters × bits / 8, plus the KV cache (grows with context length) and
runtime overhead. Bigger context windows cost memory, so the director should not ask for 128k
tokens of context it does not need.

## Finding where the memory goes (a worked example)

ACE-Step 1.5 needed ~21 GB for a 10-second music cue and pushed the Mac into swap. It now runs in
under 10 GB (task 3.4, D-041). The method carries over to any model:

1. **Measure the right number.** `/usr/bin/time -l` reports a process's **peak memory
   footprint**: everything it owns, including GPU (Metal) buffers and pages that were
   compressed or swapped. That's the number that decides whether the Mac swaps. "Maximum
   resident set size" misses GPU buffers, so it can look fine while the machine swaps.
2. **Ask each framework what it holds.** PyTorch reports `torch.mps.current_allocated_memory()`
   (live tensors) and `driver_allocated_memory()` (live tensors plus its cache). Here: 6.9 GB
   allocated, 8.9 GB with the cache, but an 18.7 GB footprint. So ~10 GB belonged to something
   else.
3. **Read the logs for second copies.** ACE-Step quietly converted its VAE to a second framework
   (MLX), in float32 and compiled, and decoded with that copy. Two frameworks means two memory
   pools. Neither one's numbers show the other.
4. **Check the precision.** ACE-Step chooses float32 on MPS (bf16 only on CUDA). Every loader
   read one attribute, `handler.dtype`, so changing it to bf16 halved the weights without editing
   the library.

| Change | Peak footprint (10 s cue) |
|---|---|
| as shipped (fp32, MLX VAE) | 21.0 GB, 5.7 GB swapped |
| bf16 weights | 18.6 GB |
| bf16 + one VAE (PyTorch's) | **9.6 GB, no swap** |

Precision alone saved 2.4 GB; removing the duplicate saved 9. **Look for duplicates before
reaching for quantization.**

## Gotchas

- **Docker on macOS cannot see the GPU.** Its Linux VM gets CPU only, so models always run
  natively (D-010). The VM also reserves memory (8 GB limit here), which counts against the 24 GB.
- **First run is slow.** Metal compiles shaders on first use, and models load from SSD. Benchmarks
  report load time separately from steady-state speed.
- **`load_duration` lies a little.** Ollama reports its own load time; the wall-clock time a stage
  waits also includes HTTP and runner start-up. We measure wall clock too.
- **Thinking models** (qwen3, gpt-oss) spend tokens on hidden reasoning before answering. That
  raises quality on planning tasks and costs latency. Ollama exposes it with the `think` option.
