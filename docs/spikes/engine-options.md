# Animation engine options (research, 2026-10-30)

Why: the real-motion spike (see `real-motion.md`) showed the engine, not the motion data, caps how lifelike
the puppets look (rigid two-piece limbs). Before building more on Synfig we compare engines on one benchmark
shot. This page lists what exists. "Verified" = seen in a source this session; "from memory" = my own
knowledge, check before relying on it.

## Requirements for a candidate
Runs offline on the Mac (M4, 24 GB) and later on Windows/Linux; scriptable or headless (the director drives it
by code); open licence, output free to use; real deformation (bend limbs, squash) not just rigid parts; fits the
engine-neutral scene model (D-030).

## Puppet / cut-out engines (mesh deformation)
| Option | Licence | Deformation | Automation | Notes |
|---|---|---|---|---|
| Synfig + Skeleton Deformation (current, opt-in) | GPL-3 | yes, per limb (D-069) | CLI render, `.sif` files | Baseline. Already wired. |
| Own mesh-skinning renderer (Python, offscreen GL or Skia) | ours | full (linear blend skinning, shape keys, squash) | total, headless | From memory/idea. We already have parts, bones, motions as engine-neutral data. Cost: we write and own the renderer. Cheapest to test. |
| Godot 4 (2D: Skeleton2D, Polygon2D, movie-maker `--write-movie`) | MIT | yes | scripted, offline movie export | From memory. Needs a GPU context, fine on Mac. Game engine, so timeline editing is ours. |
| Blender (+ COA Tools 2, armature + mesh deform, `blender --background --python`) | GPL | yes, rich | strong Python | Verified: command pattern. Verified (old forum): EEVEE headless needed a display; Cycles is safe. Check current docs on macOS. COA Tools 2 verified to exist. |
| Inochi2D / Inochi Creator | BSD-2 | yes, physics too | SDK; needs OpenGL 3.2 context; headless unverified | Verified: licence, mesh warp, physics. Made for live VTubing. Runtime in D. |
| AnimeEffects | GPL-3 | yes (polygon mesh) | GUI; no CLI found | Verified: licence, Mac support. Probably GUI-bound. |
| DragonBones | open source | yes (free-form) | runtimes | Verified listing only; project looks stagnant. |
| Spine, Live2D, Rive, Moho | proprietary | | | Excluded (open-source-first rule). |

## Frame-by-frame (hand-drawn style)
OpenToonz (BSD-3, D-031), Krita (GPL), Pencil2D (GPL). All GUI-centred. The real cost is the drawings
(one AI image per frame, roughly 180 per 15 s shot per character, plus consistency retries), not the app.

## AI motion generation (against D-064 unless used for hero shots only)
- Wan 2.2 (5B fits 24 GB per the sources; mature ComfyUI workflows) and LTX-2 (heavier; FP8 does not work on
  Metal, GGUF or an MLX port needed). Verified single report: 82 min for a 2 s clip with GGUF Wan 2.2 on an M1 Max
  64 GB. No source found for cartoon character consistency.
- ToonCrafter (two keyframes to 16 frames, 512x320, about 2 s, 8 fps). Licence statements conflict (model card
  header says bigscience-openrail-m, text says Apache-2.0, one site says non-commercial). Do not use before
  reading its LICENSE.
- Verdict: too slow, too low-resolution and too uncontrollable on this machine for the main pipeline.

## Editing and assembly (already chosen)
MLT / melt (edit_mcp), Kdenlive project export (untested).

## Suggested bake-off shortlist
Benchmark: Kit walk-in, wave, jump (5 s, mocap clips) + one Mia talking close-up. Score by eye (owner), plus
automation effort, render time, defects.
Owner view (2026-10-30): OpenToonz plus Blender is the preferred industry-standard combination, so both stay in
the bake-off as first-class candidates (installs approved).
1. Blender armature + mesh deform (and Grease Pencil for hand-drawn shots)
2. OpenToonz (cut-out with its mesh/plastic tool, and frame-by-frame for hero shots)
3. Synfig + bendable limbs (baseline)
4. Own mesh-skinning renderer (cheapest, most control; the fallback if the apps resist automation)
5. Godot 4 2D, Inochi2D only if offscreen rendering works.
The main risk for 1 and 2 is automation, not looks: both are GUI-first. The bake-off must show that code can
build the scene, animate it and render headless on the Mac before we judge the picture.

Sources: [Synfig overview](https://us.fitgap.com/products/009157/synfig-studio),
[COA Tools 2](https://github.com/Aodaruma/coa_tools2), [Inochi Creator](https://linuxlinks.com/inochi-creator-create-edit-inochi2d-puppets),
[AnimeEffects](https://www.github.com/p-yukusai/AnimeEffects), [Spine alternatives](https://alternativeto.net/software/spine),
[Wan 2.2 and LTX-2 on Mac](https://lilting.ch/en/articles/ltx2-wan22-mac-local-video-gen),
[ToonCrafter](https://github.com/ToonCrafter/ToonCrafter), [Blender EEVEE headless thread](https://devtalk.blender.org/t/blender-2-8-unable-to-open-a-display-by-the-rendering-on-the-background-eevee/1436).
