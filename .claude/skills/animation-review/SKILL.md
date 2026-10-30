---
name: animation-review
description: Review a rendered animation clip, film or character sheet as a strict picture reviewer (faces, anatomy and rig, character and style consistency, motion smoothness, transitions, kid safety). Use before showing any render to the owner, after any change to art, rig, motion or render code, and whenever asked to "review", "check how it looks" or "QA the animation". Looks at the pictures, not only at numbers.
---

# Animation review

Follow the rubric in `docs/craft/visual-review.md` (read it first; it is the single source of truth, also read by the
director and the later local reviewer). You are the reviewer the owner should not have to be: judge what a viewer sees,
never pass a clip you did not look at, never fix while reviewing, report plainly.

## Procedure (keep image use small: one sheet, at most three zooms)
1. Evidence: `.claude/skills/animation-review/make_evidence.sh <video-or-image> <out-dir> [start] [end]` writes
   `sheet.png` (12 evenly spaced frames, left to right and top to bottom; their times are in `sheet_times.txt`),
   `motion.csv` (per-frame change; spikes are pops or cuts) and `audio.txt` (loudness).
2. Read `motion.csv` and `sheet_times.txt`, view `sheet.png` once, then crop (ffmpeg `-vf crop=w:h:x:y`) at most three
   zooms: a face, the worst frame, a joint or edge.
3. Compare with the reference (character sheet, `describe_art`, the design the owner chose).
4. Write `review.md` next to the clip: `Verdict: PASS | NEEDS WORK | FAIL`, a findings table (severity, time or frame,
   area, what you see, likely cause, suggested fix), "What looks good", and what you did not check.

Calibration: the 2026-10-30 bake-off clip (`docs/spikes/owner-review-bakeoff.md`, Mia at 5 to 8 s) must come out FAIL.
