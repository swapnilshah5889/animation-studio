# Architecture

## Goal

One prompt in, one finished children's animated film out, made **entirely on the owner's machines**,
with no paid APIs.

- The **LLM is the director**: it writes the story, plans shots, picks motions, and checks results.
- **Open-source apps do the animating.** Synfig tweens rigged characters, Kdenlive assembles the edit,
  and so on. The LLM never generates every frame. That would be slow, expensive and inconsistent.
- **AI generates assets once** (characters, backgrounds, voices, music), and the rig and tools reuse
  them forever. This is how real studios keep characters on-model.

## Pipeline (version 1: children's cut-out animation)

```
prompt
  └─> director (local LLM)
        ├─ story ......... premise → script → shot list (validated JSON)
        ├─ characters .... design → puppet sheet → parts → rig      [comfy MCP + synfig MCP]
        ├─ backgrounds ... painting → depth layers → parallax set   [comfy MCP]
        ├─ audio ......... voices → lip-sync cues → music → sfx      [audio MCP]
        ├─ shots ......... build Synfig scene per shot → preview → QA → render   [synfig + qa MCP]
        └─ edit .......... assemble shots + audio → Kdenlive project → final MP4  [edit MCP]
```

Each stage writes files into the **film project folder** (below), which is the single source of truth.
Every stage can be resumed, inspected, or fixed by hand in the real app, then picked up again.

## Key design decisions (details in DECISIONS.md)

1. **Consistency comes from the rig.** Each character is generated **once** as a puppet (neutral pose,
   limbs apart), cut into parts, and rigged with bones. No LoRA is needed in v1.
2. **Procedural faces.** Eyes, eyebrows and mouths are **vector shapes generated in code** inside
   Synfig, not AI images. That gives exact lip-sync from Rhubarb cues, blinks, and expressions at zero
   AI cost, and it suits the simple children's style.
3. **A motion library.** Reusable, parameterized bone animations (walk, wave, jump, nod, talk gestures,
   idle breathing, and so on). The director picks motions by name and timing, and Synfig fills in the
   frames between poses.
4. **Palette lock.** Every generated asset is snapped to the character's or background's official palette
   (deterministic color quantization). This removes AI color drift.
5. **Vectorize flat art.** Character parts are converted from raster to vector (vtracer) where it
   looks good, so the art stays crisp at any resolution.
6. **Rules in code, judgment in the LLM.** Timing, frame math and layout are deterministic, tested code.
7. **Engine-neutral scene model (D-030).** Our schemas are the source of truth, and animation engines
   are swappable backends (below).

## Engine-neutral scene model and backends (D-030, D-031, D-032)

```
Director (LLM) → our schemas: film / shotlist / shot / rig + motion channels   ← the product's core
                      ├─ Synfig backend     → .sif  → synfig CLI     (first film, Steps 2–5)
                      ├─ OpenToonz backend  → .tnz  → tcomposer      (strategic engine, Step 6)
                      └─ web preview        → PixiJS in the browser  (only if the product is hosted)
```

- **No engine-specific fields** in the schemas, `film.json`, or the director's tool vocabulary. Engine
  details live in `studio_core/engines/<engine>/`.
- **Synfig ships the first film.** It is already working and becomes the conformance reference.
- **OpenToonz is the strategic engine:** BSD-3 license, one engine for children's cut-out *and* anime
  tiers (Plastic mesh deformation, a real multiplane camera, compositing effects), a built-in render
  farm, and professional interoperability. Evidence: `docs/spikes/opentoonz.md`.
- **Final rendering is server-side:** stateless Linux render containers on CPU nodes (OpenToonz
  `tcomposer` under Xvfb, the Synfig CLI, MLT/ffmpeg). GPUs are only for AI asset generation. The
  same containers run on the owner's machines for development and self-hosting.
- **Open owner decision:** hosted web app vs desktop app vs both. D-001 (fully local) stands until then.

## MCP servers

Each server wraps one open-source app and exposes a small set of tools. The tool names below are a
starting point: refine them while building, and record changes in DECISIONS.md.

