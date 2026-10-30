# Roadmap

The first goal is **one prompt → a 60-second children's film**, fully local, in roughly 6–8 weeks of
part-time work. The final goal is **production-grade films** (the bar is defined below). Each step
has a "done when". Don't move on until it's met and verified.

**Step numbers are stable ids** (D-059). The history in PROGRESS and DECISIONS refers to them, so a
step inserted later gets a letter (4B) instead of renumbering the steps after it.

| Step | Name | Owner | Detailed brief |
|---|---|---|---|
| 0 | Environment setup + benchmarks | Agent | `steps/STEP-0-setup.md` (done) |
| 1 | Learn Synfig by hand + document its format | Owner + agent | `steps/STEP-1-synfig.md` (done) |
| 2 | `synfig_mcp`: scene, rig, motion, render tools | Agent (owner reviews) | `steps/STEP-2-synfig-mcp.md` (done) |
| 3 | `audio_mcp`: voices, lip-sync, music, sound effects, mix | Agent | `steps/STEP-3-audio-mcp.md` (done) |
| 4 | `comfy_mcp`: character puppets, backgrounds, parallax layers | Agent | `steps/STEP-4-comfy-mcp.md` (done, D-068) |
| 4B | Animation quality: puppets that hold up on screen | Agent (owner reviews) | `steps/STEP-4B-animation-quality.md` (draft, current) |
| 5 | Director agent + `edit_mcp` + `qa_mcp`: first full film | **Owner + agent** | to be written |
| 6 | OpenToonz backend + render containers (D-030–D-032) | Agent (owner reviews) | to be written |
| 7 | Evals: measure every change | **Owner + agent** | to be written |
| 8 | Durable pipeline: Temporal, MinIO, both machines | Agent (owner reviews) | to be written |
| 9 | Training: character and style LoRAs, director fine-tuning (SFT + GRPO) | **Owner + agent** | to be written |
| 10 | Series: longer episodes that reuse characters and places | Agent (owner reviews) | to be written |
| 11 | Production release (v1): meet the production-grade bar | Owner + agent | to be written |
| 12 | Future tiers: limited and full animation (anime styles) | Owner + agent | to be written |

At the end of each step, write the brief for the next one (`docs/steps/STEP-<n>-<name>.md`) and have
the owner review it before starting.

---

## The production-grade bar

What "production grade" means for a finished film. **Proposed targets, for the owner to confirm**
in the Step 4B and Step 5 briefs. Every step from 4B on works toward them, Step 7 measures them,
and Step 11 is done when films meet all of them unattended.

| Area | Target |
|---|---|
| Picture | 1080p24 (4K as an option), no seams, gaps, fringes or holes in any frame; characters on-model in every shot; smooth camera |
| Animation | Motions read clearly at a glance; limbs bend; hands and secondary parts (ears, tails) move; characters can walk across the frame |
| Lip-sync | Mouth changes within one frame (±42 ms) of the cue |
| Sound | −14 LUFS ±1 for the web (EBU R128 −23 LUFS as an option), true peak ≤ −1 dBTP, dialogue always intelligible over music |
| Story | A beginning, middle and end; every line and shot age-appropriate (`qa_mcp` safety check plus owner sign-off) |
| Rights | Every model and asset in the film commercial-OK, with a per-film provenance manifest (models, licenses, seeds, sound sources) |
| Reliability | Most prompts in a fixed test set produce a passing film with no manual steps (the rate is set in Step 7); a failed stage resumes; re-rendering a film folder gives the same film |
| Deliverables | Final MP4, an editable Kdenlive project, captions (SRT), a thumbnail and a credits/licenses file |
| Operations | Pinned, reproducible environments and render containers; logs and per-stage timings for every run; setup docs a new machine can follow |

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
- Test it with the MCP Inspector and with any MCP client (a coding agent or the Inspector).

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

Cut defects that remain after Step 4's own bar (outline dashes, seams, loose far-side limbs) are
recorded and carried into Step 4B. Step 4 closed on 2026-10-27 (D-068) with the cast pass bar met
(4 of 5: Kit, Bo, Pim, Mia); Bolt, the robot, is carried into Step 4B.

## Step 4B: Animation quality
Puppets that look finished on screen, not just correct in a test render. This is where the
picture and animation rows of the production-grade bar are met for cut-out films.

