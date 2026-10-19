# Roadmap

The first goal is **one prompt → a 60-second children's film**, fully local, in roughly 6–8 weeks of
part-time work. Each step has a "done when". Don't move on until it's met and verified.

| Step | Name | Owner | Detailed brief |
|---|---|---|---|
| 0 | Environment setup + benchmarks | Agent | `steps/STEP-0-setup.md` |
| 1 | Learn Synfig by hand + document its format | Owner + agent | to be written |
| 2 | `synfig_mcp`: scene, rig, motion, render tools | Agent (owner reviews) | to be written |
| 3 | `audio_mcp`: voices, lip-sync, music, sound effects, mix | Agent | to be written |
| 4 | `comfy_mcp`: character puppets, backgrounds, parallax layers | Agent | to be written |
| 5 | Director agent + `edit_mcp` + `qa_mcp`: first full film | **Owner + agent** | to be written |
| 6 | Evals, Temporal, second machine, LoRAs, fine-tuning | Owner + agent | to be written |

At the end of each step, write the brief for the next one (`docs/steps/STEP-<n>-<name>.md`) and have
the owner review it before starting.

---

## Step 0: Environment setup + benchmarks
Install and verify every tool and model on the Mac, and measure how fast each stage runs.

**Done when:** `scripts/doctor` reports every tool OK, every model is recorded in `MODELS.md` with its
license, and `docs/benchmarks.md` holds measured timings for each stage.

## Step 1: Learn Synfig by hand + document its format
- **Owner:** builds a ~10-second scene by hand in Synfig Studio: an imported image layer, a simple bone
  rig, two waypoints (a wave), a switch layer for mouth shapes, and a moving background. The point is
  to understand exactly what we will automate.
- **Agent:** reverse-documents the resulting `.sif` XML (our own files, which is fine) in
  `docs/learning/synfig-format.md`. That covers layers, groups, bones and skeleton deformation,
  waypoints and interpolation, switch layers, canvas and time settings, and image import. Then it builds
  a minimal Python `.sif` generator in `studio_core/` that reproduces a similar scene and renders it
  through the CLI.

**Done when:** a Python script generates a `.sif` from scratch that renders to a correct MP4 with a
waving puppet and a moving background.

## Step 2: `synfig_mcp`
- JSON Schemas: `schemas/rig.schema.json`, `schemas/shotlist.schema.json`.
- Rig model: parts, pivots, bone hierarchy, views (front, three-quarter).
- **Procedural face:** vector eyes (with blink), eyebrows (expressions), and a **mouth set matching
  Rhubarb's shapes (A–H, X)** on a switch layer.
- **Motion library v1:** idle breathe, blink, wave, nod, head tilt, walk cycle, jump, point, talk
  gestures. Each one is parameterized (duration, energy, side) and unit-tested for timing.
- MCP tools: `create_scene`, `build_rig`, `pose_at`, `apply_motion`, `apply_lipsync`,
  `add_parallax_background`, `camera_move`, `render_preview_frame`, `render_shot`.
- Test it with the MCP Inspector and with Claude Code as the client.

**Done when:** from a client, the LLM builds and renders a 10-second shot of a rigged character waving
and blinking in front of a parallax background, with a placeholder mouth cue track driving the mouth.

## Step 3: `audio_mcp`
- `speak(line, voice)`: Kokoro by default, Chatterbox for expressive lines. Per-character voice
  presets, with a pitch/speed adjustment option for child-like voices.
- `lipsync(audio, text)`: Rhubarb with the dialogue text passed in for accuracy. Output is JSON mouth
  cues in our schema.
- `compose(mood, duration, with_lyrics?)`: ACE-Step.
- `find_sfx(query)`: a CC0 sound library indexed with CLAP audio embeddings in Qdrant (Docker).
- `mix(tracks)`: ffmpeg with ducking (music dips under dialogue), plus loudness normalization for the
  web.

**Done when:** a line of dialogue is voiced, lip-synced onto the Step 2 puppet automatically, and mixed
with music and one sound effect into a playable shot.

## Step 4: `comfy_mcp`
- ComfyUI running natively with a saved workflow per task in `comfy_workflows/` (API format).
- `generate_character_sheet`: a flat children's style, a neutral puppet pose with limbs apart, on a
  plain background. Also a three-quarter view.
- `cut_into_parts`: SAM 2 segmentation into head, torso, arms, legs, plus inpainting of hidden areas
  near the joints. Output is parts plus a draft `rig.json` with pivot estimates.
- Palette lock and optional vectorizing (vtracer).
- `generate_background` + `split_depth_layers` (Depth Anything V2 Small + inpainting behind the
  foreground) → `layers.json` with parallax factors.

**Done when:** a text description of a character becomes a rigged puppet that `synfig_mcp` can
animate, and a text description of a place becomes a parallax background, with no manual steps (manual
cleanup allowed but tracked).

## Step 5: Director agent + edit + QA → first film
- `qa_mcp`: a vision model compares preview frames against the shot spec, plus a children's-safety check.
- `edit_mcp`: MLT XML assembly (shots, audio, titles), `melt` render, and a Kdenlive project the owner
  can open.
- **Director (owner leads the agent loop core):** a hand-written loop on Ollama with tool calling.
  It runs a stage state machine over the film folder (story → characters → backgrounds → audio →
  shots → edit), uses schema-validated shot lists, has approval checkpoints, and resumes from the last
  completed stage. It must unload models between stages (Mac memory rule).
- Bring in the Windows laptop as a render node (Synfig rendering in parallel by shot).

**Done when:** one prompt produces a **60-second children's film** (2 characters, 2 backgrounds,
dialogue, music, sound effects) that the owner can open and polish in Kdenlive.

## Step 6: Level up (pick in any order)
- **Evals:** character consistency (embedding similarity), palette adherence (exact), lip-sync timing
  error, a vision judge for shot-vs-spec, and a safety classifier. Run them on every change.
- **Temporal:** durable stages, retries, task queues by capability (`ai-mac`, `render-win`), MinIO.
- **LoRAs:** character LoRAs for new poses and views. Style LoRAs.
- **Fine-tune the director:** LoRA supervised fine-tuning of a small LLM to write valid shot lists, then
  **GRPO with a verifiable reward** (the shot list validates, renders without errors, and passes QA
  checks).
- **Longer films:** 3–7 minute episodes that reuse characters and backgrounds across a series.
- **Future tiers:** limited animation (Tier 2) and full animation (Tier 3) for anime style. See
  ARCHITECTURE.
