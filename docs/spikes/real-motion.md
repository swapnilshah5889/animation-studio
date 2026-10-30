# Spike: real human motion for the cut-out puppets

**Question.** Can recorded human motion make Kit and Bo move far more lifelike than the hand-keyed
library, inside the controlled cut-out engine (D-064, D-030, Synfig backend), and what does it cost?

**Scripts:** `scripts/fetch_mocap.py` (raw data), `scripts/build_real_clips.py` (clips),
`scripts/compare_motions.py` (the same 5 s shot, old against new, plus the numbers).
**Code:** `studio_core/mocap/` (parse, retarget, metrics), `studio_core/motions/real.py` (play a clip
on a rig), `studio_core/motions/principles.py` (anticipation, overshoot, lead, dips).
**Outputs** (git-ignored, outside the repo): `~/ai-studio/scratch/real-motion/compare.mp4` (old left,
new right, 960x540 each) and `compare.json` (the numbers below).

## 1. Source of real motion

| Option | Licence | Offline | Covers | Verdict |
|---|---|---|---|---|
| **CMU Mocap DB** (ASF/AMC text) | Site: "free for all uses"; FAQ: "may be copied, modified, or redistributed without permission" | yes after a 4 MB fetch | walk, run/jog, wave, shrug, jump, sit, point... | **used** |
| 100STYLE (BVH) | CC-BY 4.0 | yes, but gigabytes | only styled locomotion | not needed |
| AMASS, LAFAN1 | non-commercial / no-derivatives | n/a | n/a | rejected (licence) |
| Mixamo | Adobe terms, account | no | broad | rejected (account, terms) |
| Pose estimation from video (MediaPipe, RTMPose) | Apache-2.0 models | yes | whatever the clip shows | not done: no licence-clean clip of a person walking, waving and jumping exists in the repo, and noisy 2D joints need the same retargeting plus filtering. The **right use** is the owner filming their own short clips: same retargeting code, new `Mocap` loader. |

CMU gave all of it with the least effort (about 4 MB, six text files). Trials: 35_01 walk, 35_17
run/jog (same actor as the walk), 141_16 wave hello, 141_21 shrug, 13_39 jump. 13_27 (direct traffic,
wave, point) is fetched and unused: `point` needs a target, which the hand-keyed `point` already
aims by FK; a mocap pointing clip would not know where to point.

Not built: `sit_real` (a seated puppet needs the legs to fold toward the camera, which a front-view
cut cannot show) and `point_real` (above).

## 2. Retargeting (deterministic, unit-tested)

See `docs/learning/real-motion.md` for the how. In short: project the 3D joints onto a side plane for
gaits and a front-ish plane (turned toward the gesture, at most 45 degrees) for gestures; low-pass and
resample to 24 fps; torso, head and arms become angle offsets, legs become the ankle's position
relative to the hip and are solved by IK on the puppet's own bones; gaits are cut as one seamless loop
from two heel strikes, feet are locked while planted and the body is lowered until the planted leg
reaches; playback phase follows the distance the character covers. Clips are engine-neutral JSON
(role and side, never a bone or Synfig name) in `motions/real_clips/` (3 to 6 KB each).

New motions: `walk_real`, `run_real`, `wave_real`, `jump_real`, `shrug_real` (all also take
`energy`, `speed`, `principles`; `wave_real` takes `side` and mirrors). `principles` (0 to 1) works on
every motion, old ones included.

## 3. Results (Kit, the same 5 s shot: walks in, waves, jumps)