| Server | Wraps | Example tools | Integration level |
|---|---|---|---|
| `synfig_mcp` (may become `animation_mcp` once there are two backends, D-030) | **Synfig Studio** now, **OpenToonz** from Step 6 | `create_scene`, `build_rig`, `pose_at`, `apply_motion`, `apply_lipsync`, `add_parallax_background`, `camera_move`, `render_preview_frame`, `render_shot`. Names and arguments stay engine-neutral. | Synfig: generate `.sif`, render with the `synfig` CLI. OpenToonz: generate `.tnz`, render with `tcomposer`. |
| `comfy_mcp` | **ComfyUI** (image generation, SAM 2, depth) | `describe_art`, `design_character`, `choose_design`, `build_puppet`, `preview_puppet`, `generate_background`, `choose_background`, `split_depth_layers`, `preview_background` (D-056) | ComfyUI HTTP API, with graphs built in code from `config/models.toml` (`studio_core/comfy_graphs.py`) |
| `audio_mcp` | **Kokoro / Chatterbox** (TTS), **Rhubarb** (lip-sync), **ACE-Step** (music), CC0 sound library | `speak`, `lipsync`, `compose`, `find_sfx`, `mix` | Python and CLI. Sound effect search uses audio embeddings (CLAP) in Qdrant. |
| `edit_mcp` | **Kdenlive / MLT** | `assemble`, `add_titles`, `export` | Generate MLT XML and render with `melt`. The owner can open the project in Kdenlive. |
| `qa_mcp` | Local vision model (Ollama) | `check_frame`, `kid_safety_check` | Ollama API |
| `krita_mcp` (optional, later) | **Krita** + AI Diffusion plugin | `cleanup_part`, `lock_palette`, `export_layers` | Level 2: a Krita Python plugin opens a local socket |

**Integration levels:** (1) wrap file formats, CLIs and APIs (the default). (2) In-app plugins so the
LLM can act on what's open in the GUI. (3) Modify app source, only as a last resort.

**License note:** Synfig, Krita, Kdenlive and ComfyUI are GPL. Wrapping them via files, CLIs and APIs
keeps our code separate. If we ever distribute *modified* versions of them, GPL requires publishing
those changes. OpenToonz's own code is **BSD-3-Clause** (its bundled third-party libraries keep their
own licenses), so we can modify it and ship our own builds freely (D-031).

## Film project folder (source of truth)

```
films/<film-slug>/
  film.json                 # premise, characters, settings, and the status of each stage
  story/
    script.md
    shotlist.json           # validated against schemas/shotlist.schema.json
  characters/<char-id>/
    design.png              # approved concept
    sheet/                  # puppet sheet, views (front, three-quarter), mouth chart reference
    parts/                  # cut parts (PNG and/or SVG)
    rig.json                # bones, pivots, part hierarchy, available views
    palette.json
    voice.json              # TTS voice and settings
  backgrounds/<bg-id>/
    painting.png
    depth.png
    layers/                 # foreground / midground / background PNGs
    layers.json             # depth order and parallax factors
  audio/
    dialogue/<line-id>.wav
    lipsync/<line-id>.json  # Rhubarb mouth cues
    music/<cue-id>.wav
    sfx/
    mix.wav
  shots/<shot-id>/
    scene.sif
    preview.png
    qa.json
    frames/                 # rendered PNG sequence (deleted after encode, if wanted)
    shot.mp4
  edit/
    film.kdenlive           # MLT project
    final.mp4
```

`films/` is git-ignored. Small test fixtures live in `tests/fixtures/`.

## Shot spec (illustrative, to be formalized as a JSON Schema in Step 2)

```json
{
  "id": "s01_sh03",
  "duration_s": 4.5,
  "background": "meadow",
  "camera": { "move": "slow_pan_right", "zoom": 1.0 },
  "characters": [
    {
      "id": "pip",
      "view": "three_quarter",
      "position": [0.35, 0.8],
      "actions": [
        { "motion": "wave", "start_s": 0.5, "params": { "hand": "right", "energy": 0.7 } },
        { "motion": "idle_breathe", "start_s": 0.0 }
      ],
      "expressions": [ { "expr": "happy", "start_s": 0.0 } ]
    }
  ],
  "dialogue": [ { "character": "pip", "line_id": "l007", "text": "Hi, Bunny!", "start_s": 0.8 } ],
  "sfx": [ { "query": "soft birdsong", "start_s": 0.0, "volume": 0.3 } ],
  "music_cue": "m01"
}
```

## Orchestration

- **Steps 1–4:** each MCP server is developed and tested on its own, using the MCP Inspector or
  a coding agent as the client.
