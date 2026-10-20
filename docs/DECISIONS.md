# Decisions

Short ADR-style log. Newest at the bottom. Format: context → decision → why → consequences.
Add an entry whenever you choose a tool, model or format, or deviate from the plan.

---

### D-001: Fully local, no paid APIs
- **Decision:** Every runtime component runs on the owner's machines. No API keys.
- **Why:** Cost, privacy, and learning self-hosted inference.
- **Consequences:** Lower ceiling on story and voice quality than frontier APIs. Models must fit in
  ~16 GB of Mac GPU memory, one at a time.

### D-002: 2D only, children's cut-out animation first
- **Decision:** v1 is rigged puppet (cut-out) 2D animation for children. No 3D. Anime tiers later.
- **Why:** Achievable locally, consistent by construction, and closest to proven preschool styles.

### D-003: Open-source apps animate, the LLM directs
- **Decision:** The LLM never generates frames. AI generates assets once. Synfig tweens rigged
  characters, and Kdenlive/MLT assembles the edit.
- **Why:** Frame-by-frame generation is slow, expensive and inconsistent. Rigs give consistency for free.

### D-004: Wrap apps via MCP servers, at the lowest integration level that works
- **Decision:** One Python MCP server per app. Level 1 (file formats, CLIs, APIs) by default. Level 2
  (in-app plugins) when needed. Level 3 (source changes) last.
- **Why:** Least brittle. Keeps our code separate from GPL apps. MCP is a core learning goal.

### D-005: No reverse engineering of proprietary tools
- **Decision:** Use open-source tools only (Synfig, OpenToonz, Krita, Kdenlive, ComfyUI...).
- **Why:** Commercial software licenses forbid reverse engineering and there is DMCA risk. Open-source
  equivalents exist.

### D-006: Synfig Studio as the animation engine
- **Decision:** Synfig for v1 (bones, skeleton deformation, switch layers, waypoint tweening, XML `.sif`
  format, `synfig` CLI renderer).
- **Why:** Its file format is plain XML that code can generate, and it renders headless from the CLI.
  Built for cut-out animation.
- **Alternatives considered:** OpenToonz (more powerful, harder to automate headless). A custom
  PixiJS/Remotion engine (maximum control, more to build). Revisit if Synfig blocks progress.

### D-007: Consistency from rigs, procedural faces, motion library
- **Decision:** Characters are generated once and rigged. Eyes, brows and mouths are code-generated
  vector shapes (mouth set = Rhubarb A–H, X). Motion comes from a parameterized library.
- **Why:** Exact lip-sync and expressions with no AI cost. Infinite reuse. No LoRA needed for v1.

### D-008: Film project folder is the source of truth
- **Decision:** Every stage reads and writes files in `films/<slug>/`. The state lives in `film.json`.
- **Why:** Human-in-the-loop fixes in real apps, crash-safe resume, easy debugging.

### D-009: Python 3.12 via uv for all environments
- **Decision:** Never use the system Python (3.15). Each package has its own uv-managed environment
  on Python 3.12.
- **Why:** PyTorch and most ML libraries don't support 3.15 yet.

### D-010: Models run natively; Docker only for services
- **Decision:** ML models run natively on macOS (Metal/MPS, MLX, Ollama). Docker is for Qdrant,
  Temporal and MinIO.
- **Why:** Docker on Mac has no GPU access.

### D-011: Two machines, introduced at Step 5
- **Decision:** The Mac is the AI node. The Windows laptop (4 GB RTX, 32 GB RAM) joins at Step 5 as
  the render and services node, through Temporal task queues by capability.
- **Why:** Keep early steps simple. Bring in distributed workers exactly when they solve a real need.

### D-012: Model license hygiene
- **Decision:** Check every model's license before download. Record it in MODELS.md. Prefer permissive
  licenses. Flag non-commercial ones clearly.
- **Why:** The owner may want to publish or monetize films later.

### D-013: Children's safety and style naming
- **Decision:** Age-appropriate content only, checked by `qa_mcp`. No real studio or living artist
  names in presets or prompts.
