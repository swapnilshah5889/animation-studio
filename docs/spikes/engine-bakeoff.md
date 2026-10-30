# Spike: engine bake-off (Blender, OpenToonz, Synfig)

**Question.** Which engine gives the best lifelike 2D puppet result and can be driven entirely by code
(D-030 engine-neutral data in, frames out), on the M4 Mac?

**Date:** 2026-10-30. **Time:** about 2.5 h. **Outputs** (outside the repo, `~/ai-studio/scratch/engine-bakeoff/`):
`compare.mp4` (2x2, labelled, 1920x1080, 8 s, with the line audio), `look.md`, `metrics.json`, `bend.json`,
`bend_sheet.png`, the bakes and the generated OpenToonz projects. **Code:** `studio_core/engines/`
(`bake.py`, `limbs.py`, `face_sprite.py`, `blender/`, `opentoonz/`, `synfig/`) and
`scripts/spikes/bakeoff_*.py`. No existing production path was changed, no schema got an engine field.

## What was built

One **bake** feeds every engine (`engines/bake.py`): the shot spec + film folder go through the same
placement and motion code Synfig uses, and out comes JSON with, per frame, every bone's joint position and
world direction (stage pixels, y up), the eye state and the mouth cue. Parts, bones and draw order come from
the rig. Limbs are bent from **one image per limb** (`engines/limbs.py` pastes the two cut parts into one rest
pose image and writes `bendable_limbs`, the field that already exists in `rig.schema.json`); a cheap PIL face
(`face_sprite.py`) stands in for the vector face on engines that move pixels.

