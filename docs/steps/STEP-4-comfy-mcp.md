# Step 4: `comfy_mcp`: character puppets and parallax backgrounds from text

> **Status: approved by the owner on 2026-10-22, as written (installs and proposed decisions
> included, recorded in D-047).** Tasks 4.1-4.10 done. Closed against a pass bar on a varied
> cast (D-060): Kit, Bo and Pim pass; Mia and Bolt are tracked manual cleanup carried into
> Step 4B (D-066: 3 of 5 measured, the bar was 4 of 5, so the owner's call on closing).

**Goal:** an MCP server that turns words into the two kinds of art a shot needs:
- a **character description** → a rigged cut-out puppet (`rig.json` + parts + a faceless head
  with its face geometry) that `synfig_mcp` animates like Pip
- a **place description** → a **parallax background** (`layers.json` + depth layers)

There are no manual steps; manual cleanup is allowed but tracked. Pip and the meadow were drawn
in code; from here on, the art comes from the film's style preset.

**Out of scope:**
- Training (character LoRAs come in Step 9). Consistency comes from one generation per
  character, reused by the rig (D-007).
- Side views and walk cycles across the frame (later).
- The director and the vision QA server (Step 5). Here the clients are scripts, the Inspector
  and the owner's eyes.
- Vector parts by default. Vectorizing stays optional (task 4.4) until Synfig's SVG import is
  tested.

## What Steps 0–3 established (build on it, don't relitigate)

- **ComfyUI v0.42.1** native on MPS, started on demand (D-017).
  - Node packs: SAM 2 (kijai) and `comfyui_controlnet_aux`.
  - Installed models: SAM 2.1 hiera-small and Depth Anything V2 **Small**.
  - The `DepthAnythingV2Preprocessor` default is the non-commercial Large model, so the
    checkpoint is always named explicitly.
- **Styles are a parameter, locked per film** (D-025): `storybook` (default), `cutecartoon`,
  `animagine`, and `dreamshaper-lightning` (commercial unclear). `comfy_graphs.txt2img` builds
  graphs from `config/models.toml`, and kid-safety terms are always in the negative prompt. The
  first character locks the film's style.
- **The contracts are ours** (D-030):
  - `rig.json`: bones with role, side, direction and attach point; parts with size and pivot;
    draw order; and a `face` block of eye, brow and mouth positions on a **faceless** head
    (D-007, the face is drawn in code).
  - `layers.json`: layers far to near with parallax factors and `in_front`.
  - Pip and the meadow are the reference examples. `shot_spec.register_rig` validates a rig.
- **Machine rules:** one large model at a time. Unload Ollama before ComfyUI work, and free
  ComfyUI memory (`/free`) before LLM or music work. `compose` already refuses to run while
  ComfyUI is up.
- **Vision model:** qwen3-vl 8B Instruct via Ollama (D-018), available for automatic checks
  (sequenced, never alongside SDXL).

## Owner checkpoints

1. **Approve this brief.**
2. **First character designs (task 4.3):** four candidate sheets for one described character,
   in the film's style. Is the look right? Are the heads faceless? Are the limbs clear of the
   body?
3. **Puppet test (task 4.4):** the cut and rigged puppet waving, blinking and talking in a test
   render, next to Pip.
4. **Background test (task 4.7):** a generated place, split into layers, during a slow pan.

## Design decisions proposed here (owner may overrule)

| Topic | Proposal | Why |
|---|---|---|
| Pose | **Draw the skeleton in code** (OpenPose-style stick figure, child proportions, limbs apart) and condition SDXL on it with ControlNet (xinsir union ProMax, Apache-2.0). The same skeleton becomes the rig | Joint positions are then *known*, not estimated: no pose estimator in the critical path, and the NC OpenPose models are avoided entirely |
| Both views at once | A **turnaround canvas**: front and three-quarter skeletons side by side in one generation | One sampling pass for both views is the cheapest consistency we can get without training |
| Faceless heads | "faceless, blank face" in the prompt, plus a code fallback: the face area of the head mask is filled with the head's median skin colour | Faces are drawn procedurally (D-007); the fallback makes it deterministic |
| Cutting parts | **Geometric**: the character's silhouette (plain background → colour key, refined with SAM 2.1), each pixel assigned to the nearest bone segment of the known skeleton | Photo-trained segmenters fail on cartoon body parts (published results); the skeleton is exact |
| Joints that rotate | Each limb part gets a rounded **cap** past its joint, filled in code with the part's own colours, so a rotating arm never shows a gap. A Fooocus inpaint pass is an optional upgrade | Deterministic, fast, no extra model on the default path |
| Rig draft | Bones, pivots, attach points, draw order (back arm, legs, torso, head, front arm), joint limits by role, and a face block from head proportions. Validated by `register_rig`, then a test render | The output is our schema (D-030); `synfig_mcp` needs nothing new |
| Palette | k-means palette (≤ 12 colours) of the chosen design → `characters/<id>/palette.json`; optional quantize | Keeps re-cuts and later views on-model; smaller files; ready for vectorizing |
| Backgrounds | Generate at **1536×576** (8:3, an SDXL bucket), upscale with **Real-ESRGAN x4plus_anime_6B** (BSD-3) to 2880×1080, then a low-denoise refine pass | Native-bucket composition plus a permissive upscaler; TiledDiffusion is NC |
| Depth | **Depth Anything 3 MONO-LARGE** (Apache-2.0, ComfyUI-native), compared once against the installed DAv2-Small. Never the NC defaults | Better depth with a clean license, and no custom node |
| Layers | Depth quantiles → 3–4 bands (sky/far/mid/ground), plus a foreground band if the bottom is near. **Fill behind** each nearer band with ProMax's inpaint ("repaint") mode, then parallax factors from each band's depth | Pans must never reveal holes; one ControlNet model does both pose and fill |
| Memory | ComfyUI on demand; unload Ollama first; `/free` after each batch | The M4 rule |

## Installs this step needs (approve with the brief)

All local after download; no API keys; each under the 20 GB ask-first limit.

| Install | License | Size | Purpose |
|---|---|---|---|
| xinsir **controlnet-union-sdxl-1.0 ProMax** | Apache-2.0 | 2.51 GB | Pose conditioning; inpaint/repaint for background fills |
| **Depth Anything 3 MONO-LARGE** (ComfyUI native) | Apache-2.0 | ~1.4 GB (0.35B params) | Depth for layers |
| **Real-ESRGAN x4plus_anime_6B** (+ x4plus) | BSD-3 | ~18 MB / ~64 MB | Background upscaling (ComfyUI core loads ESRGAN models) |
| SAM 2.1 **base+** | Apache-2.0 | 162 MB | Silhouette refinement (small is installed) |
| *Optional, task 4.4:* Fooocus inpaint patch v2.6 + Acly's comfyui-inpaint-nodes | OpenRAIL (patch); GPL-3 (node code, run inside ComfyUI) | 1.32 GB | Better joint fills with our own style checkpoints |
| *Optional, task 4.5, owner decides:* FLUX.2 [klein] **4B** | Apache-2.0 (**the 9B is NC**) | ~13 GB | Front → three-quarter edits if the turnaround isn't consistent enough |

**Not used, because they're non-commercial:** CMU OpenPose models and thibaud's OpenPose
ControlNet, MAT, Depth Anything V2 Base/Large and DA3 Giant/Nested, FLUX.1 Kontext dev, FLUX.2
klein 9B, InstantCharacter, 4x-UltraSharp/AnimeSharp, TiledDiffusion. **Unclear, so not on the
default path:** LaMa's weights, DWPose's training data.

## Tasks

### 4.1 ComfyUI plumbing
- `studio_core/comfy_runs.py`: run a graph with parameters, wait, and copy outputs into the
  film folder. The style comes from the film's lock.
- Graphs live in `comfy_workflows/` (API format) and are built by code from `config/models.toml`.
- Memory guard: unload Ollama, refuse while ACE-Step runs, `/free` after a batch.
- Each run's graph, seed and timings are saved next to its outputs, so any image can be
  regenerated.

### 4.2 Skeleton templates
- `studio_core/puppet/skeleton.py`: one engine-neutral definition of the puppet skeleton (child
  proportions; front and three-quarter), the same joints as `rig.json` roles.
- It draws (a) the OpenPose-style conditioning image and (b) the rig's bones from the same
  numbers. Tests check that they agree.

### 4.3 `design_character` (owner checkpoint 2)
- Description + film style → N turnaround candidates. Pose from the skeleton, plain
  background, "faceless" in the prompt; seeds recorded.
- Cheap automatic checks per candidate: one figure per view (silhouette count), a plain
  background, limbs clear of the torso. Optionally qwen3-vl afterwards, sequenced.

### 4.4 `build_puppet` (owner checkpoint 3)
- From the chosen candidate:
  - the silhouette (colour key + SAM 2.1)
  - parts by nearest bone, with joint caps
  - the faceless fill
  - the face block, palette, `rig.json` and part PNGs
- Registered through `shot_spec.register_rig`, then a test render (rest pose, wave, blink,
  talk) through the Synfig backend.
- Optional: Fooocus inpaint for joint caps; vtracer SVG parts, used only if Synfig's
  `svg_layer` renders them from the CLI.
- Measured: how far generated limbs drift from the skeleton (silhouette vs bone corridors).
  Big drift means a rejected candidate.

### 4.5 Three-quarter view
- Rig the turnaround's second figure as the `three_quarter` view of the same character.
- If consistency is poor, the owner decides on FLUX.2 klein 4B (13 GB) for front → 3/4 edits,
  or leaves 3/4 for later.

### 4.6 `generate_background`
- Description + style → N candidates at 1536×576 → Real-ESRGAN → 2880×1080 → low-denoise
  refine. Ground band kept clear enough for characters to stand on.

### 4.7 `split_depth_layers` (owner checkpoint 4)
- Depth (DA3 MONO-LARGE vs DAv2-Small, measured once) → bands → masks → fill behind each
  nearer band → `layers.json` with parallax factors. Validated by the background schema.
- A pan test render through the Synfig backend.

### 4.8 `comfy_mcp` server
- Tools: `describe_art`, `design_character`, `choose_design`, `build_puppet`,
  `preview_puppet`, `generate_background`, `choose_background`, `split_depth_layers`,
  `preview_background`.
- Same conventions as the other servers (D-034, D-046). Added to `.mcp.json` and the Inspector
  check.

### 4.9 Prove it
- A scripted MCP client goes from text to a new character and a new place, then makes a shot
  with them through all three servers (animation, sound, art), and renders it.

### 4.10 Docs
- Learning notes:
  - diffusion conditioning (ControlNet)
  - segmentation vs geometry for cutting puppets
  - monocular depth and layering
  - consistency without training
- DECISIONS, PROGRESS, MODELS, and the Step 5 brief.

## Done when

- [x] The brief's decisions approved; the installs done and recorded in MODELS.md with licenses
- [x] A text description becomes a **rigged puppet** (front view, faceless head with face
      geometry) that `synfig_mcp` animates (wave, blink, lip-sync) in a test render, with no
      manual steps (holds for Kit, Bo and Pim only; Mia and Bolt need cleanup, D-060, D-066)
- [x] The three-quarter view is rigged too, or explicitly deferred by the owner (task 4.5)
- [x] A text description becomes a **parallax background** whose layers pan without holes
- [x] `comfy_mcp` exposes the tools over stdio; all are tested; the Inspector check covers it
- [x] A shot with a new character in a new place, made only through MCP tools, rendered
- [ ] Learning notes, DECISIONS, PROGRESS, MODELS updated; Step 5 brief drafted; work committed
      and pushed

## Risks

- **Pose drift:** SDXL may not follow the skeleton exactly, and limbs then fall outside their
  bone corridors. Mitigations: ControlNet strength, several candidates, and a measured drift
  check that rejects bad ones.
- **Faceless generation** is unreliable from prompts alone. The code fill makes it
  deterministic but may look flat on textured skin.
- **Turnaround consistency** without training is the hardest part. The fallback (FLUX.2 klein
  4B) is large and needs the owner's OK.
- **Speed on the M4:** SDXL + ControlNet at 1024-class sizes is tens of seconds per image.
  Candidates are batched, and the measured times go into benchmarks.md.
- **Licenses:** OpenRAIL models carry use restrictions (we stay within children's content).
  Unclear ones (LaMa, DWPose's data) stay off the default path.

## Research notes

Web research, 2026-10-22, nothing downloaded:
- xinsir ControlNets: [union ProMax](https://huggingface.co/xinsir/controlnet-union-sdxl-1.0),
  [openpose](https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0) (Apache-2.0; better
  HumanArt mAP than thibaud's, whose license follows OpenPose's: treated as NC).
- [CMU OpenPose license](https://github.com/CMU-Perceptual-Computing-Lab/openpose/blob/master/LICENSE):
  noncommercial research only.
- Cartoon body-part segmentation: photo-trained segmenters fail. The published fixes cut from
  the pose skeleton (SegAnimeChara, SIGGRAPH 2023 poster).
- [SAM 2.1](https://github.com/facebookresearch/sam2): Apache-2.0. SAM 3/3.1: custom "SAM
  License" (no NC clause; same-license redistribution); MPS unverified.
- [Depth Anything 3](https://github.com/ByteDance-Seed/Depth-Anything-3): Apache for
  SMALL/BASE/MONO-LARGE/METRIC-LARGE; NC for Giant/Nested; native in ComfyUI. DAv2 Base/Large:
  CC-BY-NC.
- [Meta Animated Drawings](https://github.com/facebookresearch/AnimatedDrawings): MIT code and
  weights, joints for drawn figures. Archived 2025-09; a possible drift checker.
- [FLUX.2 klein](https://bfl.ai/blog/flux2-klein-towards-interactive-visual-intelligence): 4B
  Apache-2.0, 9B NC. [IP-Adapter](https://huggingface.co/h94/IP-Adapter): Apache-2.0 (its
  ComfyUI pack is GPL-3, maintenance-only).
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN): BSD-3. 4x-UltraSharp: CC-BY-NC-SA.
  [TiledDiffusion](https://github.com/shiimizu/ComfyUI-TiledDiffusion): CC BY-NC-SA code.
- [vtracer](https://github.com/visioncortex/vtracer): MIT. Synfig's `mod_svg` converts SVG to
  native layers, with partial arc support; untested by us.
