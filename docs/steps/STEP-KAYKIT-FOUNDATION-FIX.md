# KayKit foundation fix pass

**Status:** APPROVED by the owner 2026-11-03 with hand route **A** (one authored open-mitten hand).
**Result (2026-11-03):** ran once; independent **NEEDS WORK** (2 look majors). Stopped per the stop rules; see
`docs/PROGRESS.md`.
**Decision:** D-108 (owner, 2026-11-03): adopt the KayKit rig-and-action route as the foundation candidate.
**Roles:** Foundation Fixer (one session), then an Independent Animation Reviewer (a different agent).
**Time box:** one working session. Stop early under the stop rules below.

## Goal

Fix the three majors from the 2026-11-03 independent review of
`~/ai-studio/scratch/character-foundation-test/render/foundation_test.mp4` (report: `render/review.md`). Re-render the
same 5.5 s, 1080p24 test so it passes review with no blockers and no majors. Keep the same character (KayKit Rogue),
the same rig (`Rig_Medium`), the same actions, the same staging and the same structure: walk, stop, wave, head turn.
This is a repair pass, not a new candidate.

## The three majors and the planned fix for each

### 1. Walk-to-stop foot pop (f50-55)

**Cause:** the NLA blend from `Walking_A` to `Idle_A` begins mid-stride. Linear blending of the leg rotations crosses
the legs, then they snap to idle.

**Fix (deterministic, in code):**
- Choose the walk exit frame automatically: the cycle frame whose foot positions (rig-local) are closest to `Idle_A`'s
  stance, with one foot planted.
- End the walk strip there and blend into idle over 6 to 8 frames.
- Keep the existing planted-foot lock running through the blend.
- Do not key leg bones by hand.

**Check, before review:**
- The left-right foot separation never drops below the idle stance's separation minus 10 percent during the walk and
  the stop.
- A feet-crop `motion.csv` over f35-70 shows no spike above 3x its median.
- The planted-foot drift stays at or below 0.007 u per frame.

### 2. Fist hand: the wave reads as fist-shaking

**Cause:** KayKit's hands are fingerless mitten fists, modelled into `Rogue_ArmLeft` and `Rogue_ArmRight`. The rig has
no finger bones. Timing or pose changes cannot open the hand.

**Decision for the owner (one choice; recommendation first):**
- **A (recommended): one authored open-mitten hand.**
  - Hand-model a simple low-poly open hand in Blender for the waving (right) hand: a flat palm, a separate thumb, and
    fingers as one mitten shape. It must match KayKit's polygon language, palette and texture atlas.
  - Weight it 100% to `hand.r`. Hide the fist geometry with a mask modifier driven by a vertex group, on a scratch
    copy of the asset; the source files stay untouched.
  - This is art authoring on a CC0 asset, which the license allows. It is not animation faking: the hand is rigid on
    its bone.
  - Review four stills first (rest, raise, wave peak, lower), then build the clip. A KayKit-style left hand is out of
    scope.
- **B: accept mitten hands as the style.**
  - Keep the fist, and turn the wrist so the hand's flat side faces the camera during the wave.
  - Tell the reviewer the mitten hand is on-model.
  - This is cheaper, but likely still to read as a fist.

### 3. Reads as a cel-shaded 3D game asset, not drawn 2D

**Causes:**
- Freestyle draws crease lines along low-poly edges inside the hair.
- Flat-faceted normals split the face's shading into polygon patches.
- The cast shadow is soft-edged.

**Fix:** one look pass, settings only:
- **Normals:** set the meshes to smooth shading with smooth-by-angle. On the head, transfer normals from a fitted
  sphere (a Data Transfer modifier with custom normals; a standard toon-shading technique), so the face takes one
  clean light/shadow shape.
- **Lines:** draw silhouettes, outer contours and material boundaries only; turn crease lines off. Taper line
  thickness along each stroke, from about 1.5 to 3 px. Use the same dark warm ink colour as now.
- **Shadow:** make the sun's shadow hard (angle under 1 degree), so the cast shadow is one flat toon shape.
- **Optional, owner's call:** hold the character's poses on twos (keep the camera on ones). Default is off.

**Order:** compare these settings on three stills (walk, wave peak, head turn) before the clip render.

## Minors in scope only if they are one-line changes

- Feet margin: lift the camera target so the boots keep at least 8 percent margin at the end.
- Out of scope: elbow bend (the `Waving` action is the asset's), stride length, the painted background.

## Code location

Move the scratch build script into the repo as `scripts/spikes/kaykit_foundation_test.py`, with type hints and a
docstring. It must stay safe to re-run, and asset and output paths are passed as arguments. Assets, `.blend` files,
renders and evidence stay under `~/ai-studio/scratch/character-foundation-test/` and are never committed. Do not touch
Rowan, `scripts/spikes/rowan_rig_*.py`, `scripts/run_first_shot.py`, `.claude/` or `.codex/`.

## Done when

1. All three checks under "Walk-to-stop" pass and are recorded with their numbers.
2. The hand route the owner chose passes its four-still check (the Fixer's own check), and then the clip.
3. The look stills, then the clip, show no crease lines inside the hair, a clean single shadow shape on the face, and
   a hard cast shadow.
4. A fresh **Independent Animation Reviewer** reviews the re-rendered clip with `skills/animation-review/README.md`
   against `Samples/rogue.png`. They must explicitly assess the stop transition, the hand, 2D/2.5D readability, and
   the earlier good points: the head turn, arm attachment and foot contact. The pass requires no blockers and no
   majors.
5. The owner watches the clip and says it passes. A pass here is a foundation test, not production readiness.

## Stop rules

- If the hand fails its four-still check once, stop and report. Do not try a second hand design.
- If the walk-to-stop check fails after the exit-frame selection, stop and report. Do not hand-key legs.
- If the review still finds a major after this one pass, stop and report the findings. Do not iterate.
- No downloads, installs, new assets, or new characters.
- No more than one subagent at a time.
