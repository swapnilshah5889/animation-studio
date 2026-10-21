# Rigging a cut-out puppet: bones, rest pose, forward kinematics

How a `rig.json` becomes a moving puppet (`studio_core/rig.py`). Background: D-007
(consistency comes from the rig), D-027 (bones for characters).

## The pieces

- **Parts** are PNG cut-outs (torso, head, upper arm, …). Each has a **pivot**: the pixel that sits
  on its joint.
- **Bones** form a tree from a **root** (Pip's torso, pivot at the hips). Each non-root bone
  **attaches** at a pixel of one of its parent's parts (the shoulder is pixel (178, 45) of the
  torso image).
- **Draw order** is a separate list (back to front). With bones, the far arm can sit behind the
  torso while still hanging from it, which nested groups can't do.

## Rest pose and offsets

The **rest pose is the art as drawn.** Each bone declares the direction it points in the
drawing: `direction_deg` 90 (up) for torso and head, −90 (down) for hanging arms and legs.
Everything that animates is an **offset from rest**, relative to the parent bone:

- `upper_arm_l: +150` raises Pip's left arm 150° counter-clockwise from hanging.
- `forearm_l: +40` bends the elbow another 40° on top of whatever the upper arm does.
- All offsets 0 means the drawing exactly.

Motions (task 2.5) and `pose_at` speak in offsets, so "raise the arm 150°" means the same on every
rig, however the art was drawn. `limits_deg` clamps them (`clamp_offset`), so an LLM asking for
`head: 90` gets a polite 25.

## Forward kinematics (FK)

FK computes where everything ends up from the joint angles, parent first:

```
world_dir(bone)   = direction_deg(bone) + Σ offsets(root … bone)
joint(child)      = joint(parent) + rotate(attach vector, parent's rotation from rest)
```

`world_pose(view, offsets)` implements this in pixels. It is used by tests (predict where a
rendered part lands: within 1.5 px) and later for "point at" and "look at" targets. Synfig
does the same math internally from the bones we write. The test shows the two agree.

The opposite problem, **inverse kinematics** (IK: "put the hand *here*, find the angles"), is
not built into Synfig 1.5.5. A two-bone IK (shoulder–elbow–hand) is a short closed-form solve
in Python if a motion needs it.

## How rig.json maps to Synfig

| rig.json | Synfig (`build_character`) |
|---|---|
| bone, `direction_deg` | `<bone>` with angle = direction − parent direction (+ offset) |
| `attach.at_px` | bone origin = (attach − parent pivot) in pixels, y up, rotated by −parent direction, then pixels → units |
| part, `pivot_px` | an import layer placed so the pivot is at local (0, 0) |
| part's bone | a group whose transformation is a `bone_link`, `base` = rotate by −direction (lays the art along the bone's +x) |
| `draw_order` | the order of those flat groups |
| (always) | a skeleton layer, not rendered, so the rig stays editable in Synfig Studio |

## Gotchas

- Left and right are the **character's**: in the front view, Pip's left arm is on the
  viewer's right.
- Mirrored limbs rotate opposite ways: raising the right arm is a negative offset. Motions take a
  `side` and flip the sign; the LLM never has to.
- Joint pixels must be inside the parent part's image (`check_rig`), or the limb floats.
- Measuring rendered parts: overlapping parts and the canvas edge both hide pixels and bias a
  centroid. That is why the FK test renders twice with the measured part on top, on a large
  canvas.

## The procedural face (task 2.4)

Eyes, brows and mouths are vector shapes drawn in code (`studio_core/face.py`), not pixels in the
head image (D-007). They are placed from the rig's `face` anchors and attached to the head bone
(`build_character(attachments=...)`), so they turn with the head: a render test rotates the head
20° and the mouth's pixels rotate about the neck to within 1.5 px.

| Switch | States | Driven by |
|---|---|---|
| `eye_l`, `eye_r` | open, half, closed | `blink_track(frames)`: half → closed → half → open over 4 frames |
| `brows` | neutral, happy, sad, surprised, grumpy, worried | the expression track |
| `mouth` | A–H, X (Rhubarb's set) | `mouth_track(cues)` from Rhubarb |
| `mouth/X` (rest) | one rest mouth per expression | the expression track again |

Why switches: each state is a fixed drawing, and a switch changes on an exact frame. That is
right for lip-sync (mouth shapes snap, as in traditional animation) and for blinks. Expressions
snap too in v1. A brief in-between could be added later by animating brow spline points.

Preview every combination with `uv run scripts/preview_face.py` (written to
`~/ai-studio/scratch/face-preview/face_preview.png`).

Gotcha learned while testing: when measuring a colour in a render, antialiased edges of *other*
art can come close to it (dark line art over pink ≈ dark red). Use a tight tolerance or a
bounding box, or the centroid drifts.
