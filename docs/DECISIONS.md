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

### D-018: Vision QA model: qwen3-vl:8b-instruct
- **Decision:** Use Qwen3-VL 8B (6.2 GB, Apache-2.0) instead of `qwen2.5vl:7b`, specifically the
  **`qwen3-vl:8b-instruct`** tag.
- **Why:** Same Qwen-VL family and size class as planned, newer, 256K context, tool calling. Works on
  Ollama 0.40.x. The default `qwen3-vl:8b` tag is the *thinking* variant: it writes ~550 tokens of
  reasoning per frame even with `think: false`, which costs 29–32 s per frame check. The instruct
  variant answers directly in 5–7 s with the same JSON structure (benchmarks.md, "Vision QA").
  The thinking tag stays installed for a quality comparison in Step 5.

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

### D-019: Image models are switchable; default preset "sdxl-storybook" (renamed: styles, D-025)
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
  character LoRAs in Step 7.

### D-020: Music: ACE-Step 1.5 (turbo), without its language model
- **Decision:** Use **ACE-Step 1.5** (code and weights **MIT**, actively maintained, Apple Silicon
  via MPS + MLX) instead of v1 (Apache-2.0, inactive since early 2026). Checkout in
  `~/ai-studio/ace-step` with its own uv env. Weights in `~/ai-studio/models/ace-step-1.5`
  (`ACESTEP_CHECKPOINTS_DIR`): turbo DiT, VAE, text encoder, plus the 1.7B "thinking" language
  model (10.1 GB in all). We run with thinking and all chain-of-thought rewrites **off**: our
  director writes the music brief itself.
- **Deviation from the plan:** the LM was meant to be skipped (3.8 GB), but ACE-Step 1.5's
  `initialize_service` refuses to start without the full main bundle and downloads it itself.
  Patching the library around that check would be brittle, so the LM is installed but unused.
  Evaluate "thinking" mode for quality later.
- **Measured problem (benchmarks.md):** ACE-Step 1.5 runs in float32 on MPS and its default MLX
  path keeps a second copy of the DiT, so one 30 s cue peaks at ~30 GB footprint and pushes the
  Mac into swap. The PyTorch/MPS DiT (`--no-mlx-dit`) was 2.5x faster in our single run (17 s vs
  43 s) but still swapped. **Step 3 must fix memory before music runs inside the pipeline**: try
  half precision, `PYTORCH_MPS_HIGH_WATERMARK_RATIO`, or ComfyUI's native ACE-Step 1.5 nodes
  (ComfyUI handles fp16/bf16 and unloading itself), and keep music on its own between stages.
- **Noted alternative:** ComfyUI core has native ACE-Step 1.5 nodes; music could later run
  through `comfy_mcp` instead of a separate env.

### D-021: TTS: Kokoro-82M through the `kokoro` package (PyTorch + MPS)
- **Decision:** `kokoro` 0.9.4 in `envs/kokoro`, weights in `~/ai-studio/models/kokoro-82m`,
  loaded from local files with `HF_HUB_OFFLINE=1` after the first download. The spaCy model is
  pinned as a wheel so nothing downloads at run time. Default voice `af_heart`, 24 kHz mono.
- **Device: CPU by default** (`[audio] kokoro_device = "cpu"`). Measured RTF ~0.10 on both CPU and
  MPS; CPU loads faster, uses 1.5 GB instead of 2.4 GB, and leaves the GPU free.
- **Why:** It is the reference implementation and already ~10x faster than real time.
  `mlx-audio` is a possible speed-up later.

### D-022: Rhubarb runs under Rosetta 2 for now (owner approved 2026-10-19)
- **Context:** Rhubarb 1.14.0's macOS binary is x86_64-only and unsigned. Rosetta 2 was already
  installed. Apple ends general-purpose Rosetta after macOS 27.
- **Decision:** Use the official x86_64 build from `~/ai-studio/tools/rhubarb/` under Rosetta.
  **Follow-up before macOS 27:** build Rhubarb natively for arm64 from source.

### D-023: Ollama runs as a Homebrew service (owner approved 2026-10-19)
- **Decision:** `brew services start ollama`, so the server runs at login instead of inside some
  terminal session. Models stay in Ollama's default store (`~/.ollama/models`).

### D-024: Director candidate after Step 0: qwen3:14b (provisional; Step 5 confirms)
- **Evidence (`scripts/check_tool_calling.py`, 5 trials each, see benchmarks.md):**
  - **qwen3:14b:** valid call, uses the result and avoids needless calls in 5/5 trials, both with
    thinking on (~68 s per trial) and **off (~7.5 s per trial)**.
  - **gpt-oss:20b:** valid on the first try in only 3/5 trials and 4/5 after one retry. It invents
    enum values (`unit: "C"`, `"metric"`). It is also slower (~87 s per trial) and 13.8 GB, close
    to the Mac's GPU memory limit.
- **Speed (benchmarks.md):** gpt-oss:20b generates 26 tok/s vs qwen3:14b's 11 tok/s (it is a
  mixture-of-experts model: only ~3.6B parameters are active per token). Reliability matters more
  for a director than raw speed, and qwen3 with thinking off is already fast per call.
- **Recommendation:** qwen3:14b as the director, **thinking off for routine tool calls**, and on
  only for planning stages (story, shot list) if quality needs it. Keep gpt-oss:20b installed for
  the Step 5/6 comparison on real director tasks; this check is deliberately tiny.
- **Design rule confirmed:** validate every tool call in code and send the validation error back
  as the tool result. gpt-oss recovered from one of its two bad calls that way.
- **Owner:** Step 5 is owner-led (AGENTS.md); this is input, not the final choice.

### D-025: Switchable style presets, locked per film
- **Context:** The owner wants to switch image models from inside the app (relayed 2026-10-19):
  all three candidates downloaded, A as default, styles as a parameter, and no switching
  mid-film.
- **Decision:**
  - **Registry:** `config/models.toml` `[styles.<id>]`: checkpoint, VAE, style LoRAs and weights,
    sampler settings for `normal` and `fast`, prompt prefix/suffix, negative prompt. The license
    flag is derived from the files it uses.
  - **Why one file, not `config/styles/<name>.toml`:** styles share weight files (SDXL Base, the
    Lightning LoRA), and one manifest defines each file (URL, sha256, license) exactly once. Split
    it later if the list grows.
  - **Styles installed:**
    - `storybook` (A, **default**, commercial yes)
    - `dreamshaper-lightning` (B, commercial **unclear**)
    - `animagine` (C, commercial yes; `safe` tag always)
    - `cutecartoon` (bonus LoRA on SDXL Base, commercial yes)
  - **Workflows take the style as a parameter:** `studio_core.comfy_graphs.txt2img(manifest,
    style, prompt, fast=...)` builds the ComfyUI graph. No checkpoint is hard-coded. Kid-safety
    terms are always appended to the negative prompt. `comfy_mcp` tools take a `style` argument
    (Step 4); the app gets a dropdown later.
  - **Locked per film:** `studio_core.film.Film` stores `style` and `style_commercial` in
    `film.json`. Once the film has any character (in `film.json` or a `characters/<id>/`
    folder), changing the style raises `StyleLockedError`. A series-level lock comes with series
    support (Step 7).
  - **Default must be commercial-OK:** the doctor fails if the default style uses a file whose
    `commercial` is not "yes".
- **Why:** Characters are generated once and reused (D-007), so a style switch after that would
  break consistency. Recording `style_commercial` lets a publishing check refuse films made with
  unclear or non-commercial models.

### D-026: Step 1 hand-built scenes replaced by GUI-saved examples and generated rigs
- **Context:** Step 1 planned for the owner to build a short scene by hand in Synfig Studio, twice
  (groups and bones), so we could see what the GUI writes and compare rig techniques. On
  2026-10-20 the owner asked the agent to do it instead. The agent cannot operate native GUI
  apps: GUI scripting would need an Accessibility permission (a security setting) and Synfig's
  toolkit exposes little to it. Dissecting the app binaries is unnecessary, because Synfig is open
  source and its v1.5.5 source was already the reference for the format.
- **Decision:** Replace the hand-built files with (1) Synfig's own GUI-saved example rigs from
  its documentation, surveyed for "what the GUI writes", and (2) the same scene generated in both
  rig techniques by `scripts/sif_demo.py`, rendered and compared pixel by pixel.
- **Consequences:** The owner skipped the hands-on Synfig session. The owner guide
  (`docs/steps/STEP-1-owner-guide.md`) stays as an optional exercise, and opening a generated
  `scene.sif` in Synfig Studio is the easiest way to see a rig. "Generated files open in the GUI"
  is inferred (they are a subset of what the GUI writes) but **not yet checked by hand**.

### D-027: Rig technique: bones for characters, nested groups for scene layout (owner, 2026-10-21)
- **Context:** Step 1 checkpoint 2. Both techniques were built for the same puppet and render the
  same animation (worst PSNR 97 dB), at the same speed (`docs/learning/synfig-format.md`,
  "Rig technique").
- **Decision:** **Characters are rigged with Synfig bones.** Each character has one bone
  hierarchy in the root `<bones>` block, with GUIDs derived from character + bone name. Each part
  is a flat group whose transformation is a `bone_link`. Art lies in bone-local space (+x along
  the bone; `base` turns the art). A skeleton layer is written but excluded from rendering, so a
  generated rig stays editable by hand in Synfig Studio.
  **Scene layout uses nested groups:** character placement, camera moves, parallax background
  layers and props.
- **Why:**
  - Bones decouple draw order from the hierarchy, so a far arm can sit behind the body.
  - Skeleton Deformation can bend a single image (bendy limbs later).
  - `scalelx` stretches one segment without scaling its children.
  - Bones are what Synfig's own cut-out workflow uses.
  - The cost is more XML (~1.4–1.9x) and GUID bookkeeping, all in unit-tested generator code.
- **Consequences:** Step 2's `rig.json` describes bones (parent, joint position, rest angle) and
  a draw order separate from the hierarchy. A validator runs before every render (bones before
  layers, all required links, every GUID resolves, every image exists), because the CLI aborts or
  silently renders blank parts on these mistakes. There is no IK node in Synfig 1.5.5; if IK is
  needed, it is solved in Python.

### D-028: Step 2 design (approved with the brief, 2026-10-21)
- **Shot spec is the source of truth:** `shots/<id>/shot.json` (validated against
  `schemas/shot.schema.json`). `scene.sif` is a build artifact regenerated from it on every change.
  Tools edit intent, never XML.
- **Server:** `mcp/synfig_mcp/` as a uv workspace member on the official MCP Python SDK 2.x
  (`mcp`, MIT; `MCPServer`, the decorator-style API formerly called FastMCP). **stdio** transport
  now; streamable HTTP in Step 5 for the Windows node.
- **Motion composition:** per-bone channels; a later motion overrides a bone for its duration;
  idle motions (breathe, blink) are additive layers.
- **Face:** procedural vector eyes, lids, brows and the 9 Rhubarb mouth shapes (A–H, X) on the
  head bone (D-007).
- **Installs approved:** `mcp` 2.x, `jsonschema` 4.x, and the MCP Inspector via `npx`.

### D-029: Motion library v1 conventions (task 2.5)
- **Bone `role` (schema addition):** `rig.schema.json` bones gain an optional `role` (torso, head,
  upper_arm, forearm, thigh, shin, ...). Together with `side`, motions find limbs on any rig, not
  only on bones named like Pip's. It is additive and backward compatible; without it, the library
  falls back to the name minus an `_l`/`_r` suffix.
- **Channels:** motions write bone angles (offsets from rest), joint **shifts** (pixels; on the
  root they move the whole character) and eye states. `build_character` gained `shifts`.
- **Front-view motions** are honest about the view: nod is a head bob, and walk is a march in
  place (alternating leg lifts) because sideways leg swings read as stumbling. Real walks across
  the frame wait for side or three-quarter art (Step 4) plus scene placement moves (task 2.6).
- **Determinism:** "random" choices (blink intervals) come from a hash of the character and the
  start frame, so renders and tests are repeatable.

### D-030: Engine-neutral scene model (owner, 2026-10-21)
- **Context:** The OpenToonz spike (`docs/spikes/opentoonz.md`) showed a second engine is viable, and a
  hosted product would also need a browser preview. Neither engine runs in a browser.
- **Decision:** **Our schemas are the product's source of truth**, and engines are interchangeable
  backends ("compilers"). That covers film, shotlist, shot and rig, plus the motion library's
  channels: bone angles, joint shifts and eye states (D-029). A backend translates the scene model into
  its own project files (`.sif`, `.tnz`, ...) and renders them. A future web previewer (e.g. PixiJS) is
  just another backend.
  - **No engine-specific fields** in the schemas, the director's tool vocabulary, or `film.json`.
    Engine details live only in backend modules (e.g. `studio_core/engines/synfig/`, later
    `studio_core/engines/opentoonz/`).
  - MCP tool names and arguments stay engine-neutral. The server picks a backend. `synfig_mcp` may be
    renamed (e.g. `animation_mcp`) when the second backend lands.
- **Why:** Switch engines per tier or per customer without touching the director, assets or evals.
  Avoid lock-in if an engine stalls or changes format. Make browser editing possible.
- **Consequences:**
  - Audit the existing schemas for Synfig-specific fields during Step 2, and move any into the Synfig
    backend.
  - When the second backend arrives (ROADMAP Step 6), add conformance tests: the same shot through
    each backend should match on pose positions and timing, within tolerance.

### D-031: OpenToonz is the strategic engine; Synfig ships the first film (owner, 2026-10-21)
- **Decision:**
  - Synfig remains the engine for Steps 2–5, up to the first 60-second film.
  - Right after that, build an **OpenToonz backend** (ROADMAP Step 6) behind the engine-neutral model
    (D-030). Aim for it to carry every tier: children's cut-out, then anime limited animation.
- **Why (product view, not the owner's Mac):**
  - **License:** OpenToonz's own code is **BSD-3-Clause**. We can modify it, fork it, bundle it, and
    build and sign our own binaries, with no copyleft obligations. Its bundled third-party libraries
    keep their own licenses. Synfig is GPL-3.
  - **One engine for all tiers:** Plastic mesh deformation, a real multiplane camera (Z-depth
    parallax), compositing effects, and professional frame-by-frame tools.
  - **Built for render farms:** headless `tcomposer` plus a built-in farm system.
  - **Professional interoperability:** used in real anime production, so exporting a `.tnz` for
    hand polish is a feature for studios and serious creators.
  - **Active project:** ~7.8k GitHub stars, commits weekly. Tahoma2D is a fork using the same file
    format.
- **Evidence (spike, 2026-10-21):**
  - Python generated a `.tnz` from scratch: levels on twos, a pegbar hierarchy, eased keys, measured
    multiplane parallax, and an animated blur effect.
  - Plastic mesh deformation authored from code rendered.
  - Render speed: ~0.04 s per 1080p frame with 10 cores.
- **Risks and mitigations:**
  - **Undocumented `.tnz` format:** pin the engine version in the render image, and add golden-file
    tests.
  - **ToonzScript can't animate:** generate `.tnz` directly.
  - **The official macOS build is Intel-only and unsigned:** irrelevant for server rendering (D-032).
    For any desktop distribution, build our own signed arm64 binaries (BSD allows it) or use Tahoma2D.
  - Synfig work so far is not wasted: it is the first backend and the conformance reference.

### D-032: Final rendering runs server-side in containers (owner, 2026-10-21)
- **Decision:** Engine rendering and compositing run in **stateless Linux render containers** on CPU
  nodes:
  - OpenToonz `tcomposer` under a virtual display (Xvfb)
  - the Synfig CLI (already headless)
  - MLT / ffmpeg for assembly

  GPUs are only for AI asset generation. The same containers run on the owner's machines (Docker on
  the Mac, WSL2 on Windows) for development and self-hosting.
- **Why:** This is how a product scales. Rendering is CPU-bound and cheap, and containers pin engine
  versions. It also removes the dependence on any desktop build (signing, Rosetta, Gatekeeper).
- **Consequences:**
  - Render workers read inputs from object storage (MinIO/S3) and write outputs back. They keep no
    local state.
  - Temporal's render queue becomes a pool of render containers, and `render-win` is just one of them.
  - **D-001 (fully local) is unchanged for now.** Whether the product is a hosted web app, a desktop
    app, or both is an open owner decision. This decision only fixes *how* rendering is packaged and
    where it can run.

