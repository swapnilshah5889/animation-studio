# The motion library: named, parameterized motions

How "Pip waves" in a shot spec becomes keyframes on bones (`studio_core/motions/`). The LLM picks
*what* (a motion name, a start time, a few parameters); code decides *how* (frames, angles,
easing). That's CLAUDE.md's "rules in code".

## From action to keyframes

```
shot.json action            {"motion": "wave", "start_s": 1.0, "params": {"side": "left", "energy": 0.7}}
      │  MOTIONS["wave"](MotionContext)            ← pure function, unit-tested
      ▼
Clip: keys on channels      ("angle", "upper_arm_l"): [(24, 0°), (33, 148°), …, (78, 0°)]
      │  compose(clips)                            ← overrides + additive layers
      ▼
per-bone tracks             angles / shifts / eyes  → build_character(...) → .sif bones
```

Three kinds of channel:
- **angle** (degrees from the rest pose) rotates a bone.
- **shift** (pixels) moves a joint: a nod lowers the head, a jump moves the whole body via the
  root.
- **eyes** (open/half/closed) drives the face's eye switch, for blinks.

## Parameters

| Parameter | Meaning |
|---|---|
| `energy` 0–1 | amplitude and a little speed. A 0.0 wave is a polite hand lift; a 1.0 wave is big and fast. |
| `side` | the character's left/right; the library flips rotation signs so mirrored limbs move correctly |
| `cycles` | repetitions (wave swings, steps, nods, beats); otherwise derived from `duration_s`, otherwise a default |
| `target` | a frame position for `point` (aimed with forward kinematics from the shoulder) |
| `duration_s` | hold length for tilts and points; repetitions for cyclic motions; end time for idle/blink |

## Composition (D-028)

- **Override:** a later motion owns a bone for its window. If Pip is waving and then starts
  pointing with the same arm, the point wins from its start.
- **Additive:** idle motions (breathing) are summed on top of whatever else is happening, so a
  waving character still breathes.
- Every motion starts and ends at the rest pose, so motions chain without jumps.
- Joint limits (`limits_deg`) clamp the final angles. An LLM asking for an impossible head angle
  gets the nearest allowed one.

## Animation principles in code

- **Ease in/out at reversals** (`halt`): a waving forearm stops for an instant at each end of the
  swing, like a pendulum. Linear motion between extremes looks robotic.
- **Overlap:** the upper arm raises first and the forearm starts waving once it's up.
- **Anticipation and squash** in `jump`: crouch before the leap, a small squash on landing.
- **Repeatable "randomness":** blinks come at irregular intervals, but the irregularity comes from
  a hash of the character and start time. The same shot always renders the same, which keeps
  evals and tests stable.

## Front-view limits (honest notes)

A front-view cut-out can only rotate parts in the picture plane. So:
- **nod** is a small downward bob of the head (a shift), not a pitch.
- **walk_cycle** is a march in place: legs lift in turn (a joint shift) while the body bobs.
  Swinging legs sideways read as stumbling. A real walk across the frame needs side or
  three-quarter view art (Step 4) and moving the character's placement in the scene (task 2.6).
- `talk_gesture` and `point` raise arms sideways, because that's the only direction a front-view
  arm can move.

## Review

`uv run scripts/preview_motions.py [--energy 1]` renders every motion as a labelled cell in a 3×3
video (`~/ai-studio/scratch/motion-preview/`), using exactly the code path `synfig_mcp` uses.