- **Step 5:** the **director agent**, a hand-written agent loop in Python against Ollama. It runs a
  stage state machine over the film folder, with approval checkpoints (story, character designs,
  first shot) and resume from the last completed stage.
- **Step 5+:** introduce **Temporal** once the Windows laptop joins. **Task queues by capability**:
  `ai-mac` (LLM, image generation, vision QA, music) and `render-win` (Synfig rendering, TTS, Rhubarb,
  encoding). MCP servers on the Windows machine use MCP's HTTP transport over the LAN. Shared assets
  go through MinIO (S3-compatible), so moving to the cloud later is a configuration change.

## Machines

| Mac (M4, 24 GB): "AI brain" | Windows (4 GB RTX, 8-core, 32 GB): "render and services node", from Step 5 |
|---|---|
| Director LLM, image generation (SDXL), vision QA, music | Synfig rendering (CPU), Docker services (Qdrant, Temporal, MinIO), TTS, Rhubarb, NVENC encodes |

Mac memory rule: one large model loaded at a time. The pipeline must unload explicitly between stages.

These are **development and self-hosting machines**. In the product, final rendering runs in stateless
Linux render containers on CPU nodes, with GPUs only for AI asset generation (D-032). From Step 6 the
same containers run locally too: Docker on the Mac (rendering needs no GPU) and WSL2 on Windows.

## Initial model and tool picks (verify licenses, record in MODELS.md)

| Role | Pick | Notes |
|---|---|---|
| Director LLM | Qwen3 14B or gpt-oss-20b (Ollama) | Must support tool calling. Benchmark both in Step 0. |
| Vision QA | 7–8B Qwen-VL family model (Ollama) | |
| Image generation | SDXL-based flat cartoon / children's-book checkpoint + a few-step speed LoRA | **Check the checkpoint license for commercial use** |
| Segmentation | SAM 2 | Apache-2.0 |
| Depth | Depth Anything V2 **Small** | Small is Apache-2.0. Larger sizes are non-commercial. |
| TTS | Kokoro-82M (default), Chatterbox (expressive, optional) | Apache-2.0 / MIT |
| Lip-sync | Rhubarb Lip Sync | MIT |
| Music | ACE-Step | Apache-2.0. Verify Apple Silicon support. |
| Sound effects | CC0 libraries + CLAP embeddings in Qdrant | Check the CLAP model license |
| Vectorizing | vtracer | MIT |
| Animation engine | Synfig Studio (first film), **OpenToonz** (strategic, from Step 6) | GPL-3 / BSD-3 (D-031) |
| Edit and assembly | Kdenlive / MLT, ffmpeg | GPL / LGPL |

## Future tiers (not in v1)

Later, for anime-style films, each shot is assigned one tier by the director. Tiers 1–2 run on the
OpenToonz backend (multiplane camera, Plastic mesh deformation, effects). Tier 3 uses OpenToonz as
the compositor around AI-generated motion.

- **Tier 1, puppet rig:** v1. Dialogue and children's content.
- **Tier 2, limited animation:** strong keyframes plus camera moves, parallax, mesh deformation
  (Inochi2D-style), compositing effects (cel shading, rim light, speed lines), and swapped drawings.
- **Tier 3, full animation:** AI keyframes from a character LoRA, with motion generated *between our own
  start and end frames* by a first/last-frame video model on a rented GPU, then dropped back to
  "on twos/threes" timing.

## Repository layout (target, created as steps need it)

```
animation-studio/
  AGENTS.md  README.md  pyproject.toml (uv workspace)
  docs/        ARCHITECTURE, ROADMAP, DECISIONS, PROGRESS, MODELS, benchmarks.md, steps/, learning/
  scripts/     doctor (environment check), benchmarks, setup helpers
  schemas/     shotlist, rig and film JSON Schemas
  studio_core/ shared library: .sif builder, rig model, motion library, timing utils
  mcp/         synfig_mcp/  comfy_mcp/  audio_mcp/  edit_mcp/  qa_mcp/  (krita_mcp/ later)
  comfy_workflows/  ComfyUI workflows saved in API format
  director/    agent loop and stage state machine (Step 5)
  evals/       eval sets and harness (Step 7)
  tests/       unit tests + fixtures
  films/       generated film projects (git-ignored)
```
