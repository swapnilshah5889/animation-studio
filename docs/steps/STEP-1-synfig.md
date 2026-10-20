# Step 1: Learn Synfig by hand + document its format

> **Status: draft for owner review.** Written at the end of Step 0. Nothing here starts until the
> owner approves it (and may change it).

**Goal:** understand exactly what we will automate. The owner builds a short cut-out scene by hand
in Synfig Studio. The agent reverse-documents the resulting `.sif` XML (our own files) and then
writes a small Python generator that produces a similar scene from scratch and renders it through
the CLI.

**Out of scope:** MCP servers (Step 2), procedural faces and the motion library (Step 2), AI-generated
art (Step 4), audio beyond a placeholder mouth track.

## What Step 0 already established

- **Renderer:** Synfig 1.5.5 CLI from the Homebrew formula, native arm64, at `/opt/homebrew/bin/synfig`
  (D-014). Renders the 1080p smoke scene at about 0.03 s per frame.
- **GUI:** Synfig Studio 1.5.5 from the official DMG (`~/ai-studio/downloads/synfig-1.5.5/`). It is
  x86_64 and unsigned, so the owner installs it and approves it in System Settings → Privacy &
  Security → "Open Anyway". It runs under Rosetta 2. Same version as the CLI, so files match.
- **Format facts found so far** (from `tests/fixtures/smoke/smoke.sif`):
  - Layers in a canvas are listed bottom-first.
  - Interpolation names in the file differ from the GUI's labels: `halt` (= ease in/out),
    `linear`, `clamped`, `constant`, `auto` (= TCB). The parser rejects `ease`.
  - A `group` layer's `origin` is the pivot. Its `transformation` composite (`offset`, `angle`,
    `skew_angle`, `scale`) moves and rotates the group around that pivot. Nested groups give
    forward kinematics: a cut-out rig without bones.
  - `import` layers place a PNG between `tl` and `br` corners, in canvas units.
  - Time values accept seconds (`2s`) and frames (`12f`).
  - The CLI quirk: `synfig --version` exits with code 3. The Homebrew build has no JPEG module, so
    use PNG.
- **Pipeline rule from the benchmarks:** render PNG frames with Synfig, encode each shot with
  ffmpeg, and use melt only to assemble finished MP4s. Melt reading PNG sequences is about 28x
  slower.

## Owner checkpoints

1. **Approve this brief** (or edit it).
2. **Rig technique (decide after task 1.2):** nested-group transforms (forward kinematics, like the
   smoke scene and Synfig's stickman plugin) versus Synfig's **Skeleton layer + bones** (bone
   influence, Skeleton Deformation for bending). The agent recommends one in DECISIONS.md with
   evidence from both files. It is the biggest input to Step 2's `build_rig`.
3. **Review `docs/learning/synfig-format.md`** before the generator is built on top of it.

## Tasks

### 1.0 Owner: install the GUI
Open the DMG, drag Synfig Studio to Applications, approve it in Privacy & Security. Then
`uv run scripts/doctor.py` shows `synfig_studio` as OK instead of DEFER. Remove the `deferred`
entry from `config/studio.toml`.

### 1.1 Owner: build a ~10 s scene by hand
Save it uncompressed (`.sif`, not `.sifz`) as `tests/fixtures/handmade/scene.sif`, with its images
next to it (small PNGs only). The scene contains:

| Element | How (Synfig Studio) | What it teaches us |
|---|---|---|
| Canvas 1920×1080, 24 fps, 10 s | Canvas → Properties | Canvas, units, time |
| A background image moving slowly left | Import Image, then animate the group offset | Import layers, waypoints on vectors |
| A simple puppet: torso + 2-segment arm (upper arm, forearm) from PNG parts | Import 3 PNGs. Rig them **both ways**, in two copies of the file: (a) nested groups with pivots, (b) a Skeleton layer with bones | The rig-technique decision |
| A wave: 2+ waypoints on the arm rotation | Animation mode, rotate at two times | Angle waypoints, interpolation |
| A mouth on a **Switch layer** with 3 shapes (e.g. A, E, X) that changes over time | Switch Group, animate "Active Layer Name" | How Rhubarb cues will drive mouths |
| An ease-in/out vs linear difference | Change interpolation on one waypoint | Interpolation names in XML |

Any placeholder art is fine (flat shapes exported as PNG). Render it once from the GUI to check.

### 1.2 Agent: reverse-document the format → `docs/learning/synfig-format.md`
From the owner's files (ours, so this is fine under D-005), document:
- canvas attributes (`view-box`, units vs pixels, `fps`, `begin-time`/`end-time`)
- layer types used, with their required params and defaults (`synfig --layer-info=<type>`)
- groups and the transformation composite; pivots
- bones: `skeleton` layer, `bone` valuenodes, how a part is bound to a bone, skeleton deformation
- waypoints: `animated` nodes, time formats, interpolation names, tangents/TCB
- switch layers: `layer_name` animation, how to drive it from a cue list
- image import: paths (relative to the `.sif`), `tl`/`br`, resampling
- exported values and `<defs>`, `guid` attributes: which ones are required for the CLI
- what the GUI writes that the CLI does not need (so the generator can stay minimal)

Include a minimal working example per concept, each rendered with the CLI as proof.

### 1.3 Agent: a minimal `.sif` builder in `studio_core/sif/`
- A small typed Python API (dataclasses → XML with the standard library's `xml.etree`), e.g.
  `Canvas`, `ImportLayer`, `Group(transform=..., children=...)`, `SwitchGroup`, `Animated(waypoints)`.
- Deterministic output: same input, byte-identical XML (stable ordering, fixed float formatting).
- Units handled in one place: pixels ↔ Synfig units, seconds ↔ frames.
- **Rules in code:** timing math and frame counts are unit-tested (CLAUDE.md).
- No GUI-only cruft. Every element the builder writes must be one the CLI needs.

### 1.4 Agent: tests
- Unit tests for units/time conversion and waypoint generation.
- Golden-file tests: the builder reproduces small reference `.sif` snippets.
- Render tests (marked slow): the CLI renders builder output without errors, and frames differ
  where the animation says they should (e.g. the arm's bounding box moves between frame 0 and the
  wave peak).

### 1.5 Agent: demo script → MP4
`scripts/sif_demo.py` builds a ~5–10 s scene from scratch with the builder: a moving background,
a waving puppet made of PNG parts (reuse the owner's parts), and a mouth switch layer driven by a
placeholder cue list in Rhubarb's JSON format (`tests/fixtures/` holds a real Rhubarb output from
Step 0). It then renders PNGs with the CLI, encodes with ffmpeg, and checks the MP4 with ffprobe.

### 1.6 Docs
- DECISIONS.md: the rig technique (checkpoint 2), the builder's design.
- PROGRESS.md, and the Step 2 brief draft (`docs/steps/STEP-2-synfig-mcp.md`).

## Done when

- [ ] The owner's hand-made scene (both rig variants) is committed as a fixture and renders with the CLI
- [ ] `docs/learning/synfig-format.md` covers every element in the 1.2 list, each with a rendered example
- [ ] The rig technique is decided and recorded in DECISIONS.md
- [ ] `studio_core/sif/` builds a scene from scratch; unit, golden-file and render tests pass
- [ ] `uv run scripts/sif_demo.py` produces a correct MP4: a waving puppet, a moving background, a
      mouth switching on cue
- [ ] PROGRESS.md updated, Step 2 brief drafted, work committed in small commits