- **The cut, generalised:** varied characters (animals, children, birds, robots) cut cleanly in both
  views, including drawings that don't follow the skeleton. Carry-overs from Step 4.
- **Clean edges:** a drawn outline along every cut edge, no fringes or dashes left on other parts,
  no seams at joints in any pose.
- **Bending limbs:** Synfig's skeleton deformation (or a mesh) so an elbow or knee bends instead of
  showing two rigid rectangles.
- **Hands and secondary parts:** a few swappable hand poses (open, point, fist, wave); ears and tails
  as their own bones, with follow-through.
- **Moving through a shot:** placement that changes over time, and a real walk across the frame in
  the three-quarter view.
- **More acting:** more expressions and talk gestures, and motion timing reviewed against the
  principles in `docs/learning/motion-library.md`.
- **Automatic checks:** a pose sweep that renders every motion at its extremes and fails on holes,
  seams or detached parts; a review reel for the owner.

**Done when:** the varied cast performs every motion in a review reel that passes the automatic
checks and the owner's review.

## Step 5: Director agent + edit + QA → first film
- `qa_mcp`: a vision model compares preview frames against the shot spec, plus a children's-safety check.
- `edit_mcp`: MLT XML assembly (shots, audio, titles), `melt` render, and a Kdenlive project the owner
  can open.
- **Director (owner leads the agent loop core):** a hand-written loop on Ollama with tool calling.
  It runs a stage state machine over the film folder (story → characters → backgrounds → audio →
  shots → edit), uses schema-validated shot lists, has approval checkpoints, and resumes from the last
  completed stage. It must unload models between stages (Mac memory rule).
- **Veteran-animator director (D-065):** the director behaves like an animator with decades on these
  tools, not a prompt-follower. It gets four things, in this order of value:
  1. **A craft library** it retrieves from (RAG, `docs/craft/`): how each tool and motion is used,
     timing and spacing rules, staging, shot grammar, what fails and why (the lessons already in
     `docs/learning/` and DECISIONS), written as short playbooks.
  2. **A look-then-fix loop:** it renders a preview frame, `qa_mcp` describes what it sees against
     the shot spec, and the director revises before the final render (critique and retry).
  3. **Rules in code** for everything that must be exact (timing, frame counts, safety), so its
     judgment covers only choices.
  4. **A capability list** it reads first (`describe_*` tools), so it never plans something the
     tools can't do, and says so when a request is outside them.
  Later, Step 7 measures its choices and Step 9 trains them (SFT, then GRPO on the evals).
- Bring in the Windows laptop as a render node (Synfig rendering in parallel by shot).

**Done when:** one prompt produces a **60-second children's film** (2 characters, 2 backgrounds,
dialogue, music, sound effects) that the owner can open and polish in Kdenlive.

## Step 5B: Projects (own cast, shared places, many films)

Owner requirement (2026-10-30): the five test characters (Kit, Bo, Pim, Mia, Bolt) are only for testing. Every
**project** has its **own characters**, and has **many films** that reuse them; films also reuse the project's
**backgrounds**. Today a film folder holds its own `characters/` and `backgrounds/` and the cast is copied in
(`--import-cast`), so there is no project level.

- **Layout (proposal, D-082):** `projects/<project-id>/` holds `project.json` (name, premise, style, status),
  `characters/<id>/` (sheet, puppet, rig, voice; built once), `backgrounds/<id>/` (plates and depth layers),
  optional shared music cues, and `films/<film-id>/` (story, shots, audio lines, edit, QA, director state).
- **References, not copies:** `film.json` lists its cast and places as `{id, version}`; a resolver in `studio_core`
  finds them in the project. Characters and backgrounds are versioned and immutable once used by a film, so
  improving a character makes a new version and finished films keep rendering the same.
- **Director:** a story prompt in an existing project first reuses its characters and places; only missing ones go
  through the art stages, and they are added to the project library for the next film.
- **MCP servers:** tools take a project and a film id; no engine fields (D-030).
- **Migration:** the existing test films become a "test-cast" project; old film folders keep working through a
  one-off script.

**Status (2026-10-30):** data layer, servers and director are built (D-089, D-091, D-094); see `docs/steps/STEP-5B-projects.md`.

