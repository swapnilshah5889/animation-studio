# Real motion: motion capture, retargeting and foot lock

How the `*_real` motions (`walk_real`, `run_real`, `wave_real`, `jump_real`, `shrug_real`) are made
from recordings of a person, and why a puppet cannot just copy the numbers.

## Motion capture in one paragraph

Mocap records where markers on a person are, many times a second. A *skeleton file* (ASF) says how
the bones connect and how long they are; a *motion file* (AMC) says, per frame, the root's position
and each bone's rotation. **Forward kinematics** (FK) turns that into 3D joint positions: start at the
root, rotate each bone by its angle, walk down the chain. We read CMU's files ourselves (about 150
lines, `studio_core/mocap/acclaim.py`); nothing needs a mocap library.

## Why a puppet cannot copy it

1. **It is 3D, the puppet is 2D.** We project the joints onto a vertical plane: seen from the side
   for gaits (legs swing forward and back), seen from the front for gestures (arms rise outward).
   `best_yaw` turns the plane toward where a gesture actually moves, so it is not foreshortened.
2. **Different proportions.** The actor's thigh/shin ratio and torso differ from Kit's. Copying
   joint *angles* puts the foot in the wrong place. So legs are stored as the **ankle's position
   relative to the hip**, in units of the actor's standing hip height, and solved on the puppet's own
   bone lengths with **two-bone IK** (law of cosines, `two_bone_ik`). Arms and torso are copied as
   angles (nobody needs the hand to be exactly somewhere).
3. **The rig has limits made for a front view** (e.g. one knee bends only one way). A clip may
   declare the wider range it needs (`Clip.limits`, `RANGES` in `motions/real.py`); beyond that,
   tracks are *fitted* (scaled down smoothly) rather than flat-clamped, and knee bends ease toward a
   cap (`soft_limit`) because rigid parts open up (holes, seams) when bent far.

## Foot lock (why no skating)

A planted foot must not move relative to the ground while the body travels over it. Mocap is nearly
there but the ankle rolls forward during a step. `lock_stance` replaces the ankle's world position
by its mean for the whole contact (with a 2-frame blend at each end) and flattens its height to the
floor. At playback the gait's phase is **distance divided by stride**, not time: the puppet takes a
step exactly when it has covered one, so slowing down (the placement path's ease-in/out) slows the
steps with it and the locked foot stays put. The distance is split into whole half-cycles (steps
stretch a little to fit), so a walk starts and ends on a *passing pose* with the feet together and
fades from and to standing.

## Principles on top (`motions/principles.py`)

Small functions on lists of per-frame values: `anticipate` (wind up opposite a move), `overshoot_settle`
(past the target, then back: a damped spring), `lead` / `drag` (the head moves first, arms and ears
follow), `contact_dips` (the body sinks on a landing), `breathing`. `apply_principles` runs them over
any clip; set `params.principles` (0 to 1) on an action to use them on the old motions too. Real
motion already has some of this, so use less (0.3 to 0.5) there.

## Gotchas we hit

- The first loop cut from a walk popped at the seam: pick two heel strikes of the same foot that
  match best (`find_loop`), then spread the leftover drift over the loop (`close_loop_periodic`).
- Subject 9's run trials are one stride long: no loop to cut. Subject 35 (the walker too) has long
  run/jog trials, so use that.
- Lowering the hip is part of foot lock: if the hip stays as high as in the capture while the foot is
  pinned lower, the leg cannot reach. The body is lowered just enough (`REACH`).
- Metrics must use the clamped angles (`metrics.frame_offsets`), or a clamped thigh hides a slide.
