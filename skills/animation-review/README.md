# Skill: animation review

Agent-agnostic. Any coding agent or local model that can run a shell command and look at an image can follow this
(Claude Code, Codex, Cursor, the director's local reviewer). Tool-specific adapters (for example
`.claude/skills/animation-review/SKILL.md`) only point here; keep the real content in this folder.

**When to use:** before showing any render to the owner, after any change to art, rig, motion or render code, and
whenever asked to review, check how it looks or QA the animation.

# Animation review

Follow the rubric in `docs/craft/visual-review.md` (read it first; it is the single source of truth, also read by the
director and the later local reviewer). You are the reviewer the owner should not have to be: judge what a viewer sees,
never pass a clip you did not look at, never fix while reviewing, report plainly.

## Procedure (keep image use small: one sheet, at most three zooms)
1. Evidence: `skills/animation-review/make_evidence.sh <video-or-image> <out-dir> [start] [end]` writes
   `sheet.png` (12 evenly spaced frames, left to right and top to bottom; their times are in `sheet_times.txt`),
   `motion.csv` (per-frame change; spikes above 5x the median are pops or cuts, e.g. a crossfade shows as a spike) and `audio.txt` (loudness).
2. Read `motion.csv` and `sheet_times.txt`, view `sheet.png` once, then crop (ffmpeg `-vf crop=w:h:x:y`) at most three
   zooms: a face, the worst frame, a joint or edge.
3. Compare with the reference (character sheet, `describe_art`, the design the owner chose).
4. Write `review.md` next to the clip: `Verdict: PASS | NEEDS WORK | FAIL`, a findings table (severity, time or frame,
   area, what you see, likely cause, suggested fix), "What looks good", and what you did not check.

Notes from the first review (2026-10-30):
- A composite video (e.g. a 2x2 engine comparison) makes panels tiny and its `motion.csv` mixes panels: pass the
  optional 5th argument `crop=w:h:x:y` to `make_evidence.sh` to review one panel at a time, and say which panels you did
  not check. The zoom budget counts crops of different panels.
- If every panel of an engine comparison shows the same defect, the shared art or face code is at fault, not the engine.
- Comparing with a reference sheet is optional when none is given; say you skipped it.

Calibration: the 2026-10-30 bake-off clip (`docs/spikes/owner-review-bakeoff.md`, Mia at 5 to 8 s) must come out FAIL.