**Done when:** two different films in one project reuse the same characters and at least one shared background
without copying files; a new character built during film 2 is available to film 3; old films still render; tests
cover the resolver, versioning and migration.

### Storage rule for Steps 5B, 5C and 13 (D-084): ready for an online database later

Owner requirement (2026-10-30): later we may attach an online database for user logins and saved data. **Not now**;
the app stays local and offline by default. But the data must be structured so a database layer is easy to add:

- **One storage interface.** All reads and writes of project data go through a `ProjectStore` in `studio_core`
  (documents: get, put, list, delete; assets: put, open, exists). Today it is a filesystem implementation; an
  in-memory implementation exists for tests; a database plus object-storage implementation can follow without
  touching the director, MCP servers or GUI. Nothing outside the store builds file paths by hand.
- **Documents.** Specs are JSON documents with `schema_version`, a stable `id` (ULID or UUID, never a name or a
  path), `project_id`, `owner_id` (the string `"local"` until accounts exist), `created_at`, `updated_at` and an
  integer `rev` for optimistic concurrency.
- **References by id and version, never by path.** Specs contain no absolute or machine-specific paths.
- **Assets are content-addressed.** Media (sheets, plates, renders, audio) are asset records `{id, sha256, mime,
  bytes}` stored in a blob store keyed by hash, so they can move to S3-style storage; derived renders also carry
  their cache key (D-083) so they can be rebuilt or fetched.
- **The project is the tenancy boundary.** Every document belongs to one project and every query is scoped by
  project, so per-user permissions can be added without reshaping the data.
- **Runtime state as documents plus an append-only event log** (director state, approvals, stage runs), so it maps
  to tables directly.
- **No secrets or credentials in project data.**
- **Contract tests** run the same suite against every store implementation; the filesystem and in-memory stores
  must pass it now, and a future database store must pass it unchanged.
- Online accounts and sync are a later step (Step 14) and are opt-in; the fully-local rule still holds by default.

## Step 5C: Acts, editable source and "export all acts"

Owner requirement (2026-10-30): a whole film is broken into **acts** that the director directs one by one. Acts can
share or differ in **backgrounds**, and each has **multiple camera angles** (shots). The project renders each act
and **stitches all acts into one movie** when the user clicks "Export all acts as a movie". Until then every act
and animation stays in an **editable, changeable format**.

- **Hierarchy:** project > film > acts > shots. A film has `acts.json` (ordered acts: title, setting/background id,
  cast ids, story beats); an act has its shots (`shots/<id>/shot.json`, as today) with camera, framing, motion,
  expression and line cues per shot.
- **Source vs. cache:** the specs (`film.json`, `acts.json`, `shot.json`, audio line cues, edit lists) are the
  editable source of truth. Renders (frames, act videos, the movie) are derived and disposable. Nothing is baked
  into media until export.
- **Per-act render with staleness:** each act render is keyed by a content hash of its specs plus the versions of
  the characters, backgrounds and engine it uses. Editing a shot marks only its act stale; "render" redoes stale
  acts only; "export all acts" renders any stale act, then stitches the act videos (with audio, music continuity
  and optional transitions) through `edit_mcp` into one movie.
- **Director:** works act by act, with an approval stop per act (resumable, retry one act without touching the
  others); it picks the act's background from the project's library and plans multi-angle coverage (establishing,
  two-shot, close-up, reaction; see `docs/craft/`).
- **Edit later:** a change to one shot (camera, expression, line, motion) is a spec edit by the user, the GUI
  (Step 13) or the director (`revise`), followed by re-render of that act only.

**Done when:** a 3-act test film with different backgrounds and at least three camera angles per act renders per
act; editing one shot re-renders only its act; "export all acts" produces one movie; deleting all renders and
re-exporting gives the same film from the specs alone; tests cover hashing, staleness and the stitch order.

## Step 5D: Visual reviewer (a gate that looks at the picture)

Why (2026-10-30): the owner had to point out that Mia's face was wrong (huge eyes at the head edges, a mouth beside the
eye) and that the motion was not smooth. Our QA checked facts (holes, seams, size, loudness) and our reports quoted
defect counts; nobody looked at the frames. See `docs/spikes/owner-review-bakeoff.md`.

