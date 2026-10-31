# Step SLICE: one 30-second vertical slice (draft, for owner approval)

Status: **draft, waiting for the owner's approval.** Decisions: D-101 (reset), D-102 (stylised 3D characters).
Nothing else is active until this passes (ROADMAP "Reset").

## Target look

The owner's references (2026-10-31), described here without names:
1. A lush, painted forest clearing with soft warm light, glow and light rays; one character sits on a mossy rock
   and only breathes and blinks. Quality comes from painting, light and atmosphere, not from complex motion.
2. A stylised 3D feature teaser: rounded, appealing characters with expressive faces, painterly lighting, depth
   of field, rich environments.

Our target is a short, well-lit, cinematic children's scene in that spirit. It is not feature-film quality: no
crowds, cloth or hair simulation, or complex acting.

## Cast and tools

- **Rain** (64 MB) and **Snow** (106 MB): free Blender Studio rigs, CC-BY 4.0, for Blender 4.1 and later, no
  add-ons. Both have IK/FK limbs and layered face controls with shape-key correctives. Credit lines:
  "Rain Rig (CC) Blender Foundation | studio.blender.org" and "Snow Rig (CC) Blender Foundation | studio.blender.org".
  Check both on Blender 5.2.3 and by eye for a children's film before building on them. If a download needs a
  sign-in, the owner downloads it (agents never sign in).
- **Blender 5.2.3**, headless, EEVEE, which is the fast choice. Use Cycles only if EEVEE cannot give soft light.
- **Backgrounds:** painted plates from `comfy_mcp`, which we already have (unload Ollama first), placed as
  layered planes in depth.
- **Motion:** CMU mocap retargeted onto the rig for the walk. Wave, idle, blink and talk come from small code
  keyframe helpers. Mouth shapes come from Rhubarb cues (`audio_mcp`) mapped to the rig's mouth controls.
- **Voices and music:** `audio_mcp` (Kokoro voices, ACE-Step music, the CC0 sound library).
- **Reused rules:** `framing.py` (head and foot room), the speed and pop checks in `motions/smooth.py`, and the
  review skill. A shot spec stays engine-neutral where that is cheap. Generalising the scene model for 3D is
  decided after the slice (D-102).

## The film (about 30 s, 24 fps, 1080p)

| Shot | Time | What happens | Camera |
|---|---|---|---|
| 1 | 0 to 8 s | A painted meadow at the forest edge, golden hour. Rain walks in from the left, about five steps, and stops. | Wide, slow dolly in, light rays |
| 2 | 8 to 14 s | Rain spots Snow off-screen, smiles and waves. Reverse shot: Snow waves back. | Medium, then reverse medium |
| 3 | 14 to 24 s | Rain: "Want to see the fireflies?" Snow: "Yes! Let's go!" Lip-sync, blinks and small gestures. | Over-the-shoulder close-ups, soft depth of field |
| 4 | 24 to 30 s | Both turn and walk towards the trees; fireflies (glowing particles) appear. Music swells, then fades. | Wide, gentle crane up |

## Tasks (one session at a time, each with a time box)

1. **Rig check (30 min):** download, open Rain and Snow in Blender 5.2.3 headless, render a turntable and a
   face-shape sheet, list the controls (body, face, mouth). Record the licence and size in `docs/MODELS.md`.
   Stop and report if a rig fails on 5.2.
2. **Look test (60 min):** one still of shot 1, with a painted background, soft key and rim light, glow, depth
   of field and the painterly character shading. Show it to the owner. The look is approved before any
   animation.
3. **Motion (90 min):** the walk (retargeted mocap, feet planted, no slide), wave, idle, blink, and lip-sync on
   the face controls. Unit tests for foot slide, framing and the cue-to-mouth timing (±1 frame).
4. **Assembly (60 min):** four shots, voices, music, sound, cuts, final encode; credits with the CC-BY lines.
5. **Review:** `skills/animation-review` with an independent reviewer, then fixes. Then the owner watches it.

## Done when

1. The owner approved this brief and the look still (task 2).
2. The 30 s film passes the independent review with no blocker and no major.
3. The owner watches it and says it passes.
4. Docs are updated (PROGRESS, DECISIONS, `docs/MODELS.md`, a `docs/learning/` note on rig retargeting), and
   everything is committed and pushed, with renders kept outside the repo.

## Risks

- A rig may not load cleanly in Blender 5.2: task 1 checks it first.
- CMU retargeting onto a custom rig needs a bone map. Fallback: a code-keyed walk cycle.
- The rigs may have no mouth shapes for visemes. Fallback: drive the jaw and lip controls.
- EEVEE headless on macOS (Metal) has to be checked in task 1.
