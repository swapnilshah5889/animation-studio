# Blender foundations bake-off (2026-10-31)

Why: the owner judged the round-3 flat Mia "very very bad" (head, hands and every action fake). The flat-part rig only has a
front view, so turns and side walks are cheats. This spike compares three ways of building the character in Blender on the
same 3 s test (walk left to right in side view, stop and turn to the camera, wave with fingers visible, tilt of the head).
Video: `~/ai-studio/scratch/blender-compare/compare.mp4` (A is the first 3 s of `clip_v3`, a different action: a walk-in and a wave
in front view; B and C are the same test). Per-candidate notes: `grease-pencil/notes.md`, `toon-3d/notes.md` in that folder.

| | A flat parts on planes (now) | B Grease Pencil strokes + armature | C procedural 3D, cel shading + outline |
|---|---|---|---|
| Strictly 2D | yes | yes | **no** (needs 2.5D approval, AGENTS.md) |
| Real turn / side walk | no (squash-slide cheat, front view only) | swap between four per-view rigs (90, 60, 30, 0 deg), body swaps may pop (not checked by eye) | yes, one rig turns in 3D |
| Hands | mittens | crude | thumb plus four fingers, spread in the wave |
| Build effort | 3 rounds | about 55 min | about 20 min |
| Render | about 0.1 s/frame | 0.08 s/frame | 0.37 s/frame |
| Agent's own score (1-10, unverified by eye) | owner: very bad | 5 | 6 |
| Main weakness | stiff paper doll | helmet hair in side view, rigid body, no follow-through | looks like a 3D toy with an outline; side-view face nearly invisible; sphere elbows and knees |

Honest caveats: both candidates were built by sub-agents that did not review their own clip frame by frame (B viewed 3 stills made
before its last tweaks and never its clip or sheet; C reports 0 px foot drift from code, not from pixels). The scores are theirs,
not an independent review. No separate reviewer was run, to save usage; the owner judges by eye.

Findings worth keeping: a Grease Pencil filled stroke (Blender 5.x, GPv3) renders only if its `fill_id` is greater than 0. Everything
is procedural and local (Blender, EEVEE and the armature modifier are GPL; no downloads). Both scripts are parametric (colours,
head size) so a director could change a design.

Not decided here: the foundation. Option C is the only one with real turns and hands but breaks the strict-2D rule; B stays 2D
but needs a drawing per view. See PROGRESS for the open question to the owner.

Code: `scripts/spikes/blender_gp/blender_gp_mia.py`, `scripts/spikes/blender_toon3d/mia_toon3d.py`.

Owner verdict after watching: **A is the worst of the three** (D-099). B versus C is still open.