Build a reviewer that runs before any film or clip is shown to the owner, and fails it with reasons:
1. **Deterministic checks (code):** face proportion limits (eye spacing and size, mouth below the nose, face inside the
   head and following it), motion smoothness (velocity and jerk limits, no pops between expressions or shots), style
   consistency between character and background (palette, line weight, level of detail).
2. **Vision-model review (local):** sampled frames plus a short rubric ("normal face? same character as the sheet?
   limbs attached? matches the background style?"), results written next to the film. Calibrate it against the owner's own
   verdicts (the bake-off clip and the Mia clip are the first two labelled examples).
3. **Review reel for the owner:** key frames and a short clip, shown only after the gates pass.
Done when: the reviewer rejects the 2026-10-30 Mia clip for the reasons the owner gave and passes a hand-checked good one.
Ask the owner before building the vision-model rubric (it overlaps with the eval harness, which the owner may want to write).

## Step 6: OpenToonz backend + render containers

> **Pending rewrite (D-087, D-090):** the engine pick (Blender and/or OpenToonz, replacing Synfig) is made by the owner after the
> skinned-mesh spike and the look review. Rewrite this step then. Until then treat the text below as the old plan.
The strategic engine (D-031) behind the engine-neutral scene model (D-030), packaged for server-side
rendering (D-032). Starting point: the spike scripts in `scripts/spikes/` and `docs/spikes/opentoonz.md`.

- **Backend interface** in `studio_core/engines/`: `compile(film, shot) → engine project` and
  `render(project, frame range) → frames`. Refactor the Synfig code behind it first, with no behavior
  change and all existing tests passing.
- **OpenToonz backend:** generate `.tnz` from our schemas:
  - character parts become levels
  - rig bones become a pegbar hierarchy (Plastic skeletons later)
  - motion channels become keyframes
  - background depth layers become multiplane columns at camera Z depths
  - camera moves, and compositing effects where the shot asks for them
- **Plastic meshes that follow each part's outline.** The spike showed rectangular meshes bend
  stiffly, and skeleton points on mesh edges are ignored.
- **Render container:** a Linux image with a pinned OpenToonz built from source, Xvfb and `tcomposer`.
  Add a Synfig image too. Both run on the Mac (Docker) and Windows (WSL2), and later in the cloud.
  Inputs and outputs go through MinIO/S3.
- **Conformance tests:** the same shots through both backends, comparing pose positions and timing
  within tolerance. Add golden-file tests for `.tnz` output.

**Done when:** the Step 5 film re-renders through OpenToonz from the same film folder, with **no
changes to the director or the schemas**, inside the render container, and passes the conformance
tests.

## Step 7: Evals
Turn the production-grade bar into numbers that run on every change. **Ask the owner before
building the harness** (AGENTS.md): propose the design and a skeleton first.

- A fixed set of test prompts, plus golden film folders to re-render.
- Metrics:
  - character consistency across shots (embedding similarity)
  - palette adherence (exact)
  - lip-sync timing error
  - holes, seams and fringes (pixel checks, from Step 4B)
  - loudness and true peak
  - a vision judge for shot-vs-spec
  - a children's-safety classifier
  - end-to-end success rate and time per film
- A report per run, compared with the last baseline, so a regression is visible before it lands.

**Done when:** one command runs the suite on the test prompts, writes a report with every metric
against its target, and flags any regression from the stored baseline.

## Step 8: Durable pipeline
- **Temporal:** each director stage becomes a durable activity with retries, so a crash or a reboot
  resumes mid-film.
- **Task queues by capability:** `ai` workers (Mac) and a pool of render containers (the Windows
  laptop is one).
- **MinIO** for shared assets, so moving to the cloud is a configuration change (D-032).
- Logs, traces and per-stage timings for every run.

**Done when:** a film runs across both machines through Temporal, survives killing a worker mid-stage
(it resumes and finishes), and every run's timings are visible.

## Step 9: Training
Needs Step 7, because every training run is judged by the evals.

- **Character LoRAs:** new poses and views of a cast character that stay on-model.
- **Style LoRAs:** a house style, trained only on art we own or are licensed to use.
- **Director fine-tuning:** LoRA supervised fine-tuning of a small LLM to write valid shot lists,
  then **GRPO with a verifiable reward** (the shot list validates, renders without errors and passes
  the QA checks).

**Done when:** a fine-tuned director beats the base model on the Step 7 suite, and a character LoRA
improves the consistency metric, both measured.

## Step 10: Series
- 3–7 minute episodes that reuse characters, voices and places across a series.
- A series bible (characters, places, style lock, recurring music) and story memory with retrieval
  (RAG), so later episodes stay consistent with earlier ones.
- Longer edits: scenes, transitions, titles and credits.

**Done when:** two episodes of one series are made from prompts, with the same characters and
places, and pass the Step 7 suite.

## Step 11: Production release (v1)
- Close every gap between the eval report and the production-grade bar.
- Package the studio for the owner's chosen delivery (hosted, desktop or both: an open owner
  decision since 2026-10-21).