- **Why:** Ethics, legal risk, and platform policy (YouTube scrutinizes mass-produced kids' content).

### D-014: Synfig CLI from the Homebrew formula; GUI installed by the owner
- **Context:** The `synfigstudio` Homebrew cask was disabled on 2026-09-01 because it fails Gatekeeper.
  The official Synfig Studio 1.5.5 DMG is x86_64-only and unsigned (`spctl`: "rejected, no usable
  signature"), so it needs Rosetta 2 and an owner approval in System Settings.
- **Decision:** The pipeline uses the Homebrew **`synfig` formula** (Synfig 1.5.5 core, native arm64,
  command-line renderer only) at `/opt/homebrew/bin/synfig`. The Synfig Studio GUI, needed only for
  Step 1's hand-built scene, is installed by the owner from the official DMG (same 1.5.5 version, so
  `.sif` files match). We never bypass Gatekeeper.
- **Why:** The renderer is all the MCP server needs. A native binary is faster than Rosetta and
  survives Apple's planned removal of general-purpose Rosetta after macOS 27.

### D-015: Large files under ~/ai-studio; per-machine config in config/studio.toml
- **Decision:** Model weights, third-party checkouts (ComfyUI, ACE-Step), standalone binaries
  (Rhubarb), Qdrant data and scratch output live under `~/ai-studio/`. Every path, port and model
  name is read from `config/studio.toml` (git-ignored; `config/studio.example.toml` is the committed
  template). `scripts/doctor.py` checks everything listed there.
- **Why:** Keeps the repo small and portable. The Windows node (Step 5) gets its own config file
  instead of code changes.

### D-016: One uv workspace for our code; isolated envs for heavy ML stacks
- **Decision:** The repo root is a uv workspace on Python 3.12 (`studio_core` now, MCP servers
  later) sharing one `.venv`. Each heavy ML stack gets its own environment so torch pins can't
  collide: ComfyUI (`~/ai-studio/comfyui/.venv`), ACE-Step (`~/ai-studio/ace-step/.venv`), Kokoro
  (`envs/kokoro/`, its `pyproject.toml` and `uv.lock` committed, outside the workspace). Our code
  talks to them over HTTP (ComfyUI) or by running a small script with that env's interpreter.
- **Rule of thumb:** third-party checkouts live outside the repo with their own venv; environment
  definitions we write live in the repo (`envs/<name>/`) so they are reproducible.
- **Why:** Research found hard conflicts (e.g. Chatterbox pins `torch==2.6.0` and `numpy<2`).

### D-018: Vision QA model: qwen3-vl:8b
- **Decision:** Use `qwen3-vl:8b` (6.2 GB, Apache-2.0) instead of `qwen2.5vl:7b`.
- **Why:** Same Qwen-VL family and size class as planned, newer, 256K context, tool calling. Works on
  Ollama 0.40.x.

### D-017: ComfyUI v0.42.1, Manager as pip package, SAM 2 and depth node packs
- **Decision:** ComfyUI pinned to tag **v0.42.1** in `~/ai-studio/comfyui` with its own uv venv
  (Python 3.12, stable PyTorch from PyPI, which includes MPS). ComfyUI-Manager is now the pip
  package `comfyui_manager` (`manager_requirements.txt`, start with `--enable-manager`).
  Custom node packs:
  - **SAM 2:** `kijai/ComfyUI-segment-anything-2` (Apache-2.0) with **SAM 2.1 hiera-small**
    (Apache-2.0, 184 MB). Run in **fp32 on MPS** (fp16 has an open MPS bug).
  - **Depth Anything V2 Small:** `Fannovel16/comfyui_controlnet_aux` (Apache-2.0, actively
    maintained), node `DepthAnythingV2Preprocessor` with `ckpt_name` set explicitly to
    `depth_anything_v2_vits.pth`. **Its default is the non-commercial Large model.**
- **Alternatives noted for Step 4:** ComfyUI core now ships **SAM 3.1** (text-prompted
  segmentation, e.g. "left arm", which could simplify `cut_into_parts`; custom "SAM License",
  no commercial ban but not OSI) and **Depth Anything 3** (DA3-Small is Apache-2.0). Both need no
  custom nodes. Evaluate them in Step 4 against the packs above.
- **Rejected:** `kijai/ComfyUI-DepthAnythingV2` (no LICENSE file, fp16 fails on Apple Silicon).

### D-019: Image models are switchable; default preset "sdxl-storybook"
- **Context:** The owner wants users to be able to pick the image model (2026-10-19). No
  dedicated flat-cartoon SDXL checkpoint had a clean license, an SFW gallery and no studio or
  artist names. This network's DNS (a family filter) also blocks Civitai, so only Hugging Face
  models are used.
- **Decision:** `config/models.toml` (committed) lists every weight file (URL, sha256, size,
  license, commercial yes/no/unclear) and the **image-model presets** of the switcher (checkpoint +
  VAE + style LoRAs + trigger words + sampler settings for a normal and a fast variant).
  `scripts/fetch_models.py` downloads presets or files idempotently with sha256 checks. The
  per-machine default lives in `config/studio.toml` (`default_image_model`). `comfy_mcp` (Step 4)
  takes a preset id.
- **Default (owner's pick):** `sdxl-storybook` = SDXL Base 1.0 (OpenRAIL++-M) + StoryBookRedmond-V2
  LoRA (OpenRAIL-M) + sdxl-vae-fp16-fix (MIT). **Speed LoRA:** SDXL-Lightning 8-step
  (OpenRAIL++-M), euler / sgm_uniform, CFG 1.
- **Rule:** only presets whose files are all `commercial = "yes"` may be the default.
  DreamShaper XL Lightning stays listed as `unclear`; DMD2 and Flash-SDXL (non-commercial) are not
  listed at all.
- **Why:** Cleanest license chain, and SDXL Base is the best foundation for our own style and
  character LoRAs in Step 6.

### D-020: Music: ACE-Step 1.5 (turbo), without its language model
- **Decision:** Use **ACE-Step 1.5** (code and weights **MIT**, actively maintained, Apple Silicon
  via MPS + MLX) instead of v1 (Apache-2.0, inactive since early 2026). Checkout in
  `~/ai-studio/ace-step` with its own uv env. Weights in `~/ai-studio/models/ace-step-1.5`
  (`ACESTEP_CHECKPOINTS_DIR`): turbo DiT, VAE and text encoder (6.3 GB). The optional 1.7B
  "thinking" language model (3.8 GB) is skipped: our director writes the music brief itself.
- **Noted alternative:** ComfyUI core has native ACE-Step 1.5 nodes; music could later run
  through `comfy_mcp` instead of a separate env.

### D-021: TTS: Kokoro-82M through the `kokoro` package (PyTorch + MPS)
- **Decision:** `kokoro` 0.9.4 in `envs/kokoro`, weights in `~/ai-studio/models/kokoro-82m`,
  loaded from local files with `HF_HUB_OFFLINE=1` after the first download. The spaCy model is
  pinned as a wheel so nothing downloads at run time. Default voice `af_heart`, 24 kHz mono.
- **Why:** It is the reference implementation, and it was measured at a real-time factor of
  ~0.23 on MPS, which is already fast enough. `mlx-audio` is a possible speed-up later.

### D-022: Rhubarb runs under Rosetta 2 for now (owner approved 2026-10-19)
- **Context:** Rhubarb 1.14.0's macOS binary is x86_64-only and unsigned. Rosetta 2 was already
  installed. Apple ends general-purpose Rosetta after macOS 27.
- **Decision:** Use the official x86_64 build from `~/ai-studio/tools/rhubarb/` under Rosetta.
  **Follow-up before macOS 27:** build Rhubarb natively for arm64 from source.

### D-023: Ollama runs as a Homebrew service (owner approved 2026-10-19)
- **Decision:** `brew services start ollama`, so the server runs at login instead of inside some
  terminal session. Models stay in Ollama's default store (`~/.ollama/models`).