### D-033: Scene layout and shot assembly conventions (task 2.6)
- **Feet, not hips:** a shot spec character's `position` is **the point between its feet** (the
  lowest point of its rest pose), as frame fractions. Code lifts the rig's root by its feet offset
  (`rig.ground_offset_px`). The JSON shape is unchanged; this clarifies the approved field (D-028).
  Why: an LLM saying "stands at the bottom of the frame" means the feet. Read as the hips, the
  example spec's `[0.5, 0.92]` put Pip's legs below the frame.
- **Backgrounds:** `backgrounds/<id>/layers.json` (`schemas/background.schema.json`): equal-size
  layer PNGs, far to near, centred on the 1920x1080 design frame at rest, each with a parallax
  factor (0 = never moves, 1 = the characters' ground, >1 = nearer) and an `in_front` flag, plus a
  backdrop colour. Characters ride the factor-1 plane.
- **Camera presets are fixed numbers in code:** slow pans travel 240 design px over their duration,
  `push_in`/`pull_out` zoom x1.25, all eased. Zoom is about the frame centre; a solid backdrop
  fills any revealed edge.
- **Design resolution:** scenes are built once at 1920x1080 (120 px per unit) and rendered at any
  size, so previews and finals share one `scene.sif`.
- **Manual poses** (`poses`) are key poses: one key per bone at its time, held until the next key,
  clamped to joint limits. Motions starting later take the bone over from their first key.
- **Shot audio:** `render_shot` mixes the shot's dialogue lines at their start times
  (`shots/<id>/dialogue.wav`, mono 24 kHz, no volume normalization) into `shot.mp4`. Sound effects
  and music wait for Step 3.
- **D-030 audit (all schemas, 2026-10-21):** no engine-specific fields in `rig`, `shot`,
  `shotlist`, `film` or `background`: every field is pixels, degrees, seconds, frame fractions or a
  named preset. Two descriptions named Synfig internals (the bone GUID namespace, "turns into
  scene.sif") and were reworded. `scene.py`, `shot.py`, `sif/`, `rig.build_character` and the face
  layers are Synfig backend code; they move under `studio_core/engines/synfig/` behind the backend
  interface in ROADMAP Step 6. Until then, callers such as the MCP server use only engine-neutral
  entry points (a film folder, a shot id, a shot spec).

### D-034: MCP server design (task 2.7)
- **Two layers.** `studio_core/shot_spec.py` holds the director's verbs as engine-neutral functions
  that edit `shot.json`. `mcp/synfig_mcp/` is a thin MCP layer over them plus the Synfig renders.
  The same verbs can later serve another transport, the director loop, or a different backend.
- **Check the whole spec, refuse, explain.** Every edit re-checks the whole spec: schema, semantic
  rules, the film's assets (background, rig, view, bone names, line audio and cues) and a dry run
  of the motion library. A refused edit saves nothing and returns a fixable message
  (`ToolError` → `is_error`). Softer problems (no blink, a line cut off by the shot end) are
  warnings on success.
- **Changes from the brief's tool table:**
  - `apply_lipsync` takes a recorded `line_id` (plus optional text), not a cues path. The spec
    refers to lines by id, and each line's audio and cues live at fixed paths.
  - `add_parallax_background` takes only `background_id`. Parallax factors belong to the
    background asset (`layers.json`), not to a shot.
  - `apply_motion` takes `energy`, `side`, `cycles` and `target` as named arguments instead of a
    `params` object, so the model sees each one, with its range, in the tool schema.
  - `create_scene` takes `camera_move` and `zoom`; `camera_move` changes timing later.
  - `render_shot` takes `quality` (`preview` 640x360 or `final` 1920x1080) and `audio`.
  - **Added** `describe_film` (characters with bone names, backgrounds, recorded lines, motions:
    everything the model needs before editing) and `remove_from_shot` (undo by index).
- **Schemas from one source:** tool enums (motions, expressions, camera moves) come from the shot
  schema and the code constants; a test checks that no tool schema mentions an engine (D-030).
- **Safety:** `film` is a folder name under config `[paths] films`, and every id is pattern-checked
  before it becomes a path, so tools can't reach outside the film folder.
- **Results** are pydantic models (structured output with an output schema). Media results are
  absolute file paths inside the film folder.
- **Renders run in a worker thread** (`anyio.to_thread`), so the server keeps answering while
  Synfig works.
- **SDK:** `mcp` 2.3.0 (MIT). `build_rig` without a rig copies the placeholder puppet from
  `tests/fixtures/characters/pip` until Step 4 generates real ones.

### D-035: How Step 2's server is proven (task 2.8)
- **One `.mcp.json` for every client.** The repo-root `.mcp.json` starts the server with
  `uv run --quiet synfig-mcp`. Claude Code and the MCP Inspector both read it, so the Inspector
  checks the exact launch config the model will use.
- **Inspector checks are a script:** `scripts/inspector_check.py` drives the Inspector's CLI
  (pinned to 2.9.0, Apache-2.0/MIT) through all 14 tools plus calls that must be refused, on a
  scratch film. It's repeatable instead of a one-off click-through.
- **The done-when run is a script too:** `scripts/run_first_shot.py` runs Claude Code headless
  (`claude -p`) with only the synfig_mcp tools (`--strict-mcp-config --tools ""`), on a film
  with assets but no shot. The prompt describes the shot, not the tools. The script saves the
  transcript to `docs/learning/mcp-first-shot.md` and checks the result against the done-when.
  Why headless: the transcript is exact and complete, the run can be repeated (later with other
  models, and with the local director in Step 5), and the model can't fall back on shell or file
  tools.
- **Owner, 2026-10-22: the Claude Code run is skipped for now.** The `claude` CLI can't be logged
  in on this machine. The script is kept and the done-when item stays open. It closes when the
  script is run from a logged-in terminal, or through Step 5's director, a local LLM driving the
  same tools.

### D-036: Step 3 design (approved with the brief, 2026-10-22)
The owner approved `docs/steps/STEP-3-audio-mcp.md` as written. In short:
- **Split:** `audio_mcp` makes audio assets (lines, cues, music, sound search). Shot specs
  reference them by id, through `add_sound_effect` / `set_music` on the animation server.
- **Process model:** each model runs in its own env as a subprocess (D-016), with batched calls.
- **Voices:** `characters/<id>/voice.json` per character: voice or blend, speed, pitch step,
  loudness. Child-like voices come from casting youthful Kokoro voices, blends and speed, and if
  needed a small ffmpeg pitch step (pitch and formants together).
- **Files:**
  - each line is `.wav` + `.txt` + `.json` (metadata with a content hash, for caching)
  - lip-sync keeps Rhubarb's JSON as our format, computed from the final line audio
  - music metadata goes in `audio/music/<cue>.json`
- **Music:** the director gives intent (mood, energy, instruments) and code writes the model
  caption. Fixed seeds, no lyrics in v1. **Memory budget: peak ≤ 14 GB, no swap.**
- **Sound effects:** a CC0-only library with a license per file in its manifest. CLAP
  (`laion/larger_clap_general`) audio embeddings in Qdrant, plus descriptions and tags for
  hybrid search. The chosen sound id is stored in the shot spec.
- **Mix:** music ducked by a volume envelope computed from the line times, then two-pass
  loudnorm to −14 LUFS / −1.5 dBTP.
- **Safety:** text is checked before speaking; no lyrics.
- **Installs approved:**
  - CLAP weights + `envs/clap`, `qdrant-client`, more Kokoro voice packs
  - CC0 sources: Kenney, OpenGameArt, a curated BigSoundBank list
  - optional, decided at the named checkpoints: FSD50K's CC0 eval clips, ComfyUI's ACE-Step
    files, Chatterbox

### D-037: Audio file formats (task 3.1)
- **Five new schemas:**
  - `voice` (`characters/<id>/voice.json`)
  - `line` (`audio/dialogue/<line>.json`)
  - `lipsync` (Rhubarb's JSON, as is)
  - `music` (`audio/music/<cue>.json`)
  - `sfx_library` (`<sfx_library>/manifest.json`)
- **Shot schema, additive:** `sfx[].sound` (a library id) and `music_volume`.
- **Voice ranges are deliberately narrow:** speed 0.7–1.4, pitch −3 to +4 semitones, speech
  loudness −30 to −14 LUFS (default −20). Outside these, voices stop sounding natural.
- **`expressiveness` (0–1), not Chatterbox's `exaggeration`:** the voice file names the intent,
  and each TTS backend maps it (the spirit of D-030). Kokoro ignores it.
- **Mouth cues** must start at 0, run in order with no gaps or overlaps, and end within 50 ms
  of the audio length (Rhubarb rounds to 10 ms). A shot is refused if a line's cues were made for
  a different length of audio: they are stale after a re-take.
- **Line metadata is optional for now:** lines from before Step 3 (the fixture) have none. Once
  present, it is validated, and it must name the character who speaks the line in the shot.
- **License is a `const` (`CC0-1.0`)** in the library schema, so the CC0-only rule (D-036) is
  enforced by validation, not just policy.

### D-038: Voice pipeline details (task 3.2)
- **Two halves:** `scripts/audio/kokoro_batch.py` runs in `envs/kokoro` (one model load per
  batch; per-line voice overrides). `studio_core/audio/voices.py` does everything else in the
  workspace: text checks, the cache, ffmpeg post-processing, files and metadata.
- **Weighted blends:** the worker computes the weighted average of the voice packs itself.
  Kokoro's own `"a,b"` syntax only averages equally.
- **Loudness by linear gain, not `loudnorm`'s dynamic mode:** measure once (EBU R128), then apply
  one gain that reaches the voice's target, limited so the true peak stays ≤ −1.5 dBTP. A line
  only gets louder or softer, never reshaped, and the result is exactly repeatable. Short lines
  ("Wow!", 0.5 s) measured fine.
- **Trim keeps air:** 80 ms before and 120 ms after the speech, so soft onsets and endings
  aren't clipped. Rhubarb sees the same file.
- **The cache key** is a sha256 of the whitespace-normalized text, the voice settings (minus
  notes) and the model string. A line without an id reuses an existing line of the same
  character with the same hash. Replacing a line's audio deletes its mouth cues, which no longer
  match.
- **Text safety for now:** length, speakable characters, no addresses, and a small whole-word
  blocklist in `config/safety_blocklist.txt` (profanity and graphic violence). The Step 5
  classifier replaces it.
- **Test marker `models`:** for tests that run a local model (Kokoro here), like `render` for
  Synfig.

### D-039: Voice casting: Pip and Bunny (owner, 2026-10-22)
- **Pip:** casting page c12: `af_heart`, +2 semitones, 8% faster (child-like, bright).
- **Bunny:** casting page c03: `af_nicole`, unchanged (soft and close).
- Stored as `tests/fixtures/characters/<id>/voice.json`, so every film made from the fixtures
  (the demo film, tests) carries the cast. `scripts/make_demo_film.py` now adds Bunny to the
  demo film: the placeholder puppet plus Bunny's voice.
- `build_rig`'s placeholder copy leaves out `voice.json`. The placeholder's voice is Pip's, and a
  new character gets its own voice at casting.

### D-040: Lip-sync details (task 3.3)
- `studio_core/audio/lipsync.py` runs Rhubarb on the **final** line audio, with the line's text
  as `--dialogFile`, extended shapes G, H and X, and `pocketSphinx` for English voices
  (`phonetic` otherwise).
- **`speak` lip-syncs by default** (`cues=False` opts out), so every spoken line is ready for
  `apply_lipsync`.
- **Cache:** existing cues are reused when they validate and match the audio's length within
  50 ms. A re-take deletes the old cues, so they're always redone.
- `metadata.soundFile` is rewritten relative to the cues file (`../dialogue/l001.wav`), so film
  folders hold no absolute paths and can move (D-032 containers).
- Lines run in parallel, up to 4 at once.
- Measured: same audio + same text gives identical cues (Rhubarb is deterministic); 6.3 s for a
  5.6 s line under Rosetta.

### D-041: Music: memory fixed in place; compose conventions (task 3.4)
- **The fix (option a, no download):**
  - ACE-Step 1.5 runs with bf16 weights (it picks fp32 on MPS) and PyTorch's DiT and VAE only:
    `--precision bf16 --no-mlx-dit --no-mlx-vae` in `scripts/audio/acestep_compose.py`.
  - The ~30 GB peak (D-020) came from fp32 weights plus duplicate MLX copies of the DiT and the
    VAE. ACE-Step built the MLX VAE even with the MLX DiT off.
  - bf16 is applied by intercepting the handler's `dtype` attribute in a subclass; ACE-Step's
    code is untouched.
  - Option (b), ComfyUI's ACE-Step nodes (+6.3 GB download), isn't needed.
- **Measured (docs/benchmarks.md), 10 s cue:**
  - fp32: 21.0 GB, 5.7 GB swapped
  - bf16: 18.6 GB
  - bf16 + PyTorch VAE: **9.6 GB, no swap**, flat at 30 s (9.6 GB) and 60 s (9.7 GB)
  - Generation 6 / 14 / 25 s for 10 / 30 / 60 s of music; model load 7 s.
  - Budget: ≤ 14 GB (D-036).
- **`compose` conventions** (`studio_core/audio/music.py`):
  - 9 moods (playful, calm, curious, adventurous, silly, sleepy, sad, mysterious, triumphant),
    each with caption words, default instruments, a tempo range scaled by energy, and a key.
  - An allowed-instrument list. Every caption is "instrumental background music for a
    children's animated cartoon, ..., no vocals"; sad and mysterious moods say "never scary".
  - The seed comes from the cue id unless given. The request hash covers mood, energy,
    instruments, duration, seed, model and precision.
  - Cues are generated at ≥ 10 s and trimmed: 50 ms fade-in, 1.5 s fade-out. 48 kHz stereo,
    normalized to −20 LUFS (linear gain), so `music_volume` means the same for every cue.
  - No looping in v1 (shots are ≤ 60 s).
- **Memory guard:** `compose` unloads every Ollama model first, refuses while ComfyUI is
  running, and measures each cue's peak footprint (`/usr/bin/time -l`). A test fails if a
  10 s cue passes the budget.

### D-042: Indian voices with Indic Parler-TTS (owner, 2026-10-22)
- **Approved:** task 3.2b as proposed in the Step 3 brief.
  - Indic Parler-TTS (AI4Bharat, Apache-2.0, gated, 0.94B params, 3.75 GB) is a second TTS
    engine for Indian English and Indian languages.
  - Plus Kokoro's 4 Hindi voices.
  - Child voices stay a Step 7 item. A fine-tune would add new Parler speakers, and the
    pitch/formant processor can come any time.
- **`envs/parler`** (its own env: parler-tts pins `transformers==4.46.1`):
  - parler-tts at its last commit (`d108732`, 2024-12-10)
  - torch and torchaudio 2.5.1 (contemporary with that transformers)
  - two dependency overrides: `descript-audiotools==0.7.2` from PyPI instead of parler's git
    "temporary fix" (whose repo needs git-lfs), and `protobuf>=4` over audiotools 0.7.2's
    `<3.20` pin. The import check passes; inference is checked when the weights are in.
- **The owner's step:** accept the model's terms on Hugging Face and log in with a free token
  (allowed by AGENTS.md for gated downloads). Agents never handle the token.

### D-043: Sound-effect library and search (task 3.5)
- **Sources (CC0 only, checked 2026-10-22):**
  - all 8 Kenney sound packs (direct zips)
  - 10 child-friendly OpenGameArt packs, CC0 on each page: footsteps, wind, dripping water,
    completion sounds, a jump landing, bubble pops, power-ups, swishes, mixed SFX, retro synth.
    OpenGameArt's 10 s robots crawl delay is respected.
  - Skipped: one-file montages, a copy of Kenney's jingles, and the games-oriented packs
    (battle, zombies, firearms).
- **BigSoundBank is left out of the automated fetch.** Its robots.txt disallows `/UPLOAD/` (the
  audio) for every robot, and its ai.txt asks that the audio not be used for training. Our use
  is indexing, not training, but a script still shouldn't fetch what robots.txt forbids. The
  owner may hand-pick sounds there.
- **Children's filter by name:** files named for guns, explosions, blood, monsters, ghosts,
  screams, etc. are excluded at import, as are pack demo reels. "die-throw" (dice) was a false
  positive and was fixed.
- **Format:** every sound is converted to 48 kHz mono 16-bit WAV, and the originals are kept in
  `_downloads/`. The manifest is validated (CC0 const), and duplicate audio is dropped by hash.
- **Search:** CLAP (`laion/larger_clap_general`, `envs/clap`) audio vectors in Qdrant
  (collection `sfx`, cosine), with each manifest entry as payload.
  - Point ids come from the audio hash, so indexing is idempotent and incremental.
  - Ranking is hybrid: the 40 nearest by vector, plus sounds whose words match the query
    (rough stemming, prefix matching), re-ranked by similarity + 0.25 × the share of query
    words matched.
  - Why hybrid: pure vector search ranked dice throws above tagged footsteps for "footsteps on
    wood".
  - An optional duration cap is a Qdrant filter.
- **Measured:** 755 sounds, 16.3 min, 184 MB. Indexing took 34 s for 581 sounds; the 174
  added later took 14 s. 15 queries take ~5 s, mostly the CLAP worker starting.
  - The spot-check passes 15/15.
  - Known gap: no animal sounds (birds, dogs, cats, cows). Rain only finds dripping water.

### D-044: FSD50K's CC0 clips for animal and nature sounds (owner, 2026-10-22)
- **Approved:** after the spot-check showed no animal sounds, the owner chose to add FSD50K's
  eval split (6.26 GB download), keeping only CC0 clips.
- **Child-safe filter:**
  - Excluded labels: all recordings of people's voices and bodies (speech, singing,
    laughter, crying, screams, coughs, burps...), on privacy and consent grounds as well as
    taste, plus gunshots and explosions.
  - Clips whose title, description or tags contain blocked or adult words are dropped too.
  - Result: 3,515 of 4,914 CC0 eval clips, including 209 birds, 70 dogs, 67 cats, 94 rain and
    51 thunder.
- Only the chosen clips are extracted from the split zip. The archives are then deleted;
  the extracted CC0 originals are kept. Each clip's manifest URL is its Freesound page.
- **Measured:**
  - 3,513 clips added (2 were duplicates), so the library has 4,268 sounds, 9.6 h, 6.0 GB.
  - Indexing the new clips took 221 s.
  - The spot-check grew to 24 asserted queries (birds, dogs, cats, roosters, frogs, rain,
    thunder, waves, a squeaky door...), all passing, with scores ~0.6–0.7.
  - Remaining gaps: cows, a cartoon boing, a slide whistle.
- **`avoid` filter (after the owner's review of the done-when shot):** many field recordings
  carry background noise their labels name. The first birdsong the search chose for the
  meadow had road traffic in it. `find_sfx(..., avoid=["traffic", "vehicle"])` drops sounds
  whose tags or description mention those words, and searches a 4x larger pool so k results
  remain.

### D-045: The shot mix (task 3.6)
- `studio_core/audio/mix.py`: dialogue, sound-effect and music buses, built sample-exactly with
  numpy after ffmpeg converts every input to 48 kHz stereo.
- **Sound effects:** normalized to −20 LUFS, then scaled by `volume` (amplitude). Clips too
  short to measure as loudness are peak-normalized to −6 dBFS instead.
- **Music:** scaled by `music_volume` and ducked by a computed envelope (−10 dB, 150 ms attack,
  400 ms release; lines closer than both ramps count as one span), not a sidechain
  compressor.
- **Loudness:** one linear gain to −14 LUFS. Then a limiter at 4× oversampling, a true-peak
  check, and a trim if needed (≤ −1.5 dBTP). The 4× step exists because a click passed a
  sample-peak limiter at −0.4 dBTP.
- The numbers live in config `[mix]`. `render_shot` now writes `shots/<id>/mix.wav` in place
  of the dialogue-only `dialogue.wav`.

### D-046: The audio_mcp server and sound in shots (task 3.7)
- **`mcp/audio_mcp`** (workspace member `audio-mcp`, stdio, registered in `.mcp.json`).
  - Same conventions as `synfig_mcp` (D-034): cleaned docstrings, validated arguments,
    structured results with absolute paths inside the film, ToolError messages saying what to
    fix, slow work in a worker thread.
  - Seven tools:
    - `describe_audio`: voices, lines, cues, installed voices, moods, instruments, library size
    - `set_voice`: casts with Kokoro voices; Parler is refused while its download is deferred,
      as is any voice that isn't installed
    - `speak`: up to 20 lines per call, with cues
    - `lipsync`
    - `compose`: moods and instruments as schema enums
    - `find_sfx`: up to 10 queries per call
    - `preview_mix`: refuses a shot with errors
- **The animation server places audio by id:** `add_sound_effect` (the sound must be in the
  library; `query` defaults to its description), `set_music` (null removes the music), and
  `remove_from_shot` with kind `sound_effect`. `describe_film` lists the music cues.
  `shot_spec` gains `add_sound_effect` and `set_music`.
- **Why two servers:** making audio (models, minutes of work) and editing shots (instant,
  engine-neutral) are different jobs. Ids are the glue, so either side can change without the
  other.
- **Proof:** `scripts/inspector_check.py` now drives both servers from `.mcp.json`, 32 calls:
  - cast → speak → lip-sync → compose → search
  - add the sound, set the music, apply the line → preview the mix (−14.6 LUFS, −1.5 dBTP)
  - plus refusals

### D-047: Step 4 design (approved with the brief, 2026-10-22)
The owner approved `docs/steps/STEP-4-comfy-mcp.md` as written. In short:
- **Puppets from text:**
  - the skeleton is drawn in code and conditions SDXL through the xinsir union ProMax
    ControlNet (Apache-2.0), so joints are known, not estimated
  - front and three-quarter views on one turnaround canvas
  - faceless heads: the prompt, plus a code fill of the face area
  - parts are cut geometrically (silhouette + nearest bone) with joint caps filled in code
  - a drafted `rig.json` with its face block, and a palette
- **Backgrounds from text:**
  - generated at 1536×576, upscaled with Real-ESRGAN x4plus_anime_6B (BSD-3) to 2880×1080,
    with a low-denoise refine
  - split into layers with Depth Anything 3 MONO-LARGE (Apache-2.0, ComfyUI-native)
  - filled behind each layer with ProMax's repaint mode; parallax factors come from depth
- **Kept off the path:** non-commercial models (CMU OpenPose, thibaud OpenPose, DAv2
  Base/Large, DA3 Giant/Nested, FLUX.1 Kontext dev, FLUX.2 klein 9B, MAT, UltraSharp,
  TiledDiffusion) and unclear ones (LaMa's weights, DWPose's data).
- **Installs approved:**
  - ProMax ControlNet (2.51 GB), DA3 MONO-LARGE (1.34 GB), Real-ESRGAN x4plus_anime_6B and
    x4plus (BSD-3), SAM 2.1 base+ (fp32, 323 MB)
  - optional: the Fooocus inpaint patch (task 4.4); FLUX.2 klein 4B only if the owner chooses
    it at task 4.5

### D-048: Puppet skeleton templates (task 4.2)
- **One set of numbers:** `studio_core/puppet/skeleton.py` defines the puppet skeleton once and
  draws both the OpenPose conditioning image (COCO-18 keypoints, standard colours, thick
  lines scaled to the figure) and the rig's bones. A test finds each keypoint in the image by
  its colour and checks it against the rig.
- **Proportions:** taken from Pip (head ≈ 37% of the height; Pip's shoulder, hip and limb
  lengths).
- **Pose:** an A-pose with arms 25° out from hanging and legs 6° apart. Limbs stay clear of the
  torso for cutting.
- **Bones:** names, roles, sides, parents, limits and draw order identical to Pip, so the
  motion library and the face work on generated puppets unchanged.
- **Turnaround:** front and three-quarter figures on one 1344×768 canvas (an SDXL size), each
  86% of the height.
  - The three-quarter view faces screen-right, a 45° turn with cartoon depth: near side ×1.12,
    far side ×0.72, the far ear hidden.
  - A plain rotation read as a thin front view.
- **To check in task 4.4:** generated puppets rest with arms 25° out, not hanging like Pip's.
  Motions are offsets from rest (D-027), so a wave raises the arm 25° higher than on Pip. If
  that looks wrong on the first puppet, add a per-bone neutral offset rather than changing
  the pose.

### D-049: Character design candidates (task 4.3)
- **`design_character`** (`studio_core/puppet/design.py`): a description plus the film's style
  gives N turnaround sheets (front + three-quarter on one 1344×768 canvas). Seeds are recorded
  per candidate. Rounds add candidates (c1..c4, then c5..c8) rather than replacing them.
  `candidates.json` follows `schemas/design.schema.json`. The prompt template is code; the
  director writes only the description, which passes the shared children's-content word check
  (`studio_core/safety.py`, now also used by `speak`).
- **Two conditions from one skeleton:**
  - OpenPose at strength 1.0 for all steps (where the joints are)
  - a code-drawn **mannequin** as a "depth" image at strength 0.4 for the first half of the
    steps (where the body isn't)
  - **Why:** OpenPose alone let SDXL rest the arms against the body, and the front-view
    "limbs clear" check failed on 3 of 4 early sheets. With the mannequin at 0.6, both test
    seeds passed, but the character turned into a wooden doll. 0.4 for half the steps is the
    compromise.
  - Both conditions share one loaded ControlNet.
- **Faces:** SDXL draws eyes and a mouth whatever the prompt says. Weighting the negatives
  (`(eyes:1.5)`) didn't remove them, and it cost the arms. So the prompt asks gently, and the
  build step paints the face area over (as D-047 planned). The owner reviews faces by eye.
- **Normal mode by default:**
  - Fast mode (Lightning, CFG 1) ignores the negative prompt, so sheets came back on textured
    paper with scattered leaves, extra tails and a signature.
  - Normal mode takes about 4–8 min per sheet on this machine under the current memory pressure
    (the swap was nearly full), against about 1–2 min for fast mode.
  - `fast=True` stays available for quick looks.
- **Automatic checks** (`puppet/checks.py`, pixel geometry, no model):
  - a plain background
  - one figure per view (silhouette pieces grouped by the skeleton they sit on, and enclosed
    holes filled, so a white shirt inside an outline counts as figure)
  - height within 0.8–1.15 of the pose
  - at least 85% of the joints on the figure (the misses are listed)
  - front arms clear of the body
  - no extra shapes (props, text, shadows, clutter)
  - **Known limits:** thin text and clutter close to a figure can pass, and the colour key is
    only a check (the real cut in 4.4 uses SAM 2.1).
- **Review page:** `scripts/design_review.py` writes `characters/<id>/design/review.html`, with
  every sheet, its seed, timings and checks, and a toggleable skeleton overlay. The page is
  self-contained. It is safe to re-run: existing seeds are skipped. `--recheck` re-runs
  improved checks on existing sheets without generating anything.
- **One copy of every image:** `run_graph` deletes ComfyUI's own output copies and the
  uploaded conditioning images after each run, when ComfyUI is local. The film folder and its
  `run.json` are the record (the owner asked for no leftover files).

### D-050: Building a puppet from a design (task 4.4)
- **`build_puppet`** (`studio_core/puppet/build.py`) cuts the chosen candidate's front view
  (`choose_design` records it in `candidates.json`). The sheet was generated on a known
  skeleton, so the cut is geometry plus colour; the only model is SAM 2.1. Each step:
  - **Silhouette:** the colour key with holes filled, united with SAM 2.1's mask
    (`puppet/segment.py`). The key keeps fur tufts, and SAM keeps pale clothes that touch the
    background. A SAM mask with IoU < 0.85 against the key is rejected and reported. Kit:
    0.946, about 3 s.
  - **Head:** the upper head, plus the pixels below the nose line that are coloured like it
    and connected to it, with holes filled. A scarf or collar stays with the torso.
  - **Limbs:** each limb takes the pixels in a corridor along its bone (1.4 limb radii, cut
    across at the shoulders and hips; the nearest bone wins). Upper arms and thighs only take
    pixels coloured like their own core, so scarf ends, coat hems and tails stay with the
    torso. Fur wisps along a limb's outline join the limb.
  - **Torso:** everything else, including the tail (it doesn't animate in v1).
  - **Face:** marks clearly darker than their surroundings (eyes, brows, mouth) are painted
    out by diffusing the surrounding colours inward. The nose stays. Where the marks were
    becomes the face block, so the vector face (D-007) sits where the artist drew it.
  - **Joint caps:** elbows and knees get the sheet's own pixels on both parts. At the neck,
    shoulders and hips, only the part drawn behind gets a disc painted from its own colours.
    It is hidden at rest and fills the gap when a part turns. A cap on the front part changed
    the rest look (a pale disc of chin on the scarf).
  - **Arms hang at rest (D-048's open point):** the motions are offsets tuned on Pip's hanging
    arms. On the A-pose rest, +150° pointed the arm straight up behind the head. The arm parts
    are turned 25° about their joints so the rest is -90°, like Pip's. This is D-048's
    per-bone neutral offset, baked into the art, so the schema, the motions and the engine
    stay unchanged. The legs keep their 6° splay.
  - **Edges:** alpha comes from the distance to the background colour over a 3 px band, and
    the background's share is taken out of the edge colours, so there is no light fringe on
    a new background.
  - **Outputs:** `rig.json` with Pip's bone names, roles, limits and draw order, plus
    `parts/*.png`, `palette.json`, `build/report.json` (limb drift, face notes, silhouette)
    and debug images (parts, face before/after, three poses).
- **Limb drift** is measured per limb: how much of the bone line lies on the silhouette,
  and the offset of the limb's centre line relative to its radius. A limb that fails is
  flagged. Kit's worst is 0.33 of a radius, so all pass.
- **The wave keeps the hand clear of the head** (`motions/library.py`). The raise is lowered
  in 5° steps until the hand, even at the forearm's inward swing, is outside the head's box.
  Kit's big head and ears hid the arm.
  - Pip is unchanged up to energy 0.75. Above that he now stops at 150° instead of 160°,
    because at 160° his hand also went behind his head on the swing.
  - This is a small change to approved motions.
- **ComfyUI cache:** a repeated graph is answered from ComfyUI's cache, pointing at outputs
  that `run_graph` has already deleted. Every run's save prefix now gets a fresh token. The
  segmentation work found this bug.
- **Test render:** `scripts/preview_puppet.py` stages the character next to Pip in shot
  `s00_sh01`. Scene 00 is reserved for test shots, outside any story's numbering. In the shot
  the character rests, waves, blinks and speaks a lip-synced line. A character without a
  voice gets a placeholder voice (casting candidate c13, af_bella +1.5 semitones) until the
  owner casts it.
- **Known limits:**
  - The three-quarter view isn't rigged yet (task 4.5).
  - The tail is torso.
  - The head split fails if clothes share the head's colours.
  - Cut edges have no drawn outline.
  - SAM settings that must stay: fp32 only, and tight boxes with no negative points (see
    `docs/learning/segmentation-sam2.md`).

### D-051: The three-quarter view, and checking it against the front (task 4.5)
- **One rig, two views:** `build_puppet` cuts both figures of the turnaround the same way
  (`_cut_view`) into `views.front` and `views.three_quarter`, with parts in
  `parts/<view>/`.
  - **Three-quarter draw order:** the far arm and both legs behind the torso, then the near
    arm, then the head.
  - **Faces in any view:** the nose is the solid dark blob nearest the skeleton's nose line.
    The eyes are the two best marks above it (large, and lower rather than higher, so not the
    brows), far enough apart. Pupils inside an eye's ring are filled before the paint-out.
  - **Colour rule on every limb:** whole upper arms and thighs, and the top 60% of forearms
    and shins. Wrist outlines, paws and shoes stay with the limb; tails crossing a shin don't.
  - **Far-side drift:** in the three-quarter view, far-side limbs (the character's left)
    overlap the body, so their drift can't be measured from cross-sections. Only coverage
    is judged there.
- **Consistency between views** (`puppet/consistency.py`, no model). Measured per region
  (head, torso, arms, legs):
  - **Paint:** colour covering ≥ 3% of a region in one view that the same region of the
    other view lacks. This uses 8×8×8 colour histograms with neighbouring cells counted as
    the same paint. Palettes gave false alarms, because median cut blends a hat's green with
    the fur.
  - **Head size:** head height as a share of the figure's height, within 10% between views.
  - **Turn:** the drawn nose's offset from the head's centre line, relative to what the
    three-quarter skeleton asked for. It must reach at least 50%.
- **Kit (c3) fails:** a hat covers 10% of the three-quarter head only, and the
  three-quarter figure is barely turned (5% of the turn asked). It renders and animates in
  that view (`scripts/preview_puppet.py --view three_quarter`, facing Pip), but it is a
  front view with a hat.
- **The brief's fallback (owner decides).** FLUX.2 [klein] 4B, from research with sources,
  not yet tried:
  - **License:** Apache-2.0 for the weights, the Qwen3-4B text encoder and the VAE. Only the
    9B is non-commercial.
  - **Size:** the ComfyUI bf16 files total about 16.1 GB (7.75 + 8.04 + 0.34). The brief's
    "~13 GB" was a VRAM figure. fp8 doesn't run on MPS, so it has to be bf16.
  - **ComfyUI:** native core nodes (reference-latent editing), with official templates. Our
    v0.42.1 is new enough.
  - **Unknowns:** no published evidence that it turns *cartoon* characters cleanly. Speed on
    an M4 is unmeasured (estimated 1–2 min per edit).
  - **Alternative if klein drifts:** Qwen-Image-Edit-2511 (Apache-2.0) as a Q4 GGUF
    (13.2 GB), with a Qwen2.5-VL-7B text encoder and an Apache-2.0 "multiple angles" LoRA. It
    is tight on memory.
  - **Options:**
    - (a) install klein 4B bf16 (under the 20 GB ask-first line) and trial one front →
      three-quarter edit of Kit
    - (b) ship front-only puppets for now, and leave three-quarter to character LoRAs
      (Step 7)

### D-052: FLUX.2 klein 4B trial for the three-quarter view (task 4.5, owner approved)
- **Installed:** FLUX.2 [klein] 4B distilled (bf16), its Qwen3-4B text encoder and the FLUX.2
  VAE.
  - All three are Apache-2.0.
  - 16.13 GB from Comfy-Org's repack, sha256-verified. The model file is byte-identical to
    Black Forest Labs' own.
  - Recorded in `config/models.toml` and MODELS.md. bf16, because fp8 doesn't run on MPS.
- **Graph** (`comfy_graphs.flux2_edit`), following Comfy-Org's template:
  - each reference image goes through VAE encode into a ReferenceLatent on both the positive
    and the zeroed negative
  - cfg 1, euler, 4 steps, Flux2Scheduler, explicit output size
  - at cfg 1 the negative prompt is never used, so kid-safety rests on the prompt and the
    inputs
- **Trial** (`scripts/spikes/flux2_three_quarter.py`): Kit's front figure, two prompts (text
  only, and with the three-quarter mannequin as a second reference), two seeds, two rounds.
  Each edit is placed where the rig's three-quarter view goes and measured like the SDXL
  figure.
  - **Turn: solved.** The edits turned 56–102% of what the skeleton asks, against SDXL's 6%.
    All eight are the same fox (scarf, jacket, shirt, trousers, paws, tail) with no hat. The
    line style is a little flatter than the SDXL front.
  - **Pose: not controlled by words.** In round 1 the arms rested against the body. In
    round 2, asked for 25° out, they went nearly horizontal. 75–88% of the rig's
    three-quarter joints land on the figure. The cutter would need to fit the arm bones to
    the drawing first.
  - **Ground shadows** in 2 of 4 edits per round, even when asked for none.
  - **Pose reference:** the mannequin as image 2 didn't steer the pose better, and costs
    about 100 s more.
  - **Time:** 138–163 s per edit text-only, 239–260 s with the pose reference, on this
    machine (swap busy).
- **Measures fixed on the way:**
  - The turn is now the centroid of the face's marks within the face band (45–92% of the
    head's height), not the nose. A strongly turned nose sits on the outline, where it can't
    be told from it, and the far ear's inner shading pulled the old measure the wrong way.
  - Eye pairs are chosen by matching size and height. The nose next to an eye had won as a
    "pair".
- **Proposed wiring (for the owner's go-ahead):**
  - `build_puppet` gets an option to replace the sheet's three-quarter figure with a klein
    edit of the front: the round-2 text prompt, N seeds, the best by the checks.
  - Before cutting, the arm bones are fitted to the drawn angles, then the arms hang as now.
  - Ground shadows are cut away by the colour key.

### D-053: The three-quarter view comes from FLUX.2 klein (owner approved, task 4.5)
- **`build_puppet(three_quarter="klein")` is the default.** `puppet/turn.py` redraws the
  chosen sheet's front figure turned (D-052's round-2 prompt) for seeds 1–3. For each seed it:
  - drops ground shadows: colourless pixels at the feet, keeping any sizeable piece only the
    shadow had joined (shoes drawn apart from the legs)
  - places the figure where the three-quarter view goes: the front figure's height, soles on
    the skeleton's sole, legs centred on its pelvis, edges unmixed from klein's background
  - scores it with the cut's own checks: turn ≥ 0.5, no paint only one view has, the most
    three-quarter skeleton on the figure once fitted, a turn near 1
  - The best sheet and every seed's edit, `run.json` and scores land in
    `design/<candidate>/three_quarter/`.
  - It is made once (about 7.5 min for Kit), then reused. `regenerate_turn` makes new edits;
    `turn_design(replace=True)` re-places and re-scores existing edits without the model.
  - `three_quarter="sheet"` cuts SDXL's own figure as before.
- **Limbs fitted to the drawing before the cut** (`puppet/fit.py`, written by a subagent), in
  every view, without changing drawings that already follow the skeleton (both SDXL c3
  figures stay unchanged):
  - Arms: the angles are fitted, and so is the forearm's length, up to the drawn paw's end.
  - Legs: fitted as straight bars under the torso.
  - Shoulders: slide (up to 0.75 of an upper arm) onto the drawn arm's centre line. On
    Kit's near arm, upper-arm coverage went from 24% to 100%.
- **Arms drawn behind the torso** (the far arm in a three-quarter view) start where they come
  out from behind the body. The cut walks in from the hand until the cross-section stops
  being narrow. Pixels before that point stay with the torso (scarf, chest).
  - A mostly hidden upper arm becomes a plain sleeve in the forearm's colour.
  - A partly hidden limb's stretch is painted from its own visible pixels.
  - The forearm's elbow disc is repainted from the forearm itself.
  - All of this is opaque, and hidden at rest behind the torso.
- **Faces in any view:**
  - **Nose:** the lowest compact, near-black blob around the nose line, anywhere in the head.
    A turned nose sits on the outline.
  - **Eyes:** dots or arcs (not lines), a little above the nose and within half a head of it,
    so ear shading is excluded. One found eye takes its side from the skeleton's offsets to
    the nose.
  - **Size from the front:** the three-quarter face takes the front's eye size, brow width
    and mouth width, scaled by head width. A redrawn view's tiny dot eyes would otherwise
    shrink the character's eyes.
- **Other fixes:** a pale face inside the outline is figure (its eyes were being dropped as
  islands), and paws past the wrist get a wider strip.
- **Kit:** seed 3 chosen.
  - Turn 108% of asked.
  - Consistency clean.
  - Joints on the fitted three-quarter skeleton: 88%. The rebuild takes 27 s once the klein
    edit exists.
  - In the test render (`preview_puppet.py --view three_quarter`), Kit faces Pip, waves with
    the far arm, blinks and talks.

### D-054: Backgrounds from text: drafts, then one finished plate (task 4.6)
- **`generate_background`** (`studio_core/place/design.py`): a description plus the film's
  style gives N drafts at 1536×576 (an SDXL 8:3 bucket).
  - The prompt template is code. It pushes the described things into the middle and far
    distance, keeps the front a plain lawn "like a stage floor", and excludes people and
    animals. The first drafts put big flowers and the stream along the bottom.
  - Seeds are recorded, and rounds add drafts. The records live in
    `backgrounds/<id>/design/plates.json`, which follows `schemas/plates.schema.json`.
- **Only the chosen draft is finished.** `choose_background` records the pick, then runs
  `comfy_graphs.finish_plate` (written by a subagent) and saves `backgrounds/<id>/plate.png`
  for task 4.7.
  - The finish: Real-ESRGAN x4 anime_6B, scale to 2880×1080 (lanczos), then a low-denoise
    SDXL refine (0.3, 10 steps) in the same style.
  - **Why:** the finish takes minutes on this Mac (SDXL at about 3 MP), so finishing every
    draft would multiply that.
  - `txt2img` was refactored to share the style setup with the finish (`_add_style`); its
    JSON is byte-identical, and the golden files are unchanged.
- **Ground-band checks** (`place/checks.py`, no model), on rows 78–97% of the height where
  characters' feet go:
  - edges: at most 10% of pixels at luma gradient ≥ 20
  - colours far from the band's main ones: at most 20%
  - the top and bottom must differ
  - Calibrated on real drafts: a valley with big foreground flowers and the stream along the
    front failed both (14% edges, 48% covered).
  - **Known limit:** water or a pond filling the whole band reads as "open"; a vision check
    could catch it later (D-018).
- **Review:** `scripts/background_review.py` makes drafts (safe to re-run), writes a
  self-contained page, and `--choose cN` finishes one.

### D-055: Splitting a plate into parallax layers (task 4.7)
- **`split_depth_layers`** (`studio_core/place/layers.py`): plate → depth → bands → fills →
  `layers/*.png` + `layers.json`, validated by the background schema. Steps:
  - **Depth:** DA3 MONO-LARGE at resolution 1512 (`comfy_graphs.depth_map`, written by a
    subagent), from the brief's one-time comparison on the meadow:
    - 1512 separates branches in about 5 s; 1008 merges them; 2016 adds sky specks and is
      3× slower
    - 2520 ran out of Metal memory and returned an all-black map with no error, so flat
      maps are refused
    - DAv2-Small gave soft halos and put the distant tree line as far as the sky
    - The map is bright = near with the sky exactly 0, linear in depth (not disparity).
  - **Bands:**
    - sky: the farthest region touching the top
    - far / middle / ground: cuts at the 35% and 70% depth quantiles, each moved to a valley
      of the depth histogram
    - tiny bands merged; islands joined to the band around them
    - foreground: only for things clearly nearer than the ground at their own row, low in the
      picture
  - **Parallax:**
    - ground = 1.0, measured at the characters' feet row
    - other bands: their nearness over the ground's (a perceptual multiplane spread)
    - sky 0.05
    - capped at 0.9 × (width/2 − 960) / PAN_PX, which is 1.8 at 2880 wide, so no layer edge
      enters the frame during a pan (found by the pan-render subagent)
  - **Fill behind:** each farther layer is repainted by SDXL plus ProMax "repaint"
    (`comfy_graphs.repaint_fill`, written by a subagent).
    - Masked pixels are black in the control image and grey in the latent
      (VAEEncodeForInpaint), with a feathered composite. Fills run at 1536×576 and are
      scaled back to the plate.
    - The fill covers what nearer layers hide within PAN_PX + 32 px of the band; the sky
      layer is filled everywhere.
    - Prompts per layer: sky, the far distance, the middle distance, ground.
- **Test render:** `scripts/preview_background.py` (written by a subagent) pans over the
  layers with an optional character. It checks for holes by rendering over a magenta probe
  backdrop and counting magenta pixels, plus a geometric check of layer edges; it exits
  non-zero on a hole. In development it caught unfilled cut-outs, narrow layers, over-fast
  foregrounds and zoom-outs.

### D-056: The comfy_mcp server (task 4.8)
- **`mcp/comfy_mcp`** (workspace member `comfy-mcp`, stdio, registered in `.mcp.json`): a thin
  layer over `studio_core` (`puppet/`, `place/`, `preview/`), with the same conventions as
  `synfig_mcp` and `audio_mcp` (D-034, D-046). Nine tools:
  - `describe_art`: the film's style and the styles there are (label, commercial use), every
    character (candidates with their checks, the chosen one, the rig's views, whether the views
    are consistent, whether it has a voice) and every place (drafts, the chosen one, plate,
    layers). Each comes with a `next_step` worked out from the files, so the server keeps no
    state.
  - `design_character` (n 1–8, seed) and `choose_design`. Fast mode isn't offered: it ignored
    the negative prompt in task 4.3, and the scripts still have it.
  - `build_puppet` (only `name`): from the chosen design, with the three-quarter view redrawn
    from the front (D-053). The candidate override and the redraw switches stay in the scripts.
  - `preview_puppet`: **refuses a character without a voice** instead of casting the
    placeholder, because casting is the sound server's job (D-046). The script still casts it.
  - `generate_background`, `choose_background` (always finishes the plate; denoise fixed at
    0.3, D-054) and `split_depth_layers`.
  - `preview_background`: returns `ok` and the holes, and takes `quality` (preview 640x360 or
    final 1920x1080) like `render_shot`.
- **The previews moved into `studio_core/preview/`** (`preview_puppet`, `preview_background`,
  `PreviewError`; written by a subagent). With no `out` folder, their video and contact sheet
  stay in the test shot's folder inside the film, as a tool result must (D-034). The scripts
  are thin command-line wrappers and keep their `renders/` outputs.
- **Long jobs** (2–16 min) run in a worker thread and send MCP progress notifications:
  - the progress value is the elapsed seconds, so it always increases
  - the message is the latest news, e.g. "c2 drawn: ok"
  - a heartbeat goes out at least every 15 s
  - Art jobs share one lock per server (one large model at a time); a waiting call says so.
  - Each preview has its own lock, because each replaces one test shot. Previews don't wait
    for art jobs, since Synfig renders on the CPU.
  - Cancelling waits for the worker thread, so the lock is held until the GPU work ends.
- **Refuse before the GPU:** request checks (id pattern, description length, the word list, n)
  run before the lock, so a typo isn't queued behind a ten-minute job. A hand-made puppet (a
  rig with no design candidates, like Pip) can't be redesigned under its own id, so
  `build_puppet` can never overwrite it.
- **No engine or model names** in tool names, descriptions or schemas (no Synfig, OpenToonz,
  ComfyUI, SDXL or FLUX). A test guards this. The server is called `comfy_mcp` after the app it
  wraps, like `synfig_mcp`.
- **Inspector check:** `describe_art`, `choose_design` and both previews run for real. The GPU
  jobs only get requests they must refuse, because each takes minutes. Task 4.9's scripted
  client runs them end to end.

### D-057: Proving Step 4 through MCP, and what the runs found (task 4.9)
- **`scripts/run_step4_shot.py`:** a scripted MCP client starts the three servers from
  `.mcp.json`. From words, it makes a new character (Bo, "a cheerful little brown bear cub
  wearing blue dungarees") and a new place (an orchard), checks both with the previews, then
  builds and renders a shot with Bo and Pip using only tool calls. The transcript is
  `docs/learning/mcp-step4-shot.md`. Outside MCP there are only two setup steps: creating the
  empty film (no tool makes films yet) and stopping a ComfyUI left running, so the music model
  can load.
- **The script plays the director where the owner would choose:**
  - It takes the first candidate whose checks pass, drawing another round if none does.
  - If `build_puppet` reports that the views don't match, it builds from the next passing
    sheet (at most 2 builds).
  - It orders the work by the memory rule: music first, then the art jobs, then Synfig
    (CPU).
- **Bugs found and fixed.** Bo is the first character after Kit, and several rules turned out
  to be fitted to Kit:
  - **The three-quarter redraw added a scarf.** The FLUX.2 klein prompt named "scarf". It
    now carries the candidate's own description and asks for nothing added. Existing
    redraws are still reused, so Kit's approved view doesn't change.
  - **Background between touching legs was cut into the leg parts** (white strips).
    `fill_holes` filled every enclosed region. Given the image, it now leaves open a region
    of the background's own colour (median within 15) that surrounds no figure pixels.
    - Measured: such gaps sit 5–7 from the background; Kit's cream face and chest sit 30–42.
    - A face as pale as the background still surrounds its eyes, so it stays filled.
  - **A muzzle below the skeleton's nose line went to the torso**, so it stayed behind when
    the head turned. The head's colour rule only knows the colours above the nose line. Now
    figure pieces between head pixels join the head, along a row (a muzzle between the
    cheeks) or a column (a chin in a notch at the profile's edge), if they are at least 1% of
    the head. A scarf has neither cheeks beside it nor head below it.
  - **An eye was kept as the nose.** In Bo's three-quarter view the nose sits on the
    outline and joins it into one long blob, and the open mouth below it is a smaller black
    blob. The search took the lowest compact black blob, so it got the near eye or the
    mouth, and that eye stayed painted while code drew the face. Now thin strokes are opened
    away before the search, the biggest compact black blob is the nose, and a mark sharing
    pixels with it isn't painted out.
  - **Bo's face came out deformed** in the run 2 shot (owner review): three eyes, two noses,
    one brow over both eyes, and a seam across the muzzle. After the nose fix, three more
    causes:
    - The snout tip under a profile's nose was cut onto the torso. Figure inside the head's
      convex hull, below the nose line, now joins the head (with the row and column rules,
      at least 1% of the head).
    - Klein's drawn open mouth, joined to the nose, was kept with it. A mark sharing pixels
      with the nose is now painted out except for the nose and a 3 px rim.
    - The face zone is centred on the head, so a mouth beside a turned head's snout was never
      cleaned. The zone now also takes in a box around and below a found nose, staying 6 px
      inside the outline. A speck right at the snout's edge can remain.
  - Kit's head masks are pixel-identical before and after all these fixes, and so is his
    face, except that the snout box paints out a 134 px leftover of his drawn smile and
    moves his mouth anchor 4.6 px. That only happens if Kit is rebuilt; he hasn't been.
  - **The plate finish failed on MPS** ("tensor dims larger than INT_MAX" in an untiled 3 MP
    VAE decode). It depended on free memory: ComfyUI only falls back to tiles on
    out-of-memory errors. The encode and decode are now tiled at 1024 px, and ComfyUI
    averages three tilings, so there are no seams.
  - **Progress news** says what is being made now ("c1 drawn (1/3): ok; drawing sheet 2 of
    3").
- **Open (not fixed; for the owner):**
  - **A white snout on a redraw can be lost.** With c1, klein drew the snout near-white with
    no outline at the profile edge. No colour key or SAM mask separates it from the light
    background, so the snout came out transparent. A likely fix: ask klein for a backdrop
    far from the character's colours, and hand its exact figure mask to the build. That
    changes klein's output for every new character, so it needs trials first.
  - **The three-quarter cut doesn't generalise yet.** Kit's figure follows the skeleton
    closely. Bo c2's redraw has arms held out and wide dungaree legs, and the limb fit didn't
    follow it (`limbs_ok` false in both views). Its torso part ended up holding pieces of
    other parts:
    - the chin and muzzle (fixed since by the column rule)
    - part of the far arm
    - the dungaree cuffs and leg outlines
    - thin outline dashes from where the arms were drawn, left behind when the arms are hung
    - In the bent-knee test pose the far leg falls apart. Run 2's shot used this build.
    - Fixing it means making the cut follow drawings that differ from the skeleton, tried on
      several varied characters, not tuned on one: a task of its own.
  - **"Head 116% as tall"** rejected every klein seed of c1. It may be klein's real
    proportion for this character, or partly a measurement effect. To be looked at with the
    above.

### D-058: The coding agent: Claude Code → DeepSeek Harness (owner, 2026-10-26)
- **Decision:** the repo no longer depends on Claude Code. `CLAUDE.md` is renamed to `AGENTS.md`
  (agent-neutral; every live reference is updated, the historical PROGRESS log is kept), and
  `scripts/run_first_shot.py` is rewritten as a scripted MCP client instead of a headless
  `claude -p` run.
- **Why:** the owner moved to a different coding agent and wants the project agent-agnostic. The
  MCP boundary already was (D-035, "one `.mcp.json` for every client"); only the development
  client and one done-when script named Claude Code.
- **Consequences:** Step 2's open done-when item now closes via `scripts/run_first_shot.py`, a
  scripted `synfig_mcp` client (verified 2026-10-26: 10 tool calls → a 1080p, 240-frame shot,
  all checks pass). The `claude` CLI is no longer required anywhere in the repo.

### D-059: New steps, and a production-grade goal (owner, 2026-10-26)
- **Decision:** the final output of the project is **production-grade films**, and the roadmap
  grows to match:
  - **Step 4B, animation quality** (proposed 2026-10-22, now approved): a generalised cut, clean
    edges, bending limbs, hands and secondary parts, walking across the frame, a pose-sweep check.
  - **The old Step 7 ("level up") is split** into Step 7 evals, Step 8 durable pipeline (Temporal,
    MinIO), Step 9 training (LoRAs, SFT + GRPO), Step 10 series and Step 12 future tiers.
  - **Step 11, production release (v1):** met when the test prompts produce films that pass the
    production-grade bar with no manual steps.
  - **The production-grade bar** (ROADMAP) lists targets for picture, animation, lip-sync, sound,
    story, rights, reliability, deliverables and operations. Its numbers are proposals for the
    owner to confirm in the Step 4B and Step 5 briefs.
- **Step numbers are stable ids.** Steps 0–6 keep their numbers, because about 50 places in code,
  schemas, tool docstrings and the history refer to them. A step inserted later gets a letter.
- **Consequences:**
  - References to the old Step 7 in older entries map as follows: evals → Step 7, Temporal → Step 8,
    LoRAs and fine-tuning → Step 9, longer films → Step 10, tiers → Step 12. Live docs are updated;
    the history is kept as written.
  - Temporal moves from "Step 5+" (D-011, ARCHITECTURE) to Step 8. The Windows laptop still joins in
    Step 5, as a plain render node.
  - The owner decision on hosted vs desktop delivery (open since 2026-10-21) is now needed by Step 11.

### D-060: Step 4 closes against a pass bar on a varied cast; the no-nose face fix (owner, 2026-10-26)
- **Decision:** the varied-cast work (D-057's open item) is time-boxed to a pass bar instead of
  "until every character is perfect". Cast: Kit (fox), Bo (bear), Pim (bird), Mia (child), Bolt
  (robot). **Pass bar:** at least 4 of the 5 build with their views matching, every limb on its
  bone (`limbs_ok`) and the face found in both views. Whatever still fails is recorded as tracked
  manual cleanup (the Step 4 done-when allows it) and carried into Step 4B (ROADMAP).
- **First fix, faces with no dark nose (Pim):** the nose finder took the bird's only eye for the
  nose (a brown eye through the "solid mark nearest the nose line" fallback, or a near-black one
  through the black-blob rule), so no eyes were found. Now, when the mark taken for the nose
  leaves no eye above it, `clean_face` reads the face again with no nose (`no_nose=True`): the
  marks are eyes (compact: at most 2:1; a second eye at least 0.35 of the first's area, so a
  feather arc isn't one), the window for eyes reaches 0.5 head widths above the skeleton's nose
  line, and one eye places the other from the skeleton's offsets as before.
- **Verified:** the Kit, Bo (two films) face results are identical before and after (cleaned pixels,
  anchors and notes), and Pim now finds an eye in both views. A unit test with a bird-like face
  fails without the fix. The remaining Pim problems (SAM rejection, consistency flags on the
  beak and feet, head 110% as tall, far arm and shins) are still open.

### D-061: Small view-only paint is a note, not a drift problem (task 4.5 check, 2026-10-26)
- **Context:** Pim's (the bird's) only consistency problem was its yellow beak: 4.7% of the
  three-quarter head in a colour the front head lacks. A turned head shows features the front
  doesn't (a beak in profile, the side of a shoe). Kit's hat, the thing the check exists for, is
  about 10% of the head.
- **Decision:** `compare_views` still reports paint from 3% of a region (`MIN_SHARE`), but only
  paint from 7% (`TOLERATED_SHARE`) is a problem. Between 3% and 7% it goes to `report["notes"]`
  and the region listing, with `"tolerated": true`, so it stays visible and doesn't block a build.
- **Limits:** a hat smaller than about 7% of the head now passes as a note. The synthetic hat in
  the tests is 9.7%, so the margin is thin; the number comes from two characters, so re-check it
  with Mia and Bolt. The head-size and turn checks are unchanged.
- **Verified:** Kit and Bo (two films) have identical reports before and after; Pim's consistency
  now passes with the beak as a note. A unit test with a small beak fails without the change.
- **Correction to the bird trial notes:** with the current sheets Pim's head share is 0.352 front
  vs 0.369 three-quarter (within the 10% tolerance), and no feet colour is flagged. The "110% as
  tall" and "feet" findings came from the other candidates in that trial.

### D-062: Pim's far arm: white clothes are figure, and a sleeve of its own is cut as drawn (task 4.5, 2026-10-26)
- **Cause:** the loose limbs were one bug upstream of the limb code. `fill_holes` (D-057) leaves an
  enclosed region open as "background seen through the figure" when its colour is within
  `BG_HOLE` = 15 of the background and it surrounds nothing. Pim's white shirt and sleeves sit
  13-15 from his near-white background, so they were cut out of the silhouette: only their
  outlines remained, the limb fit then locked onto an outline stroke (the near upper arm at -95
  instead of -141), and the arms ended up in the torso part.
- **Fix 1:** `BG_HOLE` is 10 (gaps between touching legs measured 5-7, Bo "under 10"). Pim's
  front view now passes `limbs_ok`; in the three-quarter view both arms and both legs follow the
  drawing.
- **Fix 2:** `complete_hidden`: an upper arm that comes out from behind the body halfway along
  (t from 0.5 to 0.75) is a plain sleeve in the forearm's colour only if what shows is that
  colour (within 40). A sleeve of its own colour (Pim: white over a blue forearm) is cut as
  drawn, so it moves with the arm and doesn't stay on the torso as a ghost arm. From 0.75 on
  it is a plain sleeve whatever shows (Kit: 0.9; the visible bit there is scarf and body).
  Bo (0.6, the same fur) is unchanged.
- **Verified:** Kit and both Bo builds (SAM off, existing redraws) have byte-identical part
  images and rig before and after; a unit test for each rule fails without it.
- **Still open for Pim:** a brown disc at the far elbow when the arm is raised; small fragments
  beside the body at rest; the far leg falls apart in the bent-knee test pose (as Bo's did,
  D-057), and `shin_l` coverage is 0.81 against 0.85 because the drawn sole is shorter than the
  skeleton's. Pim was not rebuilt with SAM or through MCP.
- **Limits:** 0.75 and 40 come from three characters.

### D-063: The far elbow disc (a half-applied D-062) and white leg highlights (2026-10-27)
- **Correction to D-062:** `complete_hidden` decided "cut as drawn" for a far sleeve of its own
  colour, but the painting loop in `_cut_view` still tested `t >= 0.5` and turned the arm into a
  plain sleeve anyway, repainting the elbow disc from the forearm's outline-coloured edge: the solid
  brown disc at Pim's far elbow. `complete_hidden` now returns `sleeve` and the loop uses it. Pim's
  raised far arm shows the white sleeve and no disc; Kit and Bo are byte-identical.
- **Far leg in the bent-knee pose:** the cause was not the near leg covering it (no pixel of the near
  leg lies in the far leg's corridor; a prototype that completed such pixels changed nothing). Pale
  highlights inside the leg, such as Pim's white shine on cream trousers, are not the leg's core
  colour, so the colour rule left them on the torso, where they stay behind when the leg moves
  (4,564 pale pixels on Pim's torso below the hips). `join_leg_highlights` gives a leg the pale
  (luma over 235) pixels no limb owns that lie between its own pixels along a row, inside its corridor.
- **Why only pale:** the same rule for any colour also moved 40-150 pixels of mid-tone shading and
  dark seams on each of Kit's legs, and Kit had to stay unchanged. Dark seams between Bo's legs
  (2,331 dark pixels on his torso below the hips) are therefore still left on the torso.
- **Verified:** Kit's part images and rig are byte-identical before and after (SAM off, existing
  redraws); Pim's three-quarter changes are the far arm, both shins, `thigh_l` and the torso, and Bo's
  (both films) are the shins and torso. A unit test for the highlight rule and one for the sleeve
  decision fail without their code. The suite passes.
- **Still open:** Bo's and Kit's dark seam dashes between the legs; the bent-knee pose still shows a
  wedge where the shin swings away (a rigid-part limit, joint caps cover part of it); Pim's `shin_l`
  coverage 0.81 (needs 0.85); Pim was not rebuilt with SAM or through MCP.

### D-064: AI creates the art; our tools do the animation (owner, 2026-10-27)
- **Decision:** two halves, both the owner's:
  - **AI creates the art, and should do it faster:** characters, places and, later, key scenes
    ("from" and "to" frames) come from AI models driven by the director, with less manual
    steering and less waiting per asset.
  - **Controlled animation, not AI-generated video:** motion, in-betweens, timing, lip-sync and
    camera are done by our rigged-puppet tools (D-003, D-007). Hosted or local video-generation
    models (Higgsfield, Veo, Kling, Runway, Seedance and similar) are not part of the main
    pipeline.
- **Why:** the owner wants control over how things move and stay consistent, but wants the AI to
  take charge of creating the characters and scenes. Hosted video also breaks D-001 (fully local, no
  paid APIs) and costs about $15-100 a film in fees (web prices, October 2026, unverified).
- **Consequence for Step 12:** "Tier 3" stays as the owner's idea: AI-made key scenes, with the
  in-betweens done by our tools (pose and camera interpolation, optionally image interpolation),
  not by a video model. It is decided in its own brief, after Step 9 (character LoRAs keep key
  scenes on-model).
- **Consequence for the roadmap:** a speed-and-autonomy goal for asset creation is added to the
  steps that make the art (4, 4B) and to Step 5 (the director calls the art tools itself). Options
  already identified: lower Docker's memory reservation, two sheets a round, a cheap pre-check
  before a full sheet, cache rejected seeds, simpler layer fills, and a vision model to find faces.


### D-065: The director is a veteran animator (owner, 2026-10-27)
- **Decision:** the Step 5 director is built to act as a veteran animator who knows these tools
  deeply and can make any kind of animated video the tools can make. See ROADMAP Step 5 for the four
  parts: a craft library (RAG), a look-then-fix loop with `qa_mcp`, rules in code, and a capability
  list.
- **Why not just a persona prompt:** a "you are a veteran" prompt changes tone, not skill. A 14B local
  model gets skill from knowledge it can look up, feedback on what it made, and training on measured
  results (Steps 7 and 9).
- **Limit:** "any kind of video" means any kind the toolset supports: cut-out puppet films with
  AI-made art today, more styles as backends and tiers arrive (Steps 6 and 12). Out-of-range requests
  are declined with a reason, not faked.
- **Owner-led:** per AGENTS.md the agent loop core is the owner's to write; the agent proposes the
  design and a skeleton first.

### D-066: The cast pass bar measured; metric calibration and more redraw seeds (2026-10-27)
- **Measured** (Kit, Bo, Pim, Mia, Bolt rebuilt with the current code, SAM on): Kit, Bo and Pim
  pass (limbs on bones in both views, a face found in both, views consistent, turn at least 0.5).
  Mia (child) misses on turn 0.40 and one limb (`shin_r` drift 0.91); Bolt (robot, candidate c2)
  misses on limbs, no eyes in the front view, and a head 115% as tall. **3 of 5; the bar is 4.**
- **Two metric corrections** (they change reports, not the cut; Kit's part images are unchanged):
  - far-side shin coverage 0.85 -> 0.8 (`FAR_COVERAGE`): a short drawn sole scores 0.81 on Kit,
    Bo and Pim alike, with drift near zero.
  - a thigh beside a touching leg passes on coverage when the leg fit found the skeleton already on
    the legs (`touching_thigh_ok`): Bo's dungaree legs merge, so the thigh's cross-section reads as
    drifted by a radius.
- **More redraw seeds** (`turn.py`): when no seed of 1-3 turned the figure to 0.5, seeds 4-6 are
  tried one at a time until one does, and an older kept result short of the turn is extended the
  same way. It rescued Bolt c3 (seed 4, turn 0.77) but not Mia (best of six: 0.40).
- **Found:** Bolt c3 with that redraw crashed in the build (head cut 77 px wide, so the face
  anchors fell outside the head part). Bolt is built from c2 for now.
- **Open:** Mia's turn (a stronger turn instruction in the redraw prompt, or another candidate);
  Bolt (a robot has no organic eyes or limbs for the cut's rules); the head-size check (10%).

### D-067: The cast pass bar is met, 4 of 5 (2026-10-27)
- **Result** (all five rebuilt with the current code, SAM on): Kit, Bo, Pim and Mia pass (limbs on
  bones in both views, a face found in both, views consistent, turn at least 0.5; turns 1.08, 1.14,
  0.57, 0.78). Bolt (robot, candidate c2) misses: front limbs, no eyes in the front view, views
  inconsistent. This met D-060's bar.
- **What got Mia over it** (three focused sessions plus one prompt change):
  - A stronger three-quarter instruction in the klein redraw prompt (`turn.PROMPT`: body, hips and
    feet turned about 45 degrees, far shoulder and leg partly hidden, far eye and cheek smaller)
    lifted her best turn from 0.40 to 0.51. New redraws only; Kit, Bo and Pim keep theirs.
  - The turn measure (`consistency.face_offset`) now uses the face's big dark blobs (large eyes)
    when the head has any, else every mark, so a head of hair doesn't dilute it. Her turn reads
    0.78; Kit, Bo and Pim are unchanged. Capping the head width alone was not enough.
  - The cut (`build.py`): a forearm's spread zone no longer takes the coat's front edge beside the
    wrist, hair hanging past the neck stays with the head (`_hair_below_the_neck`), and a covered
    shin drawn beside its bone is slid onto the drawing (`recentre_shins`). Kit's parts are unchanged.
- **Open:** Mia's bent-knee pose still breaks up and her far arm is unchanged; Bolt; the head-size
  check (10%); dark seams between legs; nobody has looked at the final three-quarter pose images
  of the coat-arm fixes. The limits (7%, 0.8, 0.5) come from five characters.
- **Process note:** the three sessions each committed only their own files and left the shared logs
  to this session, which worked without conflicts.

### D-068: Step 4 closed, carry-overs go to Step 4B (owner, 2026-10-27)
- **Decision:** Step 4 is closed on its pass bar (D-067: 4 of 5; Kit, Bo, Pim, Mia pass) and Step 4B
  starts. Bolt (a robot) and the cut defects listed in D-067 are carried into
  `docs/steps/STEP-4B-animation-quality.md` (draft).
- **Why:** the bar was agreed in D-060 as the stopping rule; the remaining failures need a different
  approach (a locator for non-organic characters, bending limbs), not more rule-tuning on one cast.

### D-069: Step 4B started: the pose sweep, a placement track and walk, the bending-limb spike (2026-10-27)
- **Pose sweep (4B.1, `88083e8`):** `scripts/pose_sweep.py` and `studio_core/preview/sweep.py` render every
  motion's extreme poses on a magenta probe backdrop through the Synfig backend and count holes, seams
  and detached pieces. First run on the five-character cast: Pim 91 defects (75 detached, 11 holes,
  5 seams), Bolt 211 (59 holes, 119 seams, 33 detached), Mia 43 (36 seams, 7 detached), Kit 35 (33
  seams, 1 hole, 1 detached), Bo 14. About 40 s per character, 204 s for all five on the CPU. It exits 1
  on any defect. **Kit, the reference, has 35 defects**, mostly seams, so fixing them means changing
  Kit's built parts, which needs the owner's approval (4B checkpoint 3).
- **Placement track and walk (4B.6, `f3a0688`):** an additive placement path in the shot spec
  (keyframed positions with a fixed easing set), a `move_character` verb and `synfig_mcp` tool, the
  scene animates the placement group, and the walk cycle strides in time with the distance covered so
  planted feet don't slide (a render test measures the slide); facing follows travel. 502 tests passed.
  The front view keeps the march-in-place fallback. Walking in the three-quarter view for generated
  characters still needs side-view art.
- **Bending limbs spike (4B.4, `7c2ff98`, `docs/spikes/bending-limbs.md`):** three approaches rendered
  for an elbow and a knee bent 70 degrees: B two parts with a cap (today), A Synfig Skeleton Deformation
  on one limb image, C two parts with an overlap and an alpha ramp. A is the only one that really bends
  the limb; it has artifacts (a pinched notch on the inner elbow, a crease at the inner knee, a limb
  about 3-4% narrower at the bend, softer edges). Render cost is +0.03 to +0.04 s per limb per 1080p
  frame over an empty canvas (about +0.1 to 0.16 s for four limbs, extrapolated, not measured on a
  whole character), time barely depends on grid density (use 48x192). **Recommendation: A for arms and
  legs behind a per-limb switch, with the two-part cut as the fallback.** It means the cut must produce
  one limb image instead of two parts, which touches `puppet/build.py` and `schemas/rig.schema.json`.
  Not yet decided by the owner; hands (4B.5) wait for that decision.
- **Open:** whether to approve Kit's built parts changing (seams); the bending integration (4B.4
  follow-up); the locator trial (4B.3) was still running.

### D-070: Cut defects (4B.2), the locator trial (4B.3), and two approvals (owner, 2026-10-28)
- **Cut defects (`60fe24b`):** pose-sweep defects before to after: Pim 91 to 7, Mia 43 to 28, Bo 14 to
  11 (with fix 3 on); Kit not swept and byte-identical. Fixes: SAM's mask is accepted when it covers the
  colour key and adds the pale shirt the key lost (`sam_agrees`; Pim was rejected at IoU 0.79 though it
  covered 94% of the key); enclosed regions SAM also calls figure are filled (`fill_sam_holes`, Pim's
  torso hole); cut-off torso pieces of 100 px or more with 80% or more inside one limb's corridor go
  to that limb (`reclaim_limb_orphans`). **The third is opt-in** (`build_puppet(reclaim_orphans=True)`):
  with it on, Kit's three-quarter `shin_l` and torso change, so it stays off until the owner approves
  Kit's parts changing. Default builds change only 9 of Pim's images. Left: Mia's 24 shoulder and elbow
  seams (a bend problem for 4B.4), Mia's hair pieces in head_tilt, Bo's jump and wave seams and holes.
- **Locator trial (`17c0bf5`, `docs/spikes/vision-locator.md`):** qwen3-vl 8B finds where parts are
  (median about 0.1 head heights, no failed answers, about 29 s and 8 GB per image) and found Bolt's
  eyes and limbs where the pixel rules missed them, but 19% of joint points are over 0.15 head heights
  off and answers move up to 0.33 between runs: seeds, not pivots. It swaps left and right in 68 of 70
  pairs, so sides must be matched by geometry. Bolt's accuracy was judged by eye on one image.
- **Approved by the owner:** (1) integrate the locator as **seeds with the pixel rules as the check**
  (a pixel result within about 0.15 head heights of the seed is kept; otherwise the seed is used and
  flagged; a disagreement over 0.3 fails the build for a human look); (2) **Skeleton Deformation per
  limb** as the bending approach (D-069), with the two-part cut as fallback. Kit's parts: still the
  owner's separate decision.

### D-071: Locator seeds integrated (opt-in) and the Synfig side of bending limbs (2026-10-28)
- **Locator (`ec23780`, `puppet/locate.py`, `build_puppet(locator=True)`, default off):** answers are
  swapped left/right by geometry, cached in `characters/<id>/build/locator.json`, and used as seeds with
  the pixel rules as the check. With it on, no part image changed for any of the five characters; Bolt's
  eyes are found in the front view; Mia's eye that sat on her hair is corrected. About 17-19 s per build
  with cached answers and 160-185 s when the model is asked (4 calls). Guards added to keep the four
  passing characters from getting worse: a limb the rules measured is never overruled by a seed; a view
  whose limbs all pass is left as the unseeded fit made it; an off-figure seed fails a part only when
  the rules found nothing; a far eye in the three-quarter view keeps its inferred position and two eyes
  may not land on one mark; the nose seed never creates a nose. Bolt's three-quarter `shin_l` still
  fails (the seeds agree with the pixels). Not done: a hand-labelled error figure; exposure through the
  `comfy_mcp` `build_puppet` tool.
- **Bending limbs, Synfig side (`d8f8fc1`):** additive `views.<v>.bendable_limbs` in the rig schema (name,
  bones [upper, lower], one limb image, `size_px`, `pivot_px`, `joint_px`); `sif.SkeletonDeformation`
  (48x192 grid); `build_character(bend=)`, `build_shot` and `render_shot` take `bend=`; the two-part
  parts stay in the rig as the fallback. A character without limbs builds a byte-identical `.sif`.
  Four limbs on Pip at 1080p: +0.013 s for one frame, about +7 ms per frame in a 24-frame process
  (0.87 s to 1.036 s). The bent silhouette is 0.9998 of the two-part render's (Pip's arm is a plain
  capsule, so this does not test the pinch; nobody inspected the inner bend). 521 tests then passed.
- **What the cut must produce next:** per limb, one PNG drawn straight in the rest pose with no cap and
  the hidden joint region painted, plus the `bendable_limbs` entry; `joint_px` must match the lower
  bone's attach offset within 3 px.

### D-072: Bendable limbs in the cut (opt-in) and more acting (2026-10-28)
- **Bendable limbs in the cut (`5461e3c`, `build_puppet(bendable=True)`, default off):** per arm and leg,
  one limb image is the union of the two cut masks before the elbow or knee cap, with hidden stretches
  and any joint gap painted from the limb's own pixels (`paint_from`), cropped tight, saved as
  `parts/<view>/limb_<name>.png`, with a `bendable_limbs` entry in each view (`joint_px` from the
  rig's attach offset, so the 3 px rule holds). The two-part images stay as the fallback. Default builds
  hash-identically (29 files). On Kit, Bo and Pim a 70-degree elbow bends cleanly with no visible pinch;
  the inner knee shows a mild narrowing; Mia's elbow was hidden by her hair in the crop. Cost: nothing
  measurable at 800 px (0.43 vs 0.42 s per frame, dominated by Synfig start-up). **Bending does not
  remove the joint seams** (front view, `sam=False` rebuilds, pose sweep on vs off: Kit seams 15 vs 20,
  Bo 8 vs 7, Pim 4 vs 4, Mia 61 vs 57), so Mia's seams are mostly elsewhere. Mia's shin sits detached
  from her thigh in both renders. Looked at only in 256 px tiles: two-part stays the default until the
  owner has seen larger renders (they are part of the review reel, 4B.7). Not wired into the `comfy_mcp`
  `build_puppet` tool or `scripts/cast_review.py`.
- **More acting (`675555c`):** five expressions (excited, shy, sleepy, proud, determined; the original six
  render exactly as before, pinned by hash) and seven motions (shrug, bow, look_around, sneak, clap,
  laugh, think), each documented for what it does in the front view; `point` now anticipates and
  overshoots by 5 degrees. `wave` and `walk_cycle` are unchanged. Pose sweep on Kit and Bo: no detached
  parts; open items are the sneak hip pockets (Kit, 3 holes), `look_around` (Kit, 2 holes at the
  three-quarter neck), and a `think` pocket that may be a false positive (negative space between arm and
  head). `sleepy` needs half-closed eyes that an expression cannot set, and `laugh` has no mouth channel.
  Left unchanged: `nod` and `head_tilt` do not overshoot, `talk_gesture` beats have no hold.

### D-073: Ear and tail bones (opt-in) and the hand-pose spike (2026-10-28)
- **Ears and tails (`598242a`, `puppet/secondary.py`, `build_puppet(secondary=True)`, default off):**
  an optional `follow` block per bone in the rig schema (`lag_s`, `damping`, `gain`); `check_rig` checks
  ear and tail bones only where they exist (an ear's parent is the head, a tail's the torso or another
  tail segment, at most 3 segments). Ears are the head-mask lobes above the eye line; the tail is the
  torso piece outside the body hull attached by a narrow root; skirts, hems and scarf ends are refused
  and the build continues without those bones, saying why in the report. Found: Kit both ears and a
  3-segment tail in both views; Bo front ears only (his three-quarter ears and his tail are refused);
  Pim and Mia none. `motions/follow.py`: each ear or tail segment is a damped spring chasing its
  parent (ears lag 2-3 frames and overshoot about 16%, and splay on a nod; the tail sways with
  idle_breathe, lifts while travelling and trails a walk's bob); rigs without these bones are unchanged
  and Pip's tracks are identical on and off. Default builds of Kit, Bo, Pim, Mia are byte-identical.
  611 tests passed. **Open: with the secondary cut on, Kit gains 5 pose-sweep defects (64 off, 69 on;
  seam hairlines on wave and clap near the neck and shoulder) that persist with the new parts deleted,
  so they come from the changed head and torso cut, cause not pinned; the session did not mutation-check
  its tests; the tail's sway period, lift and bob gains are guesses; nothing renders ears or tail through
  Synfig in a real shot yet.**
- **Hand poses spike (`ca93b1f`, `docs/spikes/hand-poses.md`):** (A) procedural variants of the cut hand
  rejected: it only reshapes the same pixels. (B) a klein redraw gives very good, on-model hands on Kit
  (8 of 8; the redraw is about 1.5 times the cut paw's size with a tan cuff to refit) but costs 137 s per
  hand (about 18 min of GPU per character for four poses with two seeds) and failed to cut out Bo's and
  Mia's hands (arms against the body or a cream background). (C) hands drawn in code as vector shapes in
  the character's fill and outline colours: all five shapes read as the pose on all three characters, under
  10 ms, no GPU, no seed choice, but a generic cartoon glove, not Kit's ragged paw, and a hand-picked
  size per character that should come from the cut hand's width. **Recommendation: C**, first step an
  optional `hands` switch per forearm with only `rest` (the cut hand) and `fist`, proven in one Synfig
  shot, then point, open, wave. Stills only; nothing rendered in Synfig; one arm.

### D-074: Hands polished, ear and tail follow-up closed (2026-10-28)
- **Hands (`d18398f`, `a8c7901`; 36 new tests, mutation-checked, 655 passed then):** optional per-forearm
  `hands` block (poses, wrist, size, fill, optional outline, optional `cover_px`), drawn fist/point/open/wave
  as mitten-style vector shapes, a `hand` motion channel, `set_hand` in `synfig_mcp`, `add_hands(rig)`.
  `wave` uses wave, `point` point, `talk_gesture` alternates open and rest, `think` fist, `clap` open (a
  fist reads as punching). Polish: fill from the hand's interior, outline from its own darkest edge pixels
  (Kit's halo fixed), and a stored `cover_px` backing hides the cut hand under every pose (pixels showing
  at the wrist: fist 226/298/333/710 to 4/0/0/0 on Kit/Bo/Pim/Mia). About 70 mutants run, four weak tests
  fixed. **Open:** drawn hands are generic gloves, not on-model paws (Kit's ragged paw becomes a clean
  glove); Mia's shaded hand (`#cb7768` to `#fad8ba`) still differs from the flat fill; the backing makes
  fists boxy; hands are not tuned for the three-quarter view; the cut hand cannot be removed from the
  forearm image, so the drawn hand is drawn over it.
- **Ears and tails follow-up (`d5cf64f`):** Kit's +5 sweep defects were not the cut. `_clear_raise` in
  `motions/library.py` (it limits how high wave and clap raise an arm so the hand clears the head)
  measured the head from parts on the head bone only; with ears as their own bones the head looked narrower
  and the arms went higher, showing seams at the neck and shoulders. It now counts parts hanging off the
  head (fix carried by `d18398f`, with a test). Kit's sweep with the secondary cut: 63 against 64 for the
  default. About 46 mutations of the secondary code, tests strengthened; uncaught ones are listed in the
  report (ear size symmetry, short-lobe, midline-lobe, same-side and no-round-skull rules in `find_ears`,
  the tail's length check; two tests that need library edits). Tail gains raised after a Synfig look
  (sway amplitude 3-7 deg, walk lift 4-10 deg, bob trail 0.8-1.4 deg/px) and **not re-rendered by eye
  after the change**. The director needs no change: `describe_film` and `build_rig` already list the
  bones and the follow-through is automatic. Default builds of Kit and Bo hash the same as before.
  665 tests passed.
- **Not done:** no ear-and-tail test through a real `render_shot` call.

### D-075: Cut defects round 2: two opt-in fixes, Kit evidence shown (2026-10-29)
- **Two opt-in fixes (`526fc6a`; defaults unchanged, Kit's default build hashes identically; 667 tests passed,
  each new test fails without its fix):**
  - `reclaim_orphans=True`, wider: loose torso fragments lying inside a limb (feet, a foot sole beside the ankle,
    far-hand cuffs of 560-1900 px, slivers of 30-150 px) go to the limb: corridor 1.4 radii (was 1.2), minimum 30 px
    (was 100), end limbs get the 2.2-radius foot and hand spread.
  - `underlay=True` (new): `add_caps` also gives the torso the head pixels within 3% of the figure's height of the
    body, so hair that overhangs the shoulders leaves no thin gap when the head nods or turns (about 40% of Mia's
    seams were at the neck).
- **Pose-sweep defects, scratch rebuilds, before to after with both flags on:** Pim 229 to 72 (detached 139 to 3),
  Mia 98 to 36, Kit 64 to 46 (40 seams, 6 holes), Bo 26 to 16, Bolt 402 to 399. The session's baselines for Pim
  (229) and Bolt (402) differ from the orchestrator's fresh run (160, 59); the cause is not known (Bolt's scratch
  copy probably used another candidate's rig), so Bolt's sweep needs a separate look.
- **Kit with the flags on:** the front and three-quarter torso (larger), the three-quarter left shin (larger),
  the front right shin (31 px) and the front left thigh (42 px) change. Before/after sheet
  `renders/cast-review/kit-before-after.png` (rest, wave, sneak, both views): at that size the two rows look the
  same, so it shows no regression but does not show the improvement; the counts do. Every other character's parts
  change too with the flags on (Pim's by up to about 1300 px per part).
- **Open:** the defaults are still off pending the owner's OK; Mia's remaining shoulder and hand seams and holes;
  Bolt.

### D-076: The two cut fixes are on by default; Kit's parts change (owner, 2026-10-29)
- **Decision:** `build_puppet(reclaim_orphans=True, underlay=True)` are the defaults (`9db3da6`); the
  low-level `assign_parts` and `add_caps` keep their explicit False defaults. The owner approved Kit's built
  parts changing (conditions: sweep defects fall, render no worse); the before/after sheet showed no
  visible difference at tile size (D-075).
- **Verified:** 667 tests passed; the cast rebuilt with SAM on keeps the pass bar (Kit, Bo, Pim, Mia pass; Bolt
  misses on three-quarter limbs: 4 of 5).
- **Pose-sweep defects after the rebuild, all views and motions (holes / seams / detached):** Pim 6 (3/3/0),
  Bo 16 (3/10/3), Mia 27 (7/20/0), Bolt 23 (7/14/2), Kit 44 (5/39/0): **116 in total, from 393** on the
  previous rebuild (747 on the stale rigs). Pim fell from 160, Bolt from 59.
- **Open:** the 4B done-when asks for none; the remaining ones are mostly seams (Kit 39, Mia 20, Bolt 14,
  Bo 10); Bolt's three-quarter limbs; the hands' colour and boxy fists.

### D-077: The review reel (4B.7) and the owner's first look (2026-10-29)
- **Reel (`1494cb0`, `scripts/review_reel.py`, tests; output `renders/review-reel/`, git-ignored):** for each of the
  five characters a default video, a 4B-options video (bendable limbs, secondary ear/tail bones, drawn hands) and a
  default-vs-options comparison, front and three-quarter, every expression and motion, plus a labelled contact
  sheet per character and `index.md`. About 1,550 s of rendering per character (about 2 h 9 min in all).
- **Pose sweep, default vs options:** Kit 44 vs 49, Bo 16 vs 19, Pim 6 vs 73, Mia 27 vs 45, Bolt 23 vs 407. **The 4B
  options raise the defect count for every character** (most for Bolt and Pim), so they are not ready to become
  defaults; the cause is not investigated.
- **Owner's findings, by eye:** expressions look perfect (Kit, front); the three-quarter view does not look good;
  Mia's face is absurdly off; Bolt's side view is great but in the front view the side of his head is transparent.
- **Diagnoses (from the sheets and parts):** (1) the code-drawn face has front-view geometry on a turned head (two
  equal round eyes read like spectacles; the far eye is placed from the skeleton; no foreshortening); (2) Mia's drawn
  eyes are solid dark ovals without a sclera but the code-drawn eyes always have a white sclera, sized from her large
  drawn eyes (bug-eyed), and in three-quarter the eyes land over her hair, not on the visible skin (only one eye found
  by the pixel rules; the locator is off by default); (3) a light green patch on Kit's tail in three-quarter (probably
  scarf pixels in the tail part); (4) Bolt's white side panels around the head are transparent in the front head part:
  pale on a near-white background, enclosed by outlines but within the background-colour threshold of the gap rule
  (D-062); pure white is 5-8 from the background, like the thin gaps between legs, so colour alone cannot separate
  them, a shape test (fat region vs thin gap) is needed; (5) the reel's own flaws: the hand beats start with the
  character still at the right edge after the walk; the sheets are small because the walk moves her across the frame.
- **Mia's sheet (the reel session looked at the top half only):** huge wide-set round eyes in every expression, T-pose
  arms in `jump` with thin stretched sleeves, stringy forearms in `shrug` and `talk_gesture`, legs splayed in the
  walk with feet that look disconnected, and `sneak`, `nod`, `bow`, `look_around` nearly invisible at thumbnail size.

### D-078: Face fix and cut round 3 (2026-10-29)
- **Face (`4bda1f0`):** Mia's bug-eyed look was not a missing eye style: her eyes have a white sclera with a big brown
  iris. The eye mark merged with her lash and brow and measured 123 px tall on a 396 px head, so the cut sized the
  eye about 1.7 times too big; a merged-mark rule falls back to 0.14 of the head width (her front eye 90.8 to 57.8 px),
  and the brows are lighter, lower and no wider than the eye. Optional schema fields: `face.turn`, `eyes.style`
  (`sclera` default, `solid` built and tested, no character uses it), `eyes.width_px`, `eyes.highlight_px`,
  `eyes.highlight_r_px`, `eyes.color`, `brows.weight`, `colors.skin`. Three-quarter face: far eye and brow 0.75 to 0.55
  of the near ones by turn, pupils toward the facing side, mouth shorter and toward the snout (no nose layer exists);
  placement uses a pixel spill check, not the locator (it moved Mia's far eye about 7 px). Kit, Bo and Pim front face
  blocks are byte-identical (their three-quarter blocks gain only `turn`). 14 new tests, 6 fail with the old
  `face.py`. Still wrong: Mia's front mouth sits left of centre (her blush marks pull it), blush dots are not painted
  out, her far eye is close to the hair edge in three-quarter; the final before/after sheet was not looked at
  (`renders/face/face-before-after.png`).
- **Pale panels (`f176a3e`):** `fill_holes` treated every enclosed region within 10 of the background as a gap; Bolt's
  white panels (6-7 away, outlined) and most of his white limbs fell under that. A region 5-10 from the background
  that survives an erosion of about 1.1% of the figure's height now counts as figure; thin slivers and anything
  closer than 5 stay gaps (calibrated on the five sheets: Bolt's panels and limbs are 6.2-9.8 away and 3-5 px thick at
  quarter scale, real gaps 0-4.5 away). Bolt's front parts grew by 6% to 431%; Kit, Bo, Pim, Mia part images are
  byte-identical. Not fixed: Bolt's white shoes (about 2 away, same as real gaps), a small magenta rectangle at the
  chin of `head.png`, and white shapes with open outlines.
- **Kit's green patch (`be1ca95`):** not the tail: the three-quarter `forearm_l` carried about 3,200 scarf pixels
  because the elbow disc copies the sheet's pixels. The forearm elbow disc now excludes torso and head pixels
  (knees unchanged: it also changed Kit's front legs); only the three-quarter `forearm_l` changed (Kit, Bo, Mia, Bolt).
- **Correction to D-077:** the 4B options do not raise defects. The reel compared a SAM-built default with a
  no-SAM-built options variant. On a no-SAM baseline (Kit 46, Bo 16, Pim 72, Mia 36, Bolt 337) each option moves the
  count by about 10 or less (bendable: Kit -7, Bo +2, Pim +1, Mia +7; secondary: Kit -1; hands: Kit +1, Mia +8, Bolt
  -10). No option became a default.
- **After a full SAM rebuild of the cast:** pass bar still 4 of 5 (Bolt misses on three-quarter `shin_l`; turns Kit 1.08,
  Bo 1.14, Pim 0.57, Mia 0.78, Bolt 0.79); pose sweep 116 in total, identical to before these fixes (Kit 44, Mia 27,
  Bolt 23, Bo 16, Pim 6). The sweep compares poses against rest, so it cannot see parts that are transparent at rest
  (Bolt's panels): fidelity to the sheet needs a different check. 689 tests passed.

### D-079: Step 5 fast path: edit_mcp, qa_mcp and the director design (2026-10-29)
- **`edit_mcp` (`a725e9b`; workspace member `edit-mcp`, `.mcp.json`, `scripts/inspector_check.py`):**
  `create_film` (through `Film.create`, refuses an existing film), `describe_edit`, `assemble` (writes
  `edit/edit.json`, schema `schemas/edit.schema.json`, and the MLT project `edit/film.mlt`; title cards drawn with
  Pillow on a cream backdrop and encoded by ffmpeg; joins `cut` or `crossfade`) and `render_film` (melt, progress
  notes, then ffprobe and loudness checks; `preview` 640x360, `final` 1920x1080). melt was chosen because it worked
  first time (benchmarks: melt 8.8 s against ffmpeg 9.4 s for a 60 s encode); an ffmpeg xfade version was not timed.
  Real film from three existing shots plus a title card and an end card: 29.5 s with four 0.5 s crossfades,
  rendered in 7.4 s at 1080p, 29.504 s, -14.3 LUFS, video and audio present; no frame was viewed. **Only plain MLT is
  written; Kdenlive is not installed on this Mac, so opening the project in Kdenlive is untested and there is no
  `.kdenlive`.** Not done: fade in and out and other transitions, setting `stages.edit` in `film.json`.
- **`qa_mcp` (`63e2791`; workspace member `qa-mcp`):** `check_frame(film, shot_id, time_s)`: code checks first and
  always (a black frame; per character, rendered alone on a magenta backdrop: missing, cropped, holes, seams,
  detached pieces), then one `qwen3-vl:8b-instruct` call (temperature 0, think off, JSON schema) returning
  `matches`, `problems` and a description; `ok` needs both layers clean; the model is unloaded afterwards and the call is
  refused while ComfyUI is busy. `check_safety(text?, film?, shot_id?, time_s?)`: the word blocklist, then a model
  judgement against a seven-category rubric for ages 3-8; any doubt gives `ok: false, needs_human: true`.
  `check_film(film)`: up to 3 key frames per shot (from the action times, blink and idle_breathe ignored) plus every
  dialogue line and the premise, sequentially with one model. Measured: `check_frame` 24-28 s in all (the model call
  20 s cold and 9.4 s warm, more than the 5-7 s in benchmarks.md), a safety call 3.6-6.7 s, 5.2 GB, gone after.
  Trial on a copy of `step3-demo`: 3 good frames ok; a deliberately broken frame (a character moved off-frame) was
  caught by the code check, the model missed it (it said the character was present and skipped the other one), which
  is why the code checks are the facts and the model only advises; 5 of 5 sentences judged right (3 fine, a mild fox
  hit refused as violence, a ghost in a dark cellar as fear). A false alarm from the sweep rules on a thin slot between
  Pip's legs was fixed by ignoring holes more than 6 times longer than wide and raising the seam minimum to 40 px
  (a heuristic that could miss a real thin gap). Not done: `check_film` against the real model (fake-model test only),
  lip-sync and temporal checks, a prompt revision for the model's confusion cases; the premise check needs a `premise`
  key in `film.json`. `Ollama.generate` gained an optional `format` argument.
- **Director design (`6bb4f01`, `aa97544`, `docs/steps/STEP-5-director-design.md`, 357 lines, docs only):** stage state
  machine with `films/<slug>/director/state.json`, the Ollama tool-calling loop, planning schemas, memory between
  stages, the `director/` skeleton marking the loop core (`loop.py`, `dispatch.py`, `runner.py`) apart from plumbing,
  a minimal craft library, and the milestone 2 plan with a fixed test story. Open owner questions: who writes the
  loop core; story length (15 s then 60 s, or 60 s straight); approval granularity (four stops or fewer);
  code-driven art stages as the fast path (narrows the brief's "director drives all servers"); and the small
  differences from the brief (a `director/` folder, `qa` as a seventh stage, `read_craft` by name first, a separate
  shot-plan schema).


## D-080: Director loop built; art, audio, edit and QA stages are code-driven (2026-10-30)

The `director/` package and `scripts/direct.py` (new, resume, approve, revise, retry, status) run a story prompt
through seven stages with four approval stops. The owner approved the design with: a session writes the loop core
(kept small and commented, with a learning note in `docs/learning/agent-loop.md`), 15 s story first, four stops,
code-driven art stages. Choices made while building:
- The first passing candidate is chosen in code (a text-only 14B has no signal beyond the check flags). A vision
  pick with qwen3-vl is a later option.
- A shot is built in two phases: code scaffolds it (blink and idle for everyone), then a tool-calling conversation
  looks and fixes. `render_shot` is refused until `check_frame` has run.
- Planning calls are schema-forced with required fields (the 14B drops optional ones; "none" is an empty value).
- The audio stage stops an idle ComfyUI before `compose`, and refuses if it is busy.
- Edit and QA are code-driven; QA reports open issues at the final approval and does not auto-fix.
- Stage timeouts include tool time (deviates from the design, which excluded it).
- Craft retrieval is by name only for now.
Stop conditions are decided by code (`done`, `unfinished`, `stuck`, `limit`), never by the model.
Open: the 14B's shot and expression taste is weak (see PROGRESS).

## D-081: A desktop GUI is a planned step; it is a thin client over the director's state (2026-10-30)

The owner wants a desktop app to keep projects and stories, interact with the director and see saved files
(ROADMAP Step 13). Decision: the GUI sits on top of the existing state folders and director commands, so the CLI
and GUI stay equivalent; proposed stack is a local FastAPI backend, a Svelte UI and Tauri packaging (the owner
knows Svelte/React/TypeScript). Why not a GUI-only state: it would break resume, scripting and tests. The stack
is a proposal and may change at the step's brief.

## D-082: Projects own characters and backgrounds; films reference them (2026-10-30)

The five test characters are for testing only. The unit of reuse becomes the **project**: it owns the characters
and backgrounds (built once, versioned, immutable once a film uses them); each film in the project references them
by `{id, version}` instead of copying them (replaces the `--import-cast` copying). Why: the owner wants many films
per project with a stable cast and shared places; copies drift and waste disk. The GUI (D-081) shows projects as
the top level. Layout and migration are specified in ROADMAP Step 5B.

## D-083: Acts are the unit of directing and rendering; specs are the editable source, renders are cache (2026-10-30)

A film is a list of acts; each act has its own background, cast and several camera angles (shots). The director
directs and renders per act; "export all acts" stitches the act renders into the movie. All specs (`acts.json`,
`shot.json`, cues, edit list) stay editable until export; media is derived, keyed by a content hash (specs plus
character, background and engine versions) so an edit re-renders only its act. Why: long films need partial
re-renders, per-act approval and later edits in the GUI; baking early would make every change a full redo. See
ROADMAP Step 5C.

## D-084: Store project data behind an interface so an online database can be added later (2026-10-30)

No online database now; the product stays local and offline by default. All project data goes through a
`ProjectStore` (filesystem now, in-memory for tests, database plus object storage later), as id-and-version
referenced JSON documents with `schema_version`, `owner_id`, `project_id`, `rev` and timestamps, and
content-addressed assets; specs hold no paths. The project is the tenancy boundary. Why: the owner wants user
logins and saved data online later; retrofitting that into path-based folders would mean rewriting every tool.
Contract tests keep every store equivalent. See ROADMAP "Storage rule" and Step 14.

## D-085: The desktop app installs on Apple Silicon Macs first; heavy parts are installed by a setup screen (2026-10-30)

Target is a `.dmg` with a `.app` for macOS arm64 only (Windows and Intel later). The app bundles the UI and the
Python backend (own `uv` environment); models and large engines are not inside the installer but are installed
and checked by a first-run Setup screen (licence and size shown, resumable, with repair). Why: models are tens of
GB and the engines are separate GPL and BSD apps; keeping them out keeps the installer small, the licences clean
and the fully-local rule intact after setup. Signing and notarization are decided when sharing beyond the owner.

## D-086: Real motion comes from CMU mocap retargeted in code; `*_real` motions are opt-in for now (2026-10-30)

Clips come from the CMU Graphics Lab Motion Capture Database ("free for all uses"), projected to 2D and retargeted
to each puppet's bones with foot-lock, stored as small engine-neutral JSON clips (raw data stays outside the repo).
`Clip.limits` lets a clip declare a wider joint range than the rig default; `params.principles` (0 to 1) is an
opt-in layer for anticipation, overshoot, settle, head lead and landing dips on any motion. Result was a modest
gain: with rigid two-piece limbs the walk, run and jump add cut defects (Kit 26% to 44% of swept frames), so the
`*_real` motions stay opt-in and are not offered to the director until the render engine bends limbs (see D-087).

## D-087: Engine choice is decided by a bake-off; Blender and OpenToonz lead, Synfig is the reference (2026-10-30)

The owner is not impressed with Synfig's results and prefers Blender plus OpenToonz. Before building more, a
bake-off renders the same benchmark (Kit walk, wave, jump; a Mia close-up) in each, with an automation gate
(code builds, animates and renders headless on the Mac, deterministically) before the look is judged. Source
changes to the apps are allowed only as a last resort and recorded (AGENTS.md levels 1 to 3). Strictly 2D
(orthographic camera) unless the owner approves 2.5D. The replacement of Synfig is recorded as a decision only
after the bake-off, and Synfig stays available as a fallback until the new engine renders the cast at least as
cleanly. Reverse-engineering tools are not needed: both apps are open source.

## D-088: The shot plan carries emotion, framing, addressee and target; taste is checked in code (2026-10-30)

Shot plans have required `emotion`, `framing`, `line.to` and `target` fields. The emotion-to-expression table is data
(`director/src/director/emotions.json`, kept in sync with the face rig by a test); 16 taste rules in code (staging,
emotion arc, faces, camera intent, pointing) give the model one feedback round and are advice, never fatal. The opening
wide shot may carry the scene's first line when the recorded lines leave no time, and the brief states the time the
lines need. Measured: violations 52 to 8 on five fixed stories. The shot-plan format will be adapted to acts (D-083).

## D-089: Project data layer: ULID ids with a slug, append-only versions, act cache key (2026-10-30)

Ids are ULID-style with a `slug` handle; a project id may be caller-chosen because it is the folder name. A character
or background version is an append-only manifest of relative file name to asset record (content-addressed); old
versions cannot be edited. The act cache key hashes the act (its background and cast versions), its shots in order, an
engine id and the film style, with a `KEY_VERSION`. Migration into the store clones, then hard-links, then copies, and
never touches the old film folders. Adoption by the MCP servers and director follows (STEP-5B brief).

## D-090: Engine bake-off result: engines tie on defects; Blender leads on speed and automation (2026-10-30)

Both Blender and OpenToonz clear the automation gate with no plugins or source changes; Blender is native arm64, 4 to
40 times faster per frame and scriptable in its own Python; OpenToonz runs under Rosetta, single thread. Cut defects on
Kit's benchmark shot are about the same across Synfig, Blender and OpenToonz (43 to 63 of 120 frames), so the engine
is not what removes holes at bent joints: the cut is. The owner decides the look by eye; until then the recommendation
(Blender for puppets, OpenToonz later for hand-drawn hero shots) is not a decision. Next lever: complete the hidden
overlap at joints in the cut (a joint-completion spike), which is engine-independent.

## D-091: Project films are a derived working folder; acts render and export per act (2026-10-30)

Servers open a film through `Workspace.open_film(film, project)`; with a project, the folder is derived data under
`[paths] work` (safe to delete), rebuilt from the store at pinned versions, so existing shot, audio and art code runs
unchanged. Voices live in the film's audio document (casting a voice does not publish a new character version). The act
cache key excludes `order`, `title` and `beats` (reordering or retitling re-renders nothing; key version 2) and includes
the render target `engine:quality` (e.g. `synfig:final`). The edit schema has a clip kind `act`, so a whole act is one
clip of the movie. A changed recording makes only its act stale. Old film folders and old tool arguments keep working.

## D-092: Joint overlap in the cut is opt-in; hidden-pixel gaps are not the main remaining defect (2026-10-30)

`build_puppet(overlap=True)` grows a part under its front neighbour near joints. It reduced Kit's full-sweep defects
(124 to 78 in a first version) but made Mia worse and did not reach the target of under 10 of 120 on the benchmark
shot. Most remaining defects come from legs crossing, a hand beside a thigh, loose torso strips and the tail over a
leg, which overlap cannot fix. It stays off by default. The next lever to test is a single continuous skinned mesh of
the whole figure (bone weights taken from the part masks) instead of separate rigid parts, which removes seams by
construction; generative inpainting of hidden areas is only needed where limbs cross.

## D-093: One continuous skinned mesh per character is dropped (2026-10-30)

Spike `docs/spikes/skinned-mesh.md`: a single triangulated mesh of the whole figure (parts composited, vertex weights from
the part masks, smooth blend near joints) in Blender, same bake and defect counter as the cut. Defect frames fell (Kit
48 to 15 of 120, Mia 42 to 32 of 72, same 0.023 s per frame), but only because stretched triangles fill the gaps: on the
wave, jump and gesture motions the limb and torso texture smear and fold, which the counter cannot see. The cut's seams
are still the lesser evil. Not adopted; the code stays in `engines/blender/skin.py` as a measuring tool. Next levers:
separate part meshes with a fill of the hidden area under front parts, and a draw-order switch for crossing legs.

## D-094: The director works on a project: scenes are acts, approvals are per act, its memory lives in the project (2026-10-30)

`director new --project <id> --film <slug> [--pin-cast a,b] [--pin-places x] [--acts N]` makes a film of a project. The
story stage sees the project's library (not a flat film), is told to reuse it, and may be limited to pinned ids (an enum in
the schema plus a check). A scene of the story is an act (it gets a title); the characters and places stage first puts the
library items the story uses into the film (`Project.add_film_reference`) and only the missing ones go through the art
tools, which publish them to the library. The shots stage plans one act at a time (taste rules see the film so far, D-088),
builds its shots as camera angles of the act (same scaffold and conversation as before), writes the act's beats and calls
`render_act`; the edit stage is `export_movie`, so a changed act is the only one that renders again. New stops:
`act_<scene>` after each act (also `revise act_<scene> "note"`: that act alone is planned and built again). The agent loop
core, stop conditions and approval semantics are untouched. The director's own files (state, story, plans, line list) are
in `projects/<project>/director/<film>/`, linked into the derived working folder, so they survive its deletion; they are
the director's private progress, not product data, and are not behind `ProjectStore` yet (the project's cast, places, acts,
shots, recordings and renders are). Old film folders and `--import-cast` still work.


## D-095: Characters are built rig-first in a flat style, with a computed face and a smoothing layer (2026-10-30)

(The brief called this D-093; that number and D-094 were already taken, so it is D-095.) Spike
`docs/spikes/rigged-character-test.md`. The owner's review blamed the characters, not the engines, so Mia was rebuilt:
parts drawn by code as complete shapes in a flat palette (`puppet/flat.py`), the face computed from the head box with hard
limits (`face_layout.py`; the old painted-head face had its eyes at 78% of the skin width and the mouth 49 px off centre),
drawn per frame from continuous numbers (`engines/face_flat.py`), a head turn done as a limited slide, and a deterministic
smoothing layer (`motions/smooth.py`, `Clip.max_speed_dps`): jerk 5.0 to 0.9, one-frame jumps 71 to 20, no switch pops in
blinks, mouth shapes or expressions. Defect frames on the bake-off close-up fell from 44 to 3 of 72, with the caveat that this
shot bends little and the counter does not see looks. A FLUX.2 klein edit to a flat A-pose was tried and rejected for limbs
(arms touch the body, no guarantee of hidden parts, colours drift). Engine-neutral (D-030): the face layout and
smoothing live in `studio_core`, only the transparent render and keyed camera touch the Blender harness. Everything is opt-in
(`face.layout`, shot `smooth`, `camera.move: track`), so older films render as before. Not adopted yet for other characters or
backgrounds: the owner decides whether the flat vector look is the film's look. Mia is still not production ready (front view
only, simple art, a sideways walk); see the spike's recommendation.

## D-096: A shot change never dissolves two framings of the same character; neck, hair, legs and hands get shape rules (2026-10-30)

The independent review of the first Mia clip (NEEDS WORK) found a double-exposure dissolve, a flat neck block, clipped and
stair-stepped hair and a stiff, short-legged walk. Decisions: (1) `motions/smooth.transition_for` returns "cut" when both scenes
contain the character and their scales differ more than 1.25x; the clip uses one real camera push-in instead. (2) The neck is a
torso part tucked under a collar band, the head image ends at the chin. (3) Hair pieces are one unioned and smoothed shape with
room for the curls. (4) Visible legs are at least 27% of the figure's height and boots at most 10% (`leg_ratios`), the hand starts
under the cuff, and `walk_step` (opt-in) adds foot lift, knee bend, bob and sway to the stride walk. Each rule has a test in
`tests/test_flat_round2.py`. See `docs/spikes/rigged-character-test.md`, "Round 2". Not decided: whether the flat vector look is
the film's look (still the owner's call), and the side/three-quarter part sets.

## D-097: A head turn moves the whole head; the face moves more than the outline (2026-10-30)

The owner saw the face slide like a sticker on a fixed head: yaw only shifted the features inside the head image. Now a turn is a
horizontal map about the head's vertical axis applied to the head composite and to the hair back and side locks
(`face_layout.head_warp`, `engines/face_flat.warp_image`): the head's centre shifts 8% of its width at yaw 1, the side turned
toward narrows 4% and the far side 22%, the hair follows a lagged yaw (0.12 s), and the features keep their extra slide (the nose
most). Rules held by tests over yaw -1..1: features inside the skin, the head moves at least 40% of the face's shift, the chin
stays over the neck. The Blender harness swaps per-frame part images (`part_images`); the contract is engine-neutral (baked
numbers, PNGs per frame). Independent review of a 3 s turn test: PASS with minors. Limit: beyond about yaw 0.6 the cheat shows;
a turned part set is the real answer. Not changed: walk, framing, hair shape (round 3 not started).

## D-098: Shot-level rules in code: framing and foot contact; the flat Mia gets longer legs and a round head (2026-10-31)

The independent review of `clip_v2` named three majors. Two of them were measurable, so they became rules on the bake, not on the
pictures: `framing.check_framing` (head, feet and sides stay inside every frame under that frame's camera, with margins) and
`motions/gait.foot_report` (the lower sole touches the ground, the planted foot does not drift). Writing them found three real bugs
the pictures hid (boot art with empty rows so Mia hovered 10 px, a torso lean that slid the planted feet, a walk that ended
mid-swing). Mia: legs 140+160 px and thicker, wider arm swing; the head is an egg with an arched parted fringe and locks along the
face contour. The walk stays lateral with the front-view puppet (no side-view set exists; building one is the next real step).
The push-in ends as a full-body shot, because the rule forbids cropping head or feet. Independent review of the full clip: NEEDS
WORK (the wave arm and the straight tube legs); framing fixed, walk and hair partly. Not production ready; remaining list in the spike note.

## D-099: Flat parts on planes are dropped as the character foundation (2026-10-31)

After watching `compare.mp4` (A flat parts on planes, B Grease Pencil, C toon 3D) the owner said A is the worst of the three, and had
already called the round-3 clip "very very bad". The flat-part rig (front view only, squash-slide turns) is no longer developed;
`framing.py`, `motions/gait.py` and the parametric face rules stay as reusable, engine-neutral rules. The pick between B (2D, a
drawing per view) and C (3D with cel shading, needs 2.5D approval) is still open. See `docs/spikes/blender-foundations.md`.

## D-100: Replace Mia with a ready-made CC0 cast for the Blender and OpenToonz tests (2026-10-31)
The owner rejected Mia ("I hate mia") after the round-3 review. Four rounds of home-made art did not reach the bar, so test the engines on professionally drawn, consistent art with separate limbs: Kenney "Toon Characters 1" (CC0, recorded in `docs/MODELS.md`), using the Female person and the Robot. Why: the bake-off showed art, not the engine, is the limit (D-090, D-095); a clean flat cast with hidden-limb art, back views and expression heads removes that variable. Costs: game-style proportions (short, chibi), one fixed mouth, small raster parts (use the SVG). Mia code (`face_layout`, `framing`, `gait`, smoothing) stays as engine-neutral rules. This does not approve 3D.

Update (2026-10-31, spike `docs/spikes/new-character-engines.md`): rebuilt Kenney "Female person" from the SVG and ran one 6 s shot
through Blender and OpenToonz; both clips FAILED the independent review for fixable reasons (leg gap, face choice, fist wave, walk),
and the art is a real step up from Mia. The engines tie; keep both adapters. Two adapter bugs fixed (Blender unscaled rest armature,
OpenToonz scale/camera/swaps/transparency).

## D-101: Reset to one vertical slice; freeze engine and cast (2026-10-31)
The owner asked why the project was not heading in one direction. Every picture shown had failed while work spread into breadth (projects, acts, storage, three engine adapters), the art-source and engine questions drifted for days, and sessions self-scoped and self-passed. Decision (owner accepted): Blender is the one engine (native arm64, Python API, fastest in D-090; OpenToonz parked for the hero tier, D-031 kept long-term; Synfig legacy). The cast is frozen on the Kenney Female person and Robot (D-100). The only active work is a 30 s vertical slice with an owner-picked reference clip and a written done-when (ROADMAP "Reset"); everything else is paused until it passes. Then the eval harness, the director loop, and a character LoRA, each as its own approved brief. Process: one session at a time, no self-directed pivots, one decision at a time with a recommendation.

## D-102: Allow stylised 3D characters; cast Rain and Snow (2026-10-31)
The owner gave two reference clips: a lush, softly lit painted 2D scene and a stylised 3D feature teaser. Both are painterly and cinematic, which flat cut-out art (Kenney, Mia) does not reach, and cut-out puppets never walked or acted well from code. The owner chose to allow 3D characters. Decision: characters are stylised 3D rigs rendered with soft, painterly lighting in Blender; backgrounds stay painted plates in depth (no photoreal 3D). This retires the "2D only, cut-out puppets" rule in AGENTS.md and replaces the Kenney cast of D-100/D-101 with Blender Studio's free rigs Rain and Snow (CC-BY 4.0, for Blender 4.1+, no add-ons; credit lines required). The cut-out pipeline (Synfig, OpenToonz cut-out, `puppet/`) becomes legacy; the framing, smoothing and review rules carry over. Deviation from D-030: the slice may be built with Blender-specific scripts; how the engine-neutral scene model covers 3D is decided after the slice. ARCHITECTURE.md still describes the 2D cut-out design and is updated after the slice. Brief: `docs/steps/STEP-SLICE.md`.

**D-102 amendment (2026-10-31, same day):** the owner said the end goal is 2D or 2.5D-style animation. So 3D rigs are a production means only: they are rendered to look drawn (flat or soft cel shading, Line Art outlines, painted textures, optionally on twos), never CG-looking. The slice's look test renders a flat 2D look and a painterly 2.5D look side by side for the owner to choose. Hand-drawn 2D (Grease Pencil, OpenToonz) stays the long-term hero tier.

## D-103: One agent-neutral skill source (2026-10-31)
The owner requires a single source of truth for skills and instructions, independent of coding-agent brand. The canonical
procedures live under `skills/<name>/` and rubrics under `docs/craft/`; no agent-specific skill Markdown or adapter copies
are maintained. Every agent reads the same repo-native files directly.

## D-104: Do not animate the Rain slice until the drawn-look gate passes (2026-10-31)
The owner delegated the 2D/2.5D choice to the orchestrator, who selected painterly 2.5D as the direction to pursue.
Independent reviews of the original stills, a localized character-texture pass, and an EEVEE cel-shading/Freestyle proof
all returned NEEDS WORK: the 3D character still reads apart from the painted forest. The final toon proof has a readable
face, but a single still says nothing about motion. No treatment is adopted, and animation is paused until the visual
mismatch has a viable solution. Recommended next decision: allow a unified illustrative treatment across the painted plate
and character; if that still fails, reopen the character-art constraint. See `docs/spikes/rain-toon-look.md`.