- A licensing and provenance audit of every model and asset, and the per-film provenance manifest.
- A safety review of the whole pipeline for children's content.
- Setup and operating docs that a new machine can follow from scratch.

**Done when:** the test prompts produce films that meet every row of the production-grade bar with no
manual steps, and a clean machine can be set up from the docs alone.

## Step 12: Future tiers
After v1. Anime-style films on the OpenToonz backend, one tier chosen per shot by the director (see
ARCHITECTURE, "Future tiers"):

- **Tier 2, limited animation:** strong keyframes plus camera moves, parallax, mesh deformation,
  compositing effects and swapped drawings.
- **Tier 3, full animation (D-064):** AI-made key scenes ("from" and "to" frames, kept on-model by a
  character LoRA), with the in-betweens done by our own tools, not by a video-generation model.

**Done when:** to be set in the step's brief, against the same production-grade bar.

## Step 13: Desktop app (studio GUI)

Owner requirement (2026-10-30): in the end the studio is a desktop app with a GUI to keep **projects and
stories**, **talk to the director** (give a prompt, see its plan, approve or revise at the four stops, retry a
stage) and **browse the saved files** (character sheets, backgrounds, shot previews, the final film, logs).

- **Design rule:** the GUI is a thin client over the same state the CLI uses (`director/` state folder, the film
  folder, the approval review files). Nothing may live only in the GUI, and the CLI keeps working.
- **Shape (proposal, see D-081):** a small local Python backend (FastAPI) exposing the director commands
  (`new | resume | approve | revise | retry | status`), the project list and file listing, with a Svelte UI,
  packaged as a desktop app with Tauri (Electron as the fallback). Local only, no accounts, no cloud.
- **Screens:** project library; story and director chat with a stage timeline and approval buttons; file browser
  with media preview (images, video with audio); run log and cost/time per stage.
- **Independent of the engine choice**, so a first version (project list, director console, file browser) can be
  built in parallel with Step 6 and the engine bake-off.

- **Install target (D-085): macOS on Apple Silicon (arm64) only, for now.** The deliverable is a signed-or-ad-hoc
  `.app` in a `.dmg` that a user drags into Applications. The app is a shell plus the Python backend (shipped as
  a sidecar with its own `uv`-built Python 3.12 environment, so the system Python does not matter). It does **not**
  contain models or the big engines: on first launch a **Setup screen** checks the machine (Apple Silicon, memory,
  free disk), installs or locates the engines (Blender, OpenToonz or Synfig, ffmpeg/MLT, Ollama, Rhubarb,
  ComfyUI) and downloads the models into the user's models folder, with licence and size shown before each
  download, a progress bar, resume and a "repair" button. Data lives in `~/Library/Application Support/` (settings,
  caches) and a user-chosen projects folder; the store interface (D-084) keeps it portable. Windows and Intel
  Macs are out of scope until the Windows node step.
- **Distribution:** personal use needs no Apple Developer account (ad-hoc signing, first launch via right-click
  Open). Sharing the `.dmg` with others needs a paid Developer ID and notarization; decide at the step's brief.
  GPL engines are installed separately or bundled with their licence notices and source offers.

**Done when:** from a fresh `.dmg` install on a clean Apple Silicon Mac, with no terminal commands, a new story prompt becomes a finished film, with every approval stop answered
in the UI, and a closed and reopened app resumes the project where it was.

## Step 14: Online backend (later, opt-in)

Not scheduled. Accounts and logins, a database store and object storage behind the `ProjectStore` interface
(Storage rule, D-084), sync between devices and sharing. Done when a project created locally can be pushed to the
online store, opened by its owner on another machine and rendered there, with the same contract tests passing.