| | old (hand-keyed) | new (real) |
|---|---|---|
| Planted-foot slide in the walk, mean per contact (leg lengths) | 0.037 | 0.041 overall; **0.017 to 0.050 mid-walk**, 0.16 to 0.19 at the start and stop |
| Knee bend range while walking | 0 deg (rigid shins) | 125 deg (thigh 90 deg, shin 125 deg, incl. the jump crouch) |
| Torso and head moving | no | torso 13 deg, head 8 deg (played at 0.5 and 0.4 of the actor's) |
| Range of the actor's arm kept in the wave (puppet / source) | n/a | 1.06 (upper arm and forearm) |
| Peak acceleration of any joint (deg/frame^2) | 62 | 89 (fast wave and jump arms; real, not a glitch) |
| Jerk RMS (deg/frame^3) | 4.4 | 14.6 |

Honest reading: the foot-lock is as good as the old walk in the middle of a walk and worse at the
start and the stop (the fade from and to standing slides the planted foot about 40 px). The
smoothness numbers are **not** a win: real motion has more movement in more joints, so they go up;
they say nothing about quality and should not be used as a target. What changes is what the eye
reads: bent knees, the body lowered on the planted leg and rising on the swing, a torso lean, a wave
that travels along the arm with an elbow, a crouch before the jump and a landing.

### Cut defects (pose sweep, Kit and Bo, both views; frames with at least one hole, seam or detached part)

Swept frames are where a bone reaches its minimum or maximum; the real clips have many more such
frames (every bone moves) than the old ones, so read the rates, not the counts.

| Character | Old motions (walk_cycle, wave, jump, shrug) | New motions (the five `_real`) |
|---|---|---|
| Bo | 7 of 34 frames (21%): 1 hole, 5 seams, 2 detached | 23 of 108 (21%): 4 holes, 17 seams, 5 detached |
| Kit | 9 of 34 frames (26%): 1 hole, 13 seams | 48 of 108 (44%): 29 holes, 51 seams |

Per motion (frames with a defect / frames swept, Kit | Bo): walk 2/6 | 2/6 old, **13/20 | 9/20** new;
jump 2/4 | 3/4 old, **20/26 | 8/26** new; wave 3/16 | 2/16 old, **1/32 | 1/32** new; shrug 2/8 | 0/8 old,
**3/14 | 0/14** new; run (no old one) 11/16 | 5/16.

So: **wave and shrug do not add defects; Bo's overall rate is unchanged; Kit's walk, run and jump add
holes and seams** (largest hole 346 px at 960x540, around the hips and knees; the old maximum was
98 px). That is a real cost of bending legs in a rigid cut, and it is why the clips are not the
default for any motion yet. The old `walk_cycle` is kept; `walk_real` is opt-in.

What the sweep showed while building this, so the numbers make sense:

- **Legs were the whole problem in the upper-body clips.** `shrug_real` with legs had 8 of 12 frames
  with defects on Kit; with the legs zeroed 0 of 8. Any knee or hip bend opens seams and holes in the
  current rigid cut, so wave and shrug leave the legs standing (`legs=False` when building).
- Knee bends beyond about 35 degrees open holes (up to 340 px at 960x540): knee bends are eased toward
  65 degrees (`soft_limit`), the thigh swing allowed to 50 degrees.
- The forearm range had to be widened (the wave flexes the elbow the way the front-view rig does not
  allow: 0.3 of the arm range kept without it, 1.06 with it) and that did not add defects (1 of 32).

## 4. What still looks stiff, and why

1. **Rigid parts.** Every limb is still two flat pieces with a cap at the joint. Bending a knee or
   elbow shows the seam, and Kit's walk, run and jump still add holes even with the knee bend held back. The bigger fix is skeleton deformation (see `bending-limbs.md`) as the
   default: it would let the knee bend fully and remove most of the seams that limit this clip set.
2. **Flat in depth.** A front-view puppet walking across the frame has legs swinging sideways in the
   picture plane (a profile gait on a front body). It reads as walking; it is not a true profile.
   A profile view of each character would let the side-plane data be used as captured.
3. **No squash and stretch, no secondary mass.** Nothing deforms; the body is one rigid torso. Ears and
   tails follow (`follow.py`) but the cloth, scarf and hair do not.
4. **Hands and the face** are separate systems (hand poses, procedural face): the real clips drive
   neither, so a wave has a wave hand pose only from the old rule.
5. **Start and stop of a walk** shuffle (about 40 px of slide over 0.3 s).
6. **One actor, one style.** The walk and run are one person's; every character walks the same way
   (scaled). Variety (a heavy bear, a bouncy bunny) needs different clips or a style layer (cycle
   timing, bounce, lean).

## 5. Next levers, in the order I would pull them

1. **Bendable limbs by default** (4B.4 spike): unlocks full knee and elbow bends, so the mocap range
   can be used instead of eased.
2. **Frame-by-frame hero shots** (OpenToonz tier, D-031) for the shots where the story needs true
   acting: reviewed per shot, not per film.
3. **A profile view** per character for gaits, and a 3/4 walk that uses the same clip.
4. **Own clips**: the owner films a few short clips (walk, wave, jump, a character's signature move),
   pose estimation extracts 2D joints, the same retargeting plays them. Gives each character its own
   gait for free.
5. **Style layer** over the clips (tempo, bounce, lean, overshoot per character), using the
   principles functions.
