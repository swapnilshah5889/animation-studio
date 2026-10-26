# The motion library: named, parameterized motions

How "Pip waves" in a shot spec becomes keyframes on bones (`studio_core/motions/`). The LLM picks
*what* (a motion name, a start time, a few parameters); code decides *how* (frames, angles,
easing). That's AGENTS.md's "rules in code".

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

## Keyframes and curves

Animation software stores **keys** (a value at a frame) and a **curve** that decides how the value
travels between keys. Our clips are exactly that: `Key(frame, value, interp)`. The interpolation
names map to Synfig's own waypoint types (see synfig-format.md):

| Interp | Synfig | Use |
|---|---|---|
| `EASE` | `halt` | slow in and out; reversals (the end of a wave swing), starts and stops |
| `CLAMPED` | `clamped` | smooth pass-through points that never overshoot |
| `LINEAR` | `linear` | constant speed (rare: it looks mechanical) |
| `CONSTANT` | `constant` | jumps: eye states, mouth shapes, expressions |

Why keys instead of a value on every frame: a 10-second wave is ~20 keys instead of 240 values,
the `.sif` stays editable by hand in Synfig (an animator can drag a key), and the engine
interpolates at any frame rate. The catch: when two motions add up (breathing on top of a wave),
the sum has to be computed on our side. `timeline.sample` imitates Synfig's curves (`halt` as a
smoothstep) closely enough to add values at every key time.

This is **pose-to-pose** animation: the library writes the extreme poses (arm up, forearm
left, forearm right) and the curves draw the in-betweens.

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

## Manual key poses

A shot spec can also hold `poses`: bone angles at a time (`pose_at` in the MCP server). Each is
one key per bone, so a bone holds its pose until the next key, and moves between keys ease in and
out. A motion that starts later takes the bone over from its first key. Poses are clamped to the
joint limits too.

## Animation principles in code

- **Ease in/out at reversals** (`halt`): a waving forearm stops for an instant at each end of the
  swing, like a pendulum. Linear motion between extremes looks robotic.
- **Overlap:** parts of a body don't all start and stop together. The upper arm raises first,
  and the forearm is already swinging a little (30% of the amplitude) by the time it's up.
- **Follow-through:** after the main action, the trailing part settles instead of freezing. At
  the end of a wave the forearm eases back to a third of its swing while the arm is still raised,
  then both come down together. In `jump`, the body overshoots on landing (a small squash) and
  recovers. Not done yet: secondary motion on parts that aren't bones (Pip's ears move with the
  head as one piece).
- **Anticipation and squash** in `jump`: crouch before the leap, a small squash on landing.
- **Repeatable "randomness":** blinks come at irregular intervals, but the irregularity comes from
  a hash of the character and start time. The same shot always renders the same, which keeps
  evals and tests stable.

## Why energy is a parameter

The director describes intent: "a shy little wave", "a big excited wave". It shouldn't have to
pick angles in degrees, which it can't see and would get wrong in different ways for every
motion. One number from 0 to 1 carries that intent, and each motion decides what it means for
its own body parts. For `wave`:

| energy | arm raise | forearm swing | time to raise | per swing |
|---|---|---|---|---|
| 0 | 120° | ±15° | 0.45 s | 0.32 s |
| 1 | 160° | ±35° | 0.30 s | 0.22 s |

Bigger moves are also a little faster, as in real excitement. Because the number is bounded and
the same for every motion, it is easy for an LLM to use, easy to validate in the schema, and
easy to test ("energy 1 moves more than energy 0"). It also gives the evals in Step 7 something
measurable to check against the script's mood.

## Front-view limits (honest notes)

A front-view cut-out can only rotate parts in the picture plane. So:
- **nod** is a small downward bob of the head (a shift), not a pitch.
- **walk_cycle** is a march in place: legs lift in turn (a joint shift) while the body bobs.
  Swinging legs sideways read as stumbling. A real walk across the frame needs side or
  three-quarter view art (Step 4) and a placement that moves during the shot (placement is fixed
  per shot for now).
- `talk_gesture` and `point` raise arms sideways, because that's the only direction a front-view
  arm can move.

## Review

`uv run scripts/preview_motions.py [--energy 1]` renders every motion as a labelled cell in a 3×3
video (`~/ai-studio/scratch/motion-preview/`), using exactly the code path `synfig_mcp` uses.
