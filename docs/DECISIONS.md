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
- **Owner:** Step 5 is owner-led (CLAUDE.md); this is input, not the final choice.

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