- **Blender 5.2.3** (`blender --background --python`): an armature with the rig's bones, an orthographic camera,
  emission-only textured meshes (unlit, so the colours are the art's colours), one mesh per limb with
  smoothstep bone weights across the joint, rigid parts as quads, paint order = a 0.01-unit Z step (not
  perspective: the camera is orthographic, nothing has depth). Poses are applied as exact bone matrices from the
  bake. Strictly 2D.
- **OpenToonz 1.8.0**: a generated project (`.tnz`, levels, PNGs): every part a column on a pegbar with one
  linear keyframe per frame (x, y, rotation about the joint); every limb a texture column parented to a
  **mesh column** carrying a Plastic skeleton (shoulder, elbow, wrist) with the bend as the per-frame Angle of the
  wrist vertex. Meshes come from our own clipped-grid mesher (`opentoonz/mesh.py`). Head variants (mouths, blinks)
  are drawings of one level swapped per frame. Rendered with `tcomposer`.
- **Synfig 1.5.5**: the production path (`render_shot`), bendable limbs on (Skeleton Deformation) from the same
  limb images, and rigid (today's two-part limbs).

Benchmark: shot A (5 s, Kit, `walk_real` then `wave_real` then `jump_real`, orchard plate), shot B (3 s, Mia,
`talk_gesture`, line `l002` "Let's send it back to the sky!" with its Rhubarb cues, blinks, a 14 degree head
turn, camera zoom 1.7). 24 fps, rendered at 960x540. Mia is the `child` puppet of `films/step4-cast`.

## Gate 1: automation (from our JSON and parts, headless, deterministic)

| | Synfig (baseline) | Blender | OpenToonz |
|---|---|---|---|
| Builds the scene from our data | yes (production) | yes | yes |
| Applies the clips (same bake) | yes | yes | yes |
| Renders headless on this Mac | yes, CPU, arm64 | **yes, all three render engines, no display needed** (Workbench, EEVEE on Metal, Cycles CPU) | yes, but Intel build under Rosetta, single-thread only (below) |
| Re-run gives the same frames | **yes** (pixel hash) | **yes** (pixel hash; PNG bytes differ, a header changes) | **yes** (pixel hash, single-thread) |
| New glue code (lines) | 0 (production) + 2 (package) | about 360 (`blender/` 354) | about 400 (`opentoonz/` 406) |
| Shared glue (bake, limbs, face) | | 392 | 392 |
| Plugins / add-ons | none | **none** (no COA Tools) | none |
| Source changes | none | **none** | **none** |
| Which level | 1 | 1 (the app's own Python API in `--background`) | 1 (files + CLI) |
| Peak memory (child max RSS) | 265 MB | 350 to 460 MB | 200 to 335 MB |
| Scene build time | n/a | 0.11 s | 0.02 s |

**Pass for all three.** What broke or needed care:

- **OpenToonz multi-thread rendering is unsafe on this build.** With `-nthreads 4`, 3 of 5 plastic renders
  lost frames (103 of 120, 8 of 72, 0 of 120): SIGABRT in `malloc_zone_error` and SIGSEGV in
  `QOpenGLContext` teardown on worker threads (crash reports in `~/Library/Logs/DiagnosticReports`), plus
  the known SIGSEGV at exit. With `-nthreads 1`: 10 of 10 renders complete. A wrapper must pass
  `-nthreads 1`, count the frames on disk, and ignore the exit code. A fix would be an arm64 build (none is
  published; the Homebrew cask is disabled for being unsigned) or building OpenToonz from source for arm64
  (level 3, not tried). A Windows node would not need Rosetta.
- **OpenToonz format knowledge is the cost:** the `.tnz` is undocumented; this worked because the earlier spike
  had read the source. Skeleton vertices on a mesh edge are silently ignored (offset by 0.37 px); the Plastic bend
  sign is the wrist's Angle (+1; -1 doubled the error, measured).
- **Blender:** the bundled Python has no Pillow (sizes come from the bake); `film_transparent` off and an
  explicit background plane keep the composite identical to the others. First EEVEE frame costs 3.8 s of shader
  compile in a fresh process, the rest 0.15 s.
- **Synfig:** nothing broke. Bendable limbs needed only the limb images (they come from `engines/limbs.py`);
  the renderer treats them like any other layer.

### Time per frame (960x540, 24 fps; shot A = 120 frames, shot B = 72, whole process)

| Engine | Shot A total | s/frame | Shot B total | s/frame |
|---|---|---|---|---|
| Blender Workbench | 3.8 s | 0.03 | 2.2 s | 0.03 |
| Blender EEVEE | 17.3 s | 0.14 | 11.5 s | 0.16 |
| Blender Cycles (CPU, 8 samples, flat) | 27.9 s | 0.23 | 20.7 s | 0.29 |
| Synfig (rigid or bendable: same) | 17.6 s | 0.15 | 11.2 s | 0.16 |
| OpenToonz rigid (1 thread) | 19.5 s | 0.16 | 13.0 s | 0.18 |
| OpenToonz Plastic (1 thread) | 62 to 97 s | 0.52 to 0.81 | 15 to 22.5 s | 0.21 to 0.31 |

OpenToonz Plastic is the slowest by 3x to 5x and varied between identical runs. (1080p was not timed; the pixel
count is 4x.) Cycles was chosen as the clean reference: with 8 samples it differs from a 128-sample
render by 0.2 grey levels on average (8 pixels over 24 levels), against 0.7 (EEVEE) and 0.9 (Workbench) with
about 1000 pixels over 24 levels (edge fringes). Workbench is the right fast preview.

## Gate 2: the look (numbers; the owner judges by eye in `compare.mp4`)

The motion numbers are the same for every engine (one bake), measured on shot A: planted-foot slide 0.041 leg
lengths per contact (6 contacts; worst 0.158 at the start of the walk), largest knee bend 64 degrees (the clips
are eased to the rig's limits), joint-angle jerk 10.7 deg/frame^3, peak acceleration 92 deg/frame^2. These are
properties of the clips, not of the engine.

**Holes, seams, detached pieces** (the pose-sweep checker on the magenta probe, every frame):

| Shot A (Kit), 120 frames | frames with a defect | holes | seams | detached |
|---|---|---|---|---|
| Synfig rigid | 56 | 36 | 60 | 0 |
| Synfig bendable | 50 | 49 | 40 | 0 |
| Blender rigid (Workbench) | 53 | 36 | 48 | 1 |
| Blender bend, Workbench | 48 | 28 | 53 | 0 |
| Blender bend, Cycles | 49 | 29 | 70 | 0 |
| OpenToonz rigid | 63 | 35 | 74 | 0 |
| OpenToonz Plastic | 43 | 56 | 32 | 0 |

Shot B (Mia): 42 to 54 frames of 72 have a defect in every engine, with 24 holes in Synfig, OpenToonz and Blender
Cycles and EEVEE (4 with Workbench, whose alpha edge is harder): they are in the art (gaps in the hair), present
in the straight pose. **Read
this table as "the art, not the engine".** Blender Workbench vs Cycles, the same geometry, differs by 17 seams, so
the counts carry about that much noise (thin slivers at anti-aliased edges). The largest defect is 340 to 390 px at
960x540 in every engine and in the rigid ones too (at the hips).

**The bend sweep (the question the table above could not answer):** Kit stands on the probe backdrop and the
right knee is bent 0 to 120 degrees and the right elbow 0 to 140 (`bakeoff_bend.py`), counting new holes and seams
against the straight pose:

| | rigid (Synfig, Blender, OpenToonz) | Synfig bendable | Blender bend | OpenToonz Plastic |
|---|---|---|---|---|
| New holes or seams, knee at 120 degrees | 0 | 0 (clamped at 60 by the rig) | 1 seam | 1 seam |
| New holes or seams, elbow at 140 degrees | 1 seam | 1 seam | 1 hole | 1 hole |
| Figure area, knee at 60 / 120 (straight = 1) | 0.967 / 0.989 | 0.963 / 0.963 | 0.964 / 0.981 | 0.966 / 0.983 |

So with limbs drawn as one continuous image **no engine opens a real hole at any bend inside the limits**: at
most one small sliver (a seam or a hole) appears. The deforming engines show their first new sliver at 10 to 20
degrees of knee bend (Blender 10, Synfig bendable and OpenToonz Plastic 20) and at 10 degrees of elbow (all
engines, rigid too); the rigid draw has none at the knee in this sweep. The area stays within 4 per cent of the
straight pose everywhere. The old finding (knee bends past 35 degrees open holes up to 340 px,
`real-motion.md`) was a property of the two-part cut with caps: a limb image that already includes the overlap
does not have it, even drawn rigid. What the engines differ in is how the bend is shaped (a smooth curve against a
hinge), which a count cannot see. `bend_sheet.png` shows a crop per engine at straight, knee 60, knee 120 and
elbow 140 so the owner can judge it.

What I looked at myself (three images, the allowed maximum): one wave frame of shot A for the three Blender
render engines and Synfig, one Mia speech frame for the same four, and a crop of Blender, OpenToonz and Synfig
side by side. I did not look at the bend sweep. The poses agree to 0.6
grey levels mean (OpenToonz vs Blender, shot A frame 60; 479 pixels over 40 levels, all along the waving arm:
the two deformers shape the same bend differently). Mia's face in Blender and OpenToonz is the PIL stand-in
(plain, a bit large at first, resized): not a quality comparison with Synfig's vector face.

## Recommendation

1. **Blender is the puppet engine to build on.** It passes Gate 1 with the least glue and the best properties:
   native arm64, no add-on, no source change, three working headless render engines, deterministic, fastest
   (0.03 s/frame preview, 0.23 s/frame Cycles), a rich Python API we only scratched (shape keys, drivers,
   physics for hair and cloth, bone scale for squash and stretch is native but not demonstrated here),
   and the bake has already let it play the exact clips. Strictly 2D by construction. GPL does not touch our
   renders.
2. **OpenToonz also clears Gate 1, as the second engine for drawn work, not for puppets.** It builds from our
   data, renders headless and deterministically (single thread), and its Plastic bend looks the same as
   Blender's on the benchmark (0.6 grey levels mean difference; both bend smoothly, neither opens a hole). On
   puppets it gives nothing Blender does not, and costs more: 3x to 5x slower, Intel-only under Rosetta, unsafe
   above one thread, an undocumented file format. Its unique strengths (BSD-3 licence, xsheet and frame-by-frame
   tools, the multiplane camera, a render farm) were **not** benchmarked here, because no hand-drawn frames exist
   yet. So the pairing "Blender for rigged puppets, OpenToonz for drawn hero shots" is worth its hand-off only
   once there is a drawn-shot job to test; the next OpenToonz task should be a drawn-frames shot (image
   sequence on twos, xsheet timing) plus an arm64 or Windows-node render check. Until then Blender alone covers
   the benchmark.
3. **Synfig is only the reference** (rigid and bendable runs, both with the same limb images; no tuning was done).
   Whether the candidates bend more smoothly than its rigid limbs is for the owner's eye (numbers cannot show it); Blender beats it on speed
   (0.03 to 0.23 against 0.15 s/frame) and on automation surface; its bendable limbs render fine but are not worth
   more investment if it is being replaced.
4. The engine is only half the lifelike gap. The clips are still eased to the rig's limits (knee 64 degrees in
   shot A); the sweep shows a 120 degree knee and a 140 degree elbow render cleanly, so widening the limits for
   the real clips is the next gain, and it is independent of the engine.

## Open questions

- The face: Synfig draws it as vectors; Blender needs a pixel face (this PIL one is a stand-in) or a curve/mesh
  face. Which does the owner want (a rasterised version of the vector face is the least work)?
- Soft secondary motion and squash/stretch, the things that make mocap look alive, were not demonstrated; the
  Blender follow-up should do a jump with squash and a scarf or tail on bones.
- Hair gaps (24 holes in Mia's straight pose) are an art-build defect worth fixing at the source.
- Pose sweeps measured the same two characters only; Pim, Bolt, Bo were not run.
