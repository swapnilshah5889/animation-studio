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

## MCP servers

Each server wraps one open-source app and exposes a small set of tools. The tool names below are a
starting point: refine them while building, and record changes in DECISIONS.md.

| Server | Wraps | Example tools | Integration level |
|---|---|---|---|
| `synfig_mcp` | **Synfig Studio** (2D cut-out, bones, tweening) | `create_scene`, `build_rig`, `pose_at`, `apply_motion`, `apply_lipsync`, `add_parallax_background`, `camera_move`, `render_preview_frame`, `render_shot` | Generate and edit `.sif` XML, render with the `synfig` CLI |
| `comfy_mcp` | **ComfyUI** (image generation, SAM 2, depth) | `generate_character_sheet`, `cut_into_parts`, `generate_background`, `split_depth_layers`, `inpaint` | ComfyUI HTTP API plus saved workflows in `comfy_workflows/` |
| `audio_mcp` | **Kokoro / Chatterbox** (TTS), **Rhubarb** (lip-sync), **ACE-Step** (music), CC0 sound library | `speak`, `lipsync`, `compose`, `find_sfx`, `mix` | Python and CLI. Sound effect search uses audio embeddings (CLAP) in Qdrant. |
| `edit_mcp` | **Kdenlive / MLT** | `assemble`, `add_titles`, `export` | Generate MLT XML and render with `melt`. The owner can open the project in Kdenlive. |
| `qa_mcp` | Local vision model (Ollama) | `check_frame`, `kid_safety_check` | Ollama API |
| `krita_mcp` (optional, later) | **Krita** + AI Diffusion plugin | `cleanup_part`, `lock_palette`, `export_layers` | Level 2: a Krita Python plugin opens a local socket |

**Integration levels:** (1) wrap file formats, CLIs and APIs (the default). (2) In-app plugins so the
LLM can act on what's open in the GUI. (3) Modify app source, only as a last resort.

**License note:** Synfig, Krita, Kdenlive and ComfyUI are GPL. Wrapping them via files, CLIs and APIs
keeps our code separate. If we ever distribute *modified* versions of them, GPL requires publishing
those changes.

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
  Claude Code as the client.
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
| Animation engine | Synfig Studio | GPL-3 |
| Edit and assembly | Kdenlive / MLT, ffmpeg | GPL / LGPL |

## Future tiers (not in v1)

Later, for anime-style films, each shot is assigned one tier by the director:

- **Tier 1, puppet rig:** v1. Dialogue and children's content.
- **Tier 2, limited animation:** strong keyframes plus camera moves, parallax, mesh deformation
  (Inochi2D-style), compositing effects (cel shading, rim light, speed lines), and swapped drawings.
- **Tier 3, full animation:** AI keyframes from a character LoRA, with motion generated *between our own
  start and end frames* by a first/last-frame video model on a rented GPU, then dropped back to
  "on twos/threes" timing.

## Repository layout (target, created as steps need it)

```
animation-studio/
  CLAUDE.md  README.md  pyproject.toml (uv workspace)
  docs/        ARCHITECTURE, ROADMAP, DECISIONS, PROGRESS, MODELS, benchmarks.md, steps/, learning/
  scripts/     doctor (environment check), benchmarks, setup helpers
  schemas/     shotlist, rig and film JSON Schemas
  studio_core/ shared library: .sif builder, rig model, motion library, timing utils
  mcp/         synfig_mcp/  comfy_mcp/  audio_mcp/  edit_mcp/  qa_mcp/  (krita_mcp/ later)
  comfy_workflows/  ComfyUI workflows saved in API format
  director/    agent loop and stage state machine (Step 5)
  evals/       eval sets and harness (Step 6)
  tests/       unit tests + fixtures
  films/       generated film projects (git-ignored)
```
