# Progress

Update this at the end of every working session. Newest entry at the top.

**Current step:** Step 4 (`comfy_mcp`): tasks 4.1–4.9 run; 4.10 (docs + the Step 5 brief)
remains. The owner chose to fix the puppet cut on a few varied characters before closing
Step 4 (`scripts/cast_review.py` scaffolds this: Kit, Bo, a child, a bird, a robot). The
roadmap now ends in production-grade films (D-059): Step 4B (animation quality) comes next,
and the old Step 7 is split into Steps 7–12. Open items: Pim's other cut failures (the eye finder is fixed, D-060), task 3.2b's Parler download (deferred), Docker's memory
reservation, deleting the pre-Step-4 scratch files, Kit's and Bo's real voices (placeholders),
and the hosted-vs-desktop decision (needed by Step 11).

---

## 2026-10-26: Step 4: Pim's loose arms: white clothes were cut out of the silhouette (D-062)

**Diagnosed:** not the limb fit. D-057's gap rule left Pim's white shirt and sleeves (13-15 from the
background, `BG_HOLE` was 15) open as "background seen through", so only their outlines were
figure. The arm fit then followed an outline stroke, and the arms stayed in the torso part.

**Done**
- `puppet/checks.py`: `BG_HOLE` 15 -> 10.
- `puppet/build.py` `complete_hidden`: an upper arm half hidden, with a sleeve of its own colour
  (not the forearm's), is cut as drawn instead of becoming a plain sleeve.
- Tests: a white shirt just off the background stays figure; the far sleeve rules (own colour,
  same fur, mostly hidden). Each fails without its fix.

**Verified**
- Kit and both Bo builds: part images and rig byte-identical before and after (scratch harness,
  SAM off). Pim: front `limbs_ok` true; three-quarter arms and legs follow the drawing (checked on
  an overlay), the far arm no longer leaves a ghost arm on the torso.
- 467 passed, models excluded; ruff clean.

**Not done (Pim, three-quarter):** a brown disc at the far elbow when the arm is raised; small
fragments beside the body at rest; the far leg falls apart in the bent-knee pose; `shin_l`
coverage 0.81 (needs 0.85, the drawn sole is short). Pim was not rebuilt with SAM or through MCP.

**Next:** the elbow disc and the bent-knee far leg (they also affect Bo), then Mia and Bolt.

---

## 2026-10-26: Step 4: small view-only paint is a note (D-061)

**Done**
- `puppet/consistency.py`: paint seen in one view only is reported from 3% of a region, but is a
  problem only from 7%; below that it is a note (`report["notes"]`, `"tolerated": true`).
- Test: a small beak only the turned head shows passes with a note, a hat (9.7%) still fails, and
  the beak test fails without the change.

**Verified**
- Real sheets (scratch harness, SAM off): Kit and Bo (both films) have identical consistency
  reports; Pim's now passes with the beak (4.7%) as a note. 463 passed, models excluded; ruff
  clean.
- Pim's current sheets show no head-size or feet problem (head share 0.352 vs 0.369): those
  findings in the bird trial came from the other candidates.

**Not done:** the 7% limit rests on two characters; re-check with Mia and Bolt. Pim's remaining
problems: SAM rejected, far arm and shins in the three-quarter view, and a full end-to-end rebuild
is still to run. Mia and Bolt are not designed yet.

---

## 2026-10-26: Step 4: the no-nose face fix (D-060)

The owner chose to time-box the varied-cast work to a pass bar and start with the eye finder.

**Done**
- Pass bar recorded (D-060): 4 of 5 (Kit, Bo, Pim, Mia, Bolt) build with matching views, limbs on
  their bones and the face found in both views; the rest is tracked and carried into Step 4B.
- `puppet/build.py` `clean_face`: a face with no dark nose is read again with no nose when the
  mark taken for the nose leaves no eye above it (`no_nose`).
- Tests: the bird-like face (was xfail, now a normal test, fails without the fix) and a guard for
  a single brown eye.

**Verified**
- Before/after on the real sheets (scratch harness, SAM off, existing klein redraws): Kit and Bo
  (both films) identical in cleaned pixels, face anchors and notes. Pim: eyes `[]` -> one eye
  found in each view (the other placed from the skeleton), where before the eye was kept as a
  nose.
- `ruff check` clean; 462 passed, models excluded (2 min 7 s).

**Not done**
- Pim was not rebuilt end to end: only the face step was compared. The other Pim failures are
  still open: SAM rejected (IoU ~0.72), consistency flags the beak and feet, head 110% as tall in
  the three-quarter view, far arm and shins loose.
- Mia (child) and Bolt (robot) have no designs yet (`films/step4-cast` has no `child` candidates).

**Next:** the consistency tolerance for small features (beak, feet), then Pim's head size and
loose limbs, then design Mia and Bolt, then task 4.10.

---

## 2026-10-26: Roadmap: production-grade goal and new steps (D-059)

The owner asked for the missing steps to be added and set the goal: the final output must be
production grade.

**Done**
- `docs/ROADMAP.md`: a production-grade bar (picture, animation, lip-sync, sound, story, rights,
  reliability, deliverables, operations), Step 4B (animation quality), and the old Step 7 split
  into Steps 7 (evals), 8 (durable pipeline), 9 (training), 10 (series), 11 (production release)
  and 12 (future tiers). Each new step has a "done when".
- Step numbers 0–6 are unchanged (stable ids); live references to the old Step 7 now point at the
  new steps (ARCHITECTURE, AGENTS, README, the Step 3/4 briefs, a learning note).
- Docs only: no code, tests or schemas changed.

**Open questions for the owner**
1. Confirm or change the bar's targets (they are proposals), at the latest in the Step 4B brief.
2. How to close Step 4: time-box the varied cast against a pass bar, or close it on Kit and Bo
   and carry the rest into Step 4B.

---

## 2026-10-26: The coding agent: Claude Code → DeepSeek Harness (D-058)

The owner moved from Claude Code to a DeepSeek Harness coding agent and asked to confirm the new
agent could run the project before resuming Step 4. This session did both.

**Proved the new agent can drive the whole pipeline (not just read it):**
- `ruff check .` clean; the full suite passes (460 passed, models excluded, 2 min 20 s).
- All three MCP servers start over stdio from `.mcp.json` and answer real calls: `synfig_mcp`
  (16 tools), `audio_mcp` (7), `comfy_mcp` (9).
- Generated real media through the servers: the Step 3 done-when shot (27 tool calls →
  1080p/240-frame video with two voiced, lip-synced lines, music and SFX, −14.6 LUFS) and a
  background draft through `comfy_mcp` (storybook garden, 1536×576, checks passed).

**Scrapped the Claude Code dependency:**
- `CLAUDE.md` → `AGENTS.md` (agent-neutral; every live reference updated, the historical
  PROGRESS log and DECISIONS entries kept as-is).
- `scripts/run_first_shot.py` rewritten as a scripted MCP client (no `claude` CLI). This
  closes Step 2's done-when: verified 10 tool calls → a 1080p, 240-frame shot with a mouth
  cue track, all checks pass. Transcript: `docs/learning/mcp-first-shot.md`.
- README, ARCHITECTURE, ROADMAP, the Step 2/3 briefs and `docs/learning/mcp.md` now say
  "any MCP client / a coding agent" instead of "Claude Code". D-058 records the change.

**Decisions confirmed with the owner (2026-10-26):**
1. Rename `CLAUDE.md` → `AGENTS.md`.
2. Replace `run_first_shot.py` with a scripted client.
3. Resume Step 4 by fixing the puppet cut on varied characters (`cast_review.py`).
4. Prove the agent can generate media (done, above).

**Bird trial (Pim, same day):** built end to end (~46 min, slow: Docker's 8 GB reservation keeps
VRAM at ~3 GB free and the klein redraw swaps). Both passing sheets (c1, c3) built but their views
differ, and round 2's sheets all failed their checks. Failures to fix, in order:
1. **No eyes found** (both views). Diagnosed: the beak is yellow, so the near-black "nose" finder
   takes a dark feature *above* the eyes for the nose; the "eyes above the nose" band then sits
   above the real eyes and loses them. Fix the eye/nose finder for faces with no dark nose.
2. SAM rejected (IoU ~0.72) → colour-key fallback.
3. Consistency flags the beak yellow and feet orange as view drift (small features).
4. Head 110% as tall in the three-quarter view.
5. Far arm and shins loose in the three-quarter view.
Also fixed `cast_review.py` so it stops before a design round past the build limit.

**Next:** fix the eye finder first (a unit test with a bird-like face that fails without the fix),
then consistency/palette tolerance, then Mia (child) and Bolt (robot), then task 4.10.

---

## 2026-10-23: Step 4 task 4.9: the proof runs end to end; the puppet cut needs to generalise

`scripts/run_step4_shot.py` is a scripted MCP client. It starts the three servers from
`.mcp.json`, makes a new character and a new place from words, then builds and renders a shot
with them using only tool calls. Where the owner would choose, it takes the first candidate
whose checks pass, and if the puppet's views don't match it builds from the next passing sheet
(D-057). The transcript is `docs/learning/mcp-step4-shot.md`.

**Run 2 (the recorded one): 39 tool calls in 49 min, 11 of 12 checks passed**
- Bo, "a cheerful little brown bear cub wearing blue dungarees":
  - 3 sheets, all passing their checks
  - c1's build was rejected (head 116% as tall in the three-quarter view); c2 built with
    consistent views
- The orchard: 2 drafts → plate (tiled finish, 341 s) → 4 layers (469 s). The pan showed no
  hole in 50 frames.
- The shot `films/step4-proof/shots/s01_sh01/shot.mp4`: Bo (three-quarter, facing Pip) waves
  and asks, Pip nods and answers, with music, birdsong and a slow pan. 1080p, 192 frames.
- Progress notifications reached the client over stdio on every art call over 30 s.
- The failed check was the loudness: −15.2 LUFS against −14 ± 1. That is the mixer working as
  designed: it trims the whole mix when a true peak still pokes over −1.5 dBTP after its
  limiter. The check now follows that contract (−16 to −13 LUFS, peaks ≤ −1 dBTP). The
  transcript keeps the run's own result.

**Fixed along the way (each verified on the real sheets; Kit's masks and face detection are
pixel-identical before and after; a unit test for each fails without its fix)**
- Run 1 stopped at the plate: an untiled 3 MP VAE decode failed on MPS ("tensor dims larger
  than INT_MAX"). The plate's VAE encode and decode are now tiled.
- The three-quarter redraw gave Bo a scarf: the klein prompt named Kit's scarf. It now carries
  the character's own description.
- Background between touching legs was cut into the leg parts (white strips): enclosed
  background-coloured regions that surround nothing stay open.
- A muzzle below the skeleton's nose line went to the torso: figure between head pixels, along
  rows or columns, joins the head.
- An eye was taken for the nose and stayed painted, because the real nose sat on the outline.
  Thin strokes are now opened away first, and the biggest compact black blob is the nose.
- Progress news now says what is being made ("c1 drawn (1/3): ok; drawing sheet 2 of 3").

**Bo's face (owner review: "the face is deformed").** In run 2's shot Bo had three eyes,
two noses, one brow over both eyes and a seam across the muzzle. All of it came from one wrong
guess: the near eye was taken for the nose, so that eye was kept, and the drawn face was
anchored to it. With the nose fix and three more (D-057: the snout tip joins the head, a
mouth joined to the nose is painted out, the face zone reaches the snout), Bo was rebuilt
(22 s; the three-quarter redraw is reused) and the shot re-rendered. He now has two eyes where
the drawing had them, a brow over each, one nose, and the mouth on the muzzle, with no seam.
A small speck can remain right at the snout's edge. `films/step4-proof/shots/s01_sh01/shot.mp4`
is the re-rendered shot.

**What the shot still shows (open, D-057)**
- outline dashes beside the body, left behind when the arms are hung
- a seam on the waving arm
- in c2's three-quarter cut, the torso also holds part of the far arm and the dungaree cuffs;
  in the bent-knee test pose the far leg falls apart
- with c1, the redraw made the snout near-white with no outline, and it came out
  transparent; no colour key or SAM mask finds it
- "orchard" came out as hills, houses and plain trees (no apples), and the background prompt
  always asks for a lawn floor (task 4.6)

**Verified**
- The full suite: 460 passed, model tests excluded (2 min 4 s). Ruff clean.
- Kit is unchanged by every fix (masks and face notes compared before and after).

**Not done**
- No full run with all the fixes together. Bo was rebuilt and the shot re-rendered with
  studio_core directly, not through a new MCP run. A run 3 takes about 50 min.
- The three-quarter cut problems above. They come from rules tuned on one character.
  Recommended next: build 3 or 4 varied characters (a bear, a child, a bird, a robot, say)
  and make the cut follow drawings that differ from the skeleton, before closing Step 4. Its
  done-when ("a text description becomes a rigged puppet ... with no manual steps") holds for
  Kit today, not yet in general.

**Open questions for the owner**
1. Fix the cut on varied characters before closing Step 4 (recommended), or close Step 4 and
   carry it into the proposed animation-quality step?
2. Bo's voice is a placeholder (`am_puck`, +2.5 semitones) cast by the script.

---

## 2026-10-23: Step 4 task 4.8 done: the `comfy_mcp` server

The owner passed checkpoint 4 (the meadow pan). A subagent moved the two checkpoint previews
into `studio_core`; this session wrote the server, its tests and the Inspector calls (D-056).

**Built**
- `mcp/comfy_mcp` (workspace member `comfy-mcp`, in `.mcp.json`), with nine tools:
  - `describe_art`: style, characters and places, each with its next step
  - `design_character`, `choose_design`, `build_puppet`, `preview_puppet`
  - `generate_background`, `choose_background`, `split_depth_layers`, `preview_background`
- Long jobs run in a worker thread behind one art lock, with MCP progress notifications
  (elapsed seconds plus the latest news, a heartbeat every 15 s). The previews have a lock each.
- `studio_core/preview/` (subagent): `preview_puppet` and `preview_background` as library
  functions returning results and raising `PreviewError`. Every refusal comes before anything
  is written. The scripts are thin command lines with unchanged outputs.
- `preview_puppet` through MCP refuses a character with no voice (casting belongs to the
  sound server); the script still casts the placeholder.
- New learning section: "Tools that take minutes" in `docs/learning/mcp.md`.

**Verified**
- `tests/test_comfy_mcp.py`, 10 tests through a real MCP client:
  - the tool list, with no engine or model names in what the model sees
  - describe_art's next steps, from a fresh film to a built puppet
  - design and background rounds through the real round code, with ComfyUI faked at
    `run_graph`
  - build, layers and previews mapped to results
  - twelve refusals, none of which reach the GPU
  - two art jobs run one after the other, with increasing heartbeats and a "waiting" message
  - the stdio transport
- The preview refactor: 38 preview tests pass, and both scripts render with exit 0. Kit's
  preview took 15 s at 640x360; the meadow pan found no hole in 21 frames.
- The full suite: 456 passed, model tests excluded (1 min 53 s).
- The Inspector check over all three servers: 45/45 calls as expected, exit 0.
  - comfy_mcp: `describe_art`, `choose_design`, `preview_puppet` (Kit) and
    `preview_background` (no holes) ran for real.
  - Eight requests that must be refused were refused, with messages that name the fix.
  - The first run caught one regression in the check itself: copying Kit into the scratch
    film turned an old "unknown character" refusal into a success. That call now uses an id
    that doesn't exist.

**Not covered yet**
- The GPU tools (design, build, generate, choose_background, split) have only run through MCP
  with fakes or as refusals. Task 4.9 runs them end to end through a scripted client.
- Progress notifications were tested in-process. Whether Claude Code shows them is left for
  4.9.
- The background prompt always asks for a lawn of short grass along the bottom (task 4.6),
  so a beach or a kitchen would get grass. It is worth a look before 4.9 picks a new place.

---

## 2026-10-22/23: Step 4 task 4.7 done: the meadow in layers, panning with no holes

The owner chose meadow c4. Built with three subagents in parallel, plus this session:
- the depth graph and the one-time model comparison
- the ProMax repaint fill graph
- the pan test render with its hole check
- this session: bands, parallax, layers and the orchestrator

**Built**
- `comfy_graphs.depth_map` (subagent): DA3 MONO-LARGE at 1512, chosen over DAv2-Small and
  other resolutions (D-055).
- `comfy_graphs.repaint_fill` (subagent): SDXL plus ProMax "repaint", with the masked pixels
  black in the control image and grey in the latent, and a feathered composite.
- `studio_core/place/layers.py`, `split_depth_layers`:
  - sky, then far / middle / ground cut at histogram valleys, plus an optional foreground
  - islands joined; ground kept connected to the bottom (no torn trees)
  - parallax relative to the ground at the characters' feet, capped so no layer edge
    enters the frame
  - fills within pan reach (SDXL); the sky elsewhere a flat colour
  - feathered compositing; `layers.json` validated; a flat (failed) depth map refused
- `scripts/preview_background.py` (subagent): a pan with an optional character, rendered
  over a magenta probe backdrop, with a hole count and a layer-edge check.

**Verified**
- Meadow split: sky 26%, far 27%, middle 18%, ground 30%; parallax 0.05 / 0.52 / 0.86 / 1.0.
- Pan with Kit (`slow_pan_right`, 6 s, 1080p): no hole in 38 sampled frames, and no layer
  edge entered the frame. Rendered in 77 s.
- The pan reads as depth: the hills and tree line drift slower than the lawn, and the big
  tree slides in whole.
- 440 tests pass, model tests excluded (2 min 50 s). New tests: layers 7, depth 16 (plus 2
  live), fill tests, preview 21.
- Problems found in review and fixed:
  - fill seams (now feathered)
  - fill prompts redrawing near things (now per-layer prompts)
  - SDXL inventing odd shapes in a full-frame sky fill (now limited to pan reach)
  - a near tree's canopy in the ground layer (ground must reach the bottom)
  - a foreground parallax that would show its edge (now capped)

**Costs**
- A split takes about 8–14 min, mostly three fills at about 2.7 min each plus memory
  pressure. Depth takes 5 s.
- A full-size fill isn't feasible on this Mac: over 30 min with swap full.

**Open questions for the owner**
1. Checkpoint 4: does the meadow feel deep enough during the pan? The parallax factors are
   perceptual, and can be tuned.

---

## 2026-10-22: Step 4 task 4.6 done: backgrounds from text

The owner approved Kit's three-quarter view. Built with one subagent in parallel
(`comfy_graphs.finish_plate`: Real-ESRGAN upscale plus a low-denoise SDXL refine), plus this
session.

**Built**
- `studio_core/place/design.py`:
  - `generate_background`: drafts at 1536×576 in the film's style, from a code prompt
    template that keeps the front an open lawn
  - `choose_background`: records the pick, finishes it into `backgrounds/<id>/plate.png`
    (2880×1080), and records everything in `plates.json` (new schema)
- `place/checks.py`: ground-band checks (edges, odd colours, depth), calibrated on real
  drafts.
- `finish_plate` (subagent): `txt2img` now shares its style setup, and its golden JSON is
  byte-identical. The refine takes 10 steps.
- `scripts/background_review.py`: drafts (safe to re-run), a self-contained review page, and
  `--choose`.
- Learning note: `docs/learning/upscale-and-refine.md`.

**Verified**
- First template: big foreground flowers and the stream along the bottom, which the checks
  caught (14% edges, 48% covered).
- With the stronger template, all 4 demo drafts ("a sunny meadow at the edge of a forest with
  a small stream", seeds 11–14) pass, at 120–140 s each.
- c4 finished into the plate in 327 s. The composition matches the draft, the detail is crisp,
  and there are no seams.
- 369 tests pass, model tests excluded, plus the live draft test. ComfyUI kept no copies.

**Open questions for the owner**
1. Which draft for the meadow? I finished c4 (an open lawn across the front).

---

## 2026-10-22: FLUX.2 klein wired into build_puppet (D-053)

The owner approved wiring klein in as proposed in D-052. Built with one subagent in parallel
(`puppet/fit.py`: limbs fitted to the drawing), plus this session.

**Built**
- `puppet/turn.py`:
  - klein redraws the front figure turned, for seeds 1–3
  - ground shadows are dropped
  - each figure is placed where the three-quarter view goes, edges unmixed
  - each sheet is scored with the cut's checks; the best is kept and reused
    (`regenerate_turn`, or `replace=True` to re-place existing edits)
- `build_puppet(three_quarter="klein")` is now the default.
- `puppet/fit.py` (subagent), applied to every view before the cut:
  - arm angles, forearm lengths to the drawn paw, shoulders slid onto the drawn arm
  - legs fitted as bars under the torso
  - drawings that follow the skeleton are left exactly as they were
- `build.py`:
  - arms drawn behind the torso are cut where they emerge, with the hidden stretch painted
    (a mostly hidden upper arm becomes a plain sleeve)
  - a nose finder that works on turned heads (lowest compact black blob)
  - eyes: dots or arcs near the nose, never ear shading
  - the three-quarter face takes the front's eye, brow and mouth sizes
  - wider paws past the wrist

**Bugs found by looking at renders, and fixed**
- a paw floating beside the body (the forearm was too short for the drawn arm)
- leg corridors cutting the tail
- an eye drawn by the ear
- the face lost inside klein's pale face (eyes dropped as islands)
- a scarf chunk riding on the far arm
- a hole in the torso where the far arm had been

**Verified**
- Kit: seed 3 of 3 chosen (turn 108% of asked, consistency clean).
  - Every three-quarter limb passes except one shin (coverage 0.81).
  - Near upper arm on its drawn arm: 24% → 100%.
- Renders of both views (7 s, 1080p, about 35 s each). In the three-quarter view Kit faces
  Pip, waves with the far arm, blinks and talks. The front view is unchanged.
- 322 tests pass, model tests excluded. New tests:
  - limb fitting: 24 (subagent)
  - turn: 6 (shadows, placement, a pale face, best-seed choice, reuse, replace)
- Klein build: about 7.5 min the first time (three edits), then 27 s.

**Known limits**
- A small hard edge at the chin when the head turns.
- Legs fitted as straight bars (bent knees aren't followed).
- Hidden upper arms are plain sleeves.
- The three-quarter style is a little flatter than the SDXL front.

**Open questions for the owner**
1. Does Kit's three-quarter view pass now?

---

## 2026-10-22: FLUX.2 klein 4B installed and trialled for the three-quarter view

The owner approved the install and a trial, with the results to be shown before any wiring.

**Done**
- Downloaded the three files (16.13 GB, Apache-2.0, sha256-verified) in about three minutes,
  and recorded them in `config/models.toml` and MODELS.md.
- `comfy_graphs.flux2_edit` (written by a subagent, in parallel with the download), from
  Comfy-Org's template. Every node checked against our ComfyUI v0.42.1; 10 unit tests.
- `scripts/spikes/flux2_three_quarter.py` runs two rounds of four edits, then places,
  measures and writes `renders/spikes/flux2-three-quarter/step4-demo-kit/review.html`.
- Fixed the turn measure (now the centroid of the face's marks) and the eye-pair choice.
  Rebuilt Kit; nothing changed in its rig.

**Results** (D-052)
- Turn: 56–102% of what was asked, against SDXL's 6%. The same fox in all eight edits, with
  no hat.
- Arms: against the body in round 1, nearly horizontal when asked for 25° in round 2. Ground
  shadows in half of them.
- Time: about 2.5 min per edit, or 4+ min with a pose reference (which didn't help).

**Verified**
- 292 tests pass, model tests excluded.
- The ComfyUI folders kept no copies, and its memory was freed afterwards.

**Open questions for the owner**
1. Wire klein into `build_puppet` as proposed in D-052 (edit the front into the
   three-quarter view, pick by the checks, fit the arms before cutting)?

---

## 2026-10-22: Step 4 task 4.5 done: the three-quarter view, and a consistency check

The owner approved checkpoint 3, including the change to Pip's high-energy wave. They also
asked whether the wave's rigid "rectangle" look and the overall quality will be handled.
- Answer: mesh bending is planned for Step 6 (OpenToonz Plastic). Wrist and hand swaps,
  motion principles, secondary motion, cut-edge outlines and a motion-quality eval are not on
  the roadmap yet.
- Proposed (owner's call): an "animation quality" step between Steps 4 and 5.

Built in parallel:
- a subagent: research on the front → three-quarter edit model
- a subagent: the three-quarter test render
- this session: the two-view cutter and the consistency check

**Built**
- `build_puppet` cuts both figures into one rig (`views.front`, `views.three_quarter`; parts
  in `parts/<view>/`):
  - a three-quarter draw order
  - a face finder that doesn't assume symmetry (nose by solidity, eyes as the two best marks
    above it, pupils filled)
  - the colour rule on every limb
  - far-side three-quarter limbs judged on coverage only
- `puppet/consistency.py`, per region:
  - paint only one view has, from colour histograms
  - head size
  - turn, measured against what the skeleton asked for
- `scripts/preview_puppet.py --view three_quarter` places the character in that view, facing
  Pip.
- Bugs fixed along the way:
  - wrist outlines left on the torso (dark "sticks" at the hips after the arms hang)
  - a pupil left inside an eye's ring
  - a palette comparison that flagged the scarf and missed the hat

**Verified**
- Kit rebuilt in about 14 s with SAM (IoU 0.954 front, 0.951 three-quarter).
  - Front: all limbs pass.
  - Three-quarter: the near thigh carries a piece of tail (drift 0.64, flagged).
- Consistency on Kit: a hat (#afca70) covers 10% of the three-quarter head only, and the turn
  is 5% of what was asked. Head share matches (0.331 vs 0.342).
- Both test renders: 7 s at 1080p in about 35 s each. Kit waves, blinks and talks in both
  views, and I checked the contact sheets.
- 282 tests pass, model tests excluded. New tests:
  - two-view builds: valid rig, the far arm behind, turning the arms back reproduces each
    figure
  - SAM accepted or rejected per view
  - consistency: matching views, a hat in one view, an unturned three-quarter view
  - the preview script, 6 new tests (from the subagent)

**Front → three-quarter fallback, research only (D-051, sources in the subagent's report)**
- FLUX.2 [klein] 4B: Apache-2.0 for everything it needs, about 16.1 GB in bf16 (fp8 doesn't
  run on MPS), native ComfyUI nodes. There is no published evidence that it turns cartoon
  characters cleanly, and its speed on an M4 is unmeasured.
- Alternative: Qwen-Image-Edit-2511 Q4 GGUF with a multiple-angles LoRA (tight on memory).

**Open questions for the owner**
1. Install FLUX.2 klein 4B (about 16 GB) and trial a front → three-quarter edit of Kit, or
   keep front-only puppets for now?
2. Add the proposed animation-quality step between Steps 4 and 5?

**Cleaned up:** scratch debug images. The subagents removed their scratch films and
renders. The dev contact sheet from the three-quarter stand-in was deleted.

---

## 2026-10-22: Step 4 task 4.4 done: Kit is a rigged puppet

The owner chose candidate c3. Built in parallel:
- a subagent: the SAM 2.1 segmentation
- a subagent: the test-render script
- this session: the cutter

**Built**
- `puppet/design.py`: `choose_design` records the chosen candidate.
- `puppet/segment.py` (SAM 2.1 base+ through ComfyUI):
  - Prompts come from the skeleton: tight boxes sized by the colour key, plus points on
    the centre line.
  - fp32 only.
  - Learning note: `docs/learning/segmentation-sam2.md`.
- `puppet/build.py`: `build_puppet` cuts the chosen sheet into Pip-compatible parts:
  - silhouette: colour key ∪ SAM
  - head split by colour
  - limb corridors with a colour rule
  - face painted out, face block from the drawn marks
  - caps on the back part
  - arms turned to hang at rest
  - unmixed edges
  - writes `rig.json` (registered via `register_rig`), `palette.json`, a build report,
    debug images, and `compose()` (a PIL forward-kinematics preview)
  - learning note: `docs/learning/cutting-puppets.md`
- `scripts/preview_puppet.py` (checkpoint 3): Kit and Pip in shot `s00_sh01`. Kit rests,
  waves, blinks and speaks a Kokoro line with Rhubarb lip-sync. The script renders through
  the Synfig backend and writes a contact sheet of key frames found from the tracks.
- `motions/library.py`: the wave keeps the hand clear of the head (Kit's ears hid it). Pip is
  unchanged up to energy 0.75, and stops at 150° instead of 160° above that.
- `comfy_runs.run_graph`: a fresh save-prefix token per run. ComfyUI's cache otherwise
  answered repeated graphs with files already deleted.
- Small changes: `comfy_graphs.Graph` is public, `checks.skeleton_box` is public, and
  `required_files` lists SAM base+.

**Verified**
- Kit's build: 8 s including SAM (IoU 0.946 with the colour key).
  - All 8 limbs on their bones (worst drift 0.33 radius).
  - Face: nose kept, both eyes and the mouth found, 5 marks painted out.
  - The rig validates.
- Test render: 35–46 s for 7 s at 1080p, with audio. I checked the contact sheet frame by
  frame:
  - rest
  - a wave clear of the head
  - eyes closed on the blink
  - the mouth shapes during the line
  - Pip standing alongside
- 274 tests pass, model tests excluded, plus the live model tests (SAM, ComfyUI). New tests:
  - `test_puppet_build.py`, 7 tests on a synthetic fox: the scarf stays on the torso, the
    tail doesn't follow the leg, every pixel belongs to exactly one part, the face is
    painted out with the nose kept, the arms hang, turning the arms back reproduces the
    sheet (IoU > 0.95), and SAM is joined or rejected
  - segmentation, 5 tests
  - the preview timeline, 6 tests
  - the wave's head clearance, 1 test
- First-pass bugs found by looking at renders and fixed:
  - the arm corridors took scarf and tail
  - the paws dropped off
  - a chin cap showed on the scarf
  - fur wisps were left at the shoulders
  - a white fringe on the outline
  - the hidden wave
  - one limb's hole filling took another limb's pixels

**Open questions for the owner**
1. Checkpoint 3: does Kit look right waving, blinking and talking next to Pip? The face is
   Pip's vector face style placed on Kit's drawn features.
2. Kit's voice is a placeholder (c13, af_bella +1.5 semitones). Should we cast Kit properly?
3. The small change to Pip's high-energy wave (150° instead of 160° above energy 0.75):
   is that OK?

**Cleaned up:** scratch debug images. The two subagents removed their scratch films and files.
No ComfyUI copies were left.

---

## 2026-10-22: Step 4 task 4.3 done: `design_character` and the first candidates

**Built**
- `studio_core/puppet/design.py`: `design_character(film_root, id, description, n, seed, fast)`.
  - Each candidate is a turnaround sheet in the film's style, with a recorded seed.
  - Rounds add candidates; `candidates.json` is validated against the new `design` schema.
  - The description passes the shared word check (`studio_core/safety.py`, which `speak`
    now uses too).
- Conditioning: the OpenPose skeleton at 1.0 plus a code-drawn mannequin (`mannequin_image`
  in `skeleton.py`) as weak depth (0.4, first half of the steps). Both share one ControlNet
  loader (`comfy_graphs.txt2img`).
- `studio_core/puppet/checks.py` checks each sheet:
  - a plain background
  - figures grouped by skeleton, with holes filled
  - height and joints on the figure, listing the joints that miss
  - front arms clear of the body
  - extra shapes (props, text, shadows, clutter)
- `comfy_runs.run_graph` now deletes ComfyUI's own copies of outputs and the uploaded
  conditioning images after each run, so the film folder holds the only copy.
- `scripts/design_review.py`: generates the missing candidates (safe to re-run), frees
  ComfyUI, and writes the review page with a skeleton overlay toggle.
- Learning note: `docs/learning/controlnet-conditioning.md`.

**What the experiments showed** (scratch runs, deleted afterwards; details in D-049)
- OpenPose alone: arms rested against the body in 3 of 4 early sheets.
- Weighted face negatives (`(eyes:1.5)`): faces stayed and the arms vanished.
- Fast mode (Lightning, CFG 1): about 1–2 min instead of 4–8, but the negative prompt is
  ignored, so the sheets came back with paper texture, leaves, a signature and extra tails.
- Mannequin depth at 0.6: limbs always clear, but a wooden-doll look. 0.4 for half the steps
  keeps the style.
- The first version of the checks gave false alarms: light clothes split the silhouette.
  Grouping the pieces by skeleton and filling holes fixed it, and a sheet then fails only when
  a look at it agrees.

**Demo: Kit, "a cheerful young fox with a green scarf"** (storybook, normal mode, seeds 101–104)

| Candidate | Time | Checks | By eye |
|---|---|---|---|
| c1 (seed 101) | 267 s | pass | Arms well clear, plain background, no shadow, a closed-eye smile. The 3/4 view is barely turned. |
| c2 (seed 102) | 239 s | fail: 12 extra shapes, 75% of joints | A cluttered sheet (mini foxes, leaves) with a white body suit. Rightly rejected. |
| c3 (seed 103) | 270 s | pass | A fox in a coat, with a tail. The 3/4 view adds a small hat the front lacks. |
| c4 (seed 104) | 328 s | fail: a hand touches the tail | Arms clear otherwise. Shorts in the front view, none in the 3/4. |

- **Faces:** all four have faces (two with closed-eye smiles), so 4.4's face fill is needed.
- **Three-quarter views:** mostly a front view with a slight turn. That is task 4.5's
  problem.
- **Speed:** 10–14 s per step, with swap nearly full during the runs.

**Verified**
- 254 tests pass, model tests excluded. New tests:
  - checks on synthetic sheets drawn from the skeleton: clean, busy background, arm on hip,
    missing view, figure off the pose, light shirt, extra shape, clutter
  - the mannequin itself passes the checks
  - design rounds with a fake ComfyUI: numbering, seeds, validation, refusals, style change
  - ComfyUI copies deleted, and only this run's
  - the design schema with 4 mutation cases
- Live model test `test_one_real_candidate` (fast mode): passes, run together with `test_real_run` (123 s). ComfyUI kept no output copies, and the images uploaded for the run were deleted.

**Open questions for the owner**
1. Checkpoint 2: is the look right, which candidate (if any) should become Kit's puppet,
   and are the faces acceptable given that the build step paints them over?
2. Speed: each normal-mode sheet takes 4–8 min, partly because memory is under pressure
   (swap nearly full). Docker's VM reserves about 8 GB; lowering it is your call. There is
   also a second ComfyUI (port 8189, started by another app, "Montage") running from our
   ComfyUI install.
3. Cleanup: `~/ai-studio/scratch/` (about 510 MB from Steps 0–2, Oct 19–21) and the
   Oct 19–20 images in ComfyUI's output folder predate this task. Delete them?

**Cleaned up:** the experiments' scratch files (96 MB) and 15 images from today's runs in ComfyUI's output and input folders (4.1 smoke, 4.3 experiments, and the demo's copies from before the automatic cleanup).

---

## 2026-10-22: Step 4 started: task 4.1 (ComfyUI plumbing) done

The owner approved the Step 4 brief as written (D-047).

**Step 4 task list**

| Task | Status |
|---|---|
| 4.1 ComfyUI plumbing | **Done**: `studio_core/comfy_runs.py` (`film_style`, `make_room_for_images` with a music guard, `ensure_comfy` starts ComfyUI on demand, `run_graph` uploads, collects, renames and writes `run.json`, `free_comfy`); 5 approved models installed via the manifest. |
| 4.2 Skeleton templates | **Done**: `studio_core/puppet/skeleton.py` (Pip proportions, A-pose, front + three-quarter turnaround on 1344×768, OpenPose image and rig bones from the same joints); 7 tests: keypoints found in the image within 1.5 px, bone directions within 1°, names, roles, parents, limits and draw order identical to Pip (D-048). |
| 4.3 `design_character` (owner checkpoint 2) | **Done; owner chose c3**: `studio_core/puppet/design.py` + `puppet/checks.py`, `schemas/design.schema.json`, `scripts/design_review.py`; 4 candidates for Kit the fox (D-049). |
| 4.4 `build_puppet` (owner checkpoint 3) | **Done; approved by the owner**: `puppet/build.py` (cut, face, caps, hanging arms, rig) + `puppet/segment.py` (SAM 2.1) + `scripts/preview_puppet.py` (test render next to Pip) (D-050). |
| 4.5 Three-quarter view | **Done; FLUX.2 klein wired in (D-052, D-053)**: both views cut into one rig, `puppet/consistency.py` compares them, `preview_puppet.py --view three_quarter`. Kit's 3/4 fails the check (hat, barely turned) (D-051). |
| 4.6 `generate_background` | **Done; owner chose c4**: `place/design.py` (drafts at 1536×576, choose and finish into the 2880×1080 plate), `place/checks.py` (ground band), `comfy_graphs.finish_plate`, `scripts/background_review.py` (D-054). |
| 4.7 `split_depth_layers` (owner checkpoint 4) | **Done; waiting for the owner's review**: `place/layers.py` (DA3 depth, bands, parallax, fills), `comfy_graphs.depth_map` + `repaint_fill`, `scripts/preview_background.py` (pan test with a hole check) (D-055). |
| 4.8 `comfy_mcp` server | To do |
| 4.9 Prove it | To do |
| 4.10 Docs, Step 5 brief | To do |

**Verified**
- Downloads: ProMax ControlNet 2.34 GB, DA3 MONO-LARGE 1.24 GB and SAM 2.1 base+ 0.30 GB from
  Hugging Face, sha256-checked. Real-ESRGAN ×2 from GitHub, with hashes computed once.
- ComfyUI started on demand by `ensure_comfy` in 17 s.
- A smoke graph through `run_graph`: DA3 depth plus a Real-ESRGAN 4× upscale, in 4.5 s. The
  depth map is right even on the flat placeholder meadow: the sky farthest, the path nearest.
- API note: dynamic-combo inputs take dotted keys (`"output": "depth"`,
  `"output.normalization": "min_max"`).
- 5 plumbing tests, including a real SDXL run with its `run.json`. ComfyUI's memory was freed
  afterwards.

## 2026-10-22: Step 3 done; Step 4 brief drafted

**Step 3 in one paragraph:** the director can now make a film's sound through `audio_mcp`.
- **Voices:** characters are cast once (Pip and Bunny by the owner) and speak lines with
  automatic mouth cues. Kokoro is in use, and the Hindi voices work.
- **Music:** composed from a mood at 9.6 GB peak memory (it was 21+ GB).
- **Sound effects:** found by description among 4,268 CC0 sounds, with CLAP in Qdrant and a
  hybrid ranking.
- **The mix:** shots get a full mix (ducked music, −14 LUFS, true-peak safe).
- **The done-when shot** was built only through MCP tool calls and approved by the owner.

**Owner decisions this step:** the brief (D-036), the casting (D-039), the music samples, the
Indian voices (D-042; Parler download deferred), FSD50K's CC0 clips (D-044), the done-when shot
(with the birdsong fix).

**Verified:** see the task table above. The full suite passes (229 tests, ~3 min), with the
`models` tests running Kokoro, Rhubarb, ACE-Step and CLAP. The Inspector check covers both
servers, 32/32.

**Next**
- Owner: review the Step 4 brief (`comfy_mcp`: puppets and backgrounds from text).
- Open: Step 2's Claude Code run (D-035); 3.2b's Parler download when the owner logs in to
  Hugging Face.

## 2026-10-22: Step 3 started: tasks 3.1–3.4 (schemas, voices, lip-sync, music) done

The owner approved the Step 3 brief as written (D-036).

**Step 3 task list**

| Task | Status |
|---|---|
| 3.1 Audio schemas and file layout | **Done**: `schemas/voice`, `line`, `lipsync`, `music`, `sfx_library`; shot schema gains `sfx[].sound` and `music_volume`; semantic checks (cue order and coverage, unique voices, sounds and audio, line/voice consistency); asset checks in `shot_spec` (line metadata, stale mouth cues, chosen sounds in the library, music cues exist); `studio_core/audio/library.py` (manifest loader); files named by id recognized by folder in `validate_file` (D-037). |
| 3.2 Voices: `speak` (owner checkpoint 2: casting) | **Done; cast by the owner** (Pip c12, Bunny c03, D-039): `studio_core/audio/voices.py` (text checks, content-hash cache, one Kokoro batch per call, trim + pitch step + linear-gain loudness, line metadata, stale cues removed), `studio_core/audio/ffmpeg.py`, `scripts/audio/kokoro_batch.py`, 4 casting voices fetched; casting page `scripts/audio/voice_casting.py` (14 candidates × 2 lines) (D-038). Note: `docs/learning/voices-and-loudness.md`. |
| 3.2b Indian voices (Indic Parler-TTS, D-042) | **In progress**: `envs/parler` (pinned; audiotools/protobuf overrides), `scripts/audio/parler_batch.py`, voice.json `engine: parler` + `language` + `speaker`/`pitch`, Parler descriptions written by code, a seed per line, engine dispatch in `speak`, Devanagari text, recognizer by language; Kokoro's 4 Hindi voices work end to end (phonetic cues). **Deferred by the owner (2026-10-22): planned later** together with the Hugging Face login that the gated weights (3.75 GB) need. |
| 3.3 Lip-sync: `lipsync` | **Done**: `studio_core/audio/lipsync.py` (Rhubarb on the final audio with the text, recognizer by language, cache by validity and length, relative `soundFile`, parallel lines); `speak` lip-syncs by default (D-040). Note: `docs/learning/lip-sync.md`. |
| 3.4 Music: `compose` (owner checkpoint 3) | **Done; samples approved by the owner (checkpoint 3, 2026-10-22)**: memory fixed in place (bf16 + PyTorch DiT and VAE only): **21.0 → 9.6 GB** peak for a 10 s cue, no swap, flat to 60 s; `studio_core/audio/music.py` (9 moods, instrument list, caption in code, seeded, cached by hash, Ollama unloaded and ComfyUI refused first, peak footprint measured per cue, trimmed + faded + −20 LUFS); samples page `scripts/audio/music_samples.py` (D-041). |
| 3.5 Sound-effect library and search: `find_sfx` | **Done**: 8 Kenney + 10 OpenGameArt CC0 packs + FSD50K's CC0 eval clips (owner-approved, child-safe filter) → **4,268 sounds, 9.6 h**; BigSoundBank left out per its robots.txt; CLAP in Qdrant with hybrid ranking; spot-check 24/24; remaining gaps: cows, a cartoon boing, a slide whistle (D-043, D-044). Note: `docs/learning/embeddings-and-vector-search.md`. |
| 3.6 The mix | **Done**: `studio_core/audio/mix.py` (dialogue/sfx/music buses, sfx normalization, computed ducking envelope, −14 LUFS gain, 4×-oversampled limiter with a true-peak check), `[mix]` config, `render_shot` writes `mix.wav`; tests measure ducking (−10 dB ± 0.5), sound timing (±10 ms) and loudness (±1 LU, ≤ −1 dBTP) (D-045). |
| 3.7 `audio_mcp` server, and shot tools for sound | **Done**: `mcp/audio_mcp` (7 tools: describe_audio, set_voice, speak, lipsync, compose, find_sfx, preview_mix); `synfig_mcp` gains add_sound_effect, set_music, sound-effect removal, music cues in describe_film; tests through real MCP clients (in-process + stdio, with and without models); Inspector check over both servers 32/32 (D-046). |
| 3.8 Prove it (owner checkpoint 4) | **Done; approved by the owner (checkpoint 4)**: `scripts/run_step3_shot.py` builds the done-when shot with a scripted MCP client over both servers (launched from `.mcp.json`): 27 calls, 109 s. Pip and Bunny speak in their cast voices with mouth cues, plus composed music, birdsong found by description, and a 1080p render. All 6 checks pass (−14.8 LUFS, −1.5 dBTP); transcript `docs/learning/mcp-step3-shot.md`. The owner's note (traffic in the chosen birdsong) was fixed with `find_sfx(avoid=...)` and the shot re-rendered. |
| 3.9 Docs, Step 4 brief | **Done**: Step 3 brief checklist ticked; learning notes (voices and loudness, lip-sync, embeddings and vector search, the memory hunt, MCP with two servers); MODELS (Kokoro voices, CLAP, the sound library); Step 4 brief drafted for review. |

**Verified**
- 186 tests pass (`uv run pytest`); ruff is clean.
- Every schema has a valid example. The lip-sync example is the real Rhubarb output from Step 0.
- 24 new mistake cases are each reported at the right path, e.g. a non-CC0 license
  (`sounds[0].license: 'CC0-1.0' was expected`) and a gap between mouth cues.
- Asset checks are tested on a film folder:
  - a line recorded in another character's voice
  - mouth cues made for a shorter take ("run lipsync on it again")
  - an unchosen sound (a warning)
  - an unknown sound id, a broken manifest and a missing music cue (errors)

**Task 3.2 (same day)**
- `speak` works end to end in a scratch film:
  - two lines at −20.0 and −19.9 LUFS (target −20), with true peaks −3.7 and −5.0 dBTP
  - a repeat request is a cache hit in 0 s, even with different spacing
  - `regenerate` makes take 2 and removes stale cues
- 9 voice tests:
  - text checks, the hash, line ids, load errors and refusals (nothing is synthesized when a
    request is refused)
  - synthetic tones: a +2 semitone step lands within 2% of 493.9 Hz and keeps the length within
    30 ms; the trim keeps 80/120 ms of air; the linear gain reaches −23 LUFS within 0.3 LU
  - one real Kokoro run (`-m models`)
- Casting page: 28 takes in 25 s, 1.6 MB self-contained HTML. All 28 embedded clips decode.
- The owner cast Pip as c12 and Bunny as c03 (D-039). Their `voice.json` files are in the
  fixtures, and the demo film now has Bunny.

**Task 3.3 (same day)**
- Rhubarb on the Step 0 fixture line reproduces the fixture's 34 cues exactly. It took 6.3 s,
  and the repeat call is a cache hit.
- End to end: `speak` in Pip's cast voice → cues → `add_dialogue` → the shot passes every check,
  with no errors and no warnings.
- 200 tests pass; ruff is clean. The suite now takes ~60 s, because the `models` tests run
  Kokoro and Rhubarb. Skip them with `-m "not models"`.

**Task 3.4 (same day)**
- Memory hunt (measured, `docs/benchmarks.md`), 10 s cue:
  - fp32 (ACE-Step's MPS default): 21.0 GB, 5.7 GB swapped
  - bf16: 18.6 GB
  - bf16 + PyTorch VAE: **9.6 GB, no swap**
- PyTorch's own numbers (6.9 GB allocated) showed that ~10 GB lived elsewhere: a second,
  float32 MLX copy of the VAE that ACE-Step builds on Macs. Option (b), ComfyUI with a 6.3 GB
  download, wasn't needed. Note: `local-inference-on-apple-silicon.md` (worked example).
- The fix holds at 30 s (9.6 GB) and 60 s (9.7 GB). Generation takes 6 / 14 / 25 s.
- `compose` test (`-m models`): a 10 s cue within the budget, normalized, with valid metadata.
  The repeat call is a cache hit.
- Music samples: 3 moods × 2 takes, 15 s each, 130 s in all. Every take peaked at 9.6 GB and
  measured −20 LUFS, true peak ≤ −1.5 dBTP. All 6 embedded clips decode.
- 206 tests pass (~90 s with the `models` tests); ruff is clean.
- Next: the owner reviews the samples (checkpoint 3), then 3.5 (the sound-effect library and
  `find_sfx`).

**Task 3.2b (part 1) and 3.5 (same day)**
- 3.2b, Indian voices: the Parler engine is built and tested without its weights. Kokoro's 4
  Hindi voices work end to end with phonetic cues. The Parler download waits for the owner's
  Hugging Face command-line login, which the owner chose to do later.
- 3.5, sound-effect library:
  - Sources: Kenney (581 sounds) and OpenGameArt (174), all CC0, with a children's name filter.
  - BigSoundBank is left out: its robots.txt forbids robots on its audio.
  - CLAP in Qdrant with hybrid ranking. The keyword half was needed: pure vectors ranked dice
    above tagged footsteps.
  - The spot-check passes 15/15. **Gap: animal sounds** (and real rain). The approved optional
    fix, FSD50K's CC0 eval clips (6.2 GB), waits for the owner's decision.
- 216 tests pass (~2 min with the `models` tests); ruff is clean.

## 2026-10-22: Step 2 closed (task 2.9); Step 3 brief drafted

**Done**
- `docs/learning/mcp.md`:
  - what the Inspector showed (docstring indentation reaching the model, validation before our
    code runs, error and result shapes)
  - how a tool schema reaches the model
- `docs/learning/motion-library.md`: keyframes and curves (pose-to-pose, interpolation types),
  overlap and follow-through as the code does them, and why `energy` is a parameter (with the
  wave's numbers).
- `docs/steps/STEP-2-synfig-mcp.md`: status and done-when checklist updated. Every item is met
  except the Claude Code run (D-035).
- DECISIONS: nothing new. The brief's list (shot spec as source of truth, motion composition,
  face design, changes) is covered by D-028, D-029 and D-033–D-035.
- **Step 3 brief drafted:** `docs/steps/STEP-3-audio-mcp.md` (voices, lip-sync, music, sound
  effects with CLAP + Qdrant, the mix). Not started.

**Next**
- Owner: review the Step 3 brief, its proposed decisions and its installs.
- Agent, after approval: task 3.1 (audio schemas).

## 2026-10-21/22: Step 2 task 2.8 done: the Inspector and Claude Code as clients

**Done**
- `.mcp.json` (repo root) registers `synfig_mcp` for Claude Code and the Inspector.
- `scripts/inspector_check.py` drives the MCP Inspector CLI (pinned 2.9.0) through every tool,
  plus 3 calls that must be refused, on a scratch film `films/inspector-check/`.
- Tool descriptions are now cleaned of docstring indentation; the Inspector showed the raw
  indentation reaching the model. A test guards it.
- `scripts/run_first_shot.py`: the done-when run. It runs Claude Code headless with only our 14
  tools on a fresh film `films/first-shot/`, saves the transcript to
  `docs/learning/mcp-first-shot.md`, and checks the result against the done-when.
- `docs/learning/mcp.md`: sections on the Inspector and Claude Code as the client (D-035).

**Verified**
- Inspector: `tools/list` shows the 14 tools, and all 18 calls did what was expected (19/19 with
  the list). Edits, `build_rig`, a preview frame and a 640x360 render worked. The refusals
  (unknown motion, unknown bone, unknown character) came back as `isError` with fixable
  messages. The preview PNG was checked by eye: Pip at x=0.4, mid-wave and talking.
- `claude mcp list` sees the server ("Pending approval": project servers need the owner's OK in
  an interactive session).
- Headless `claude -p` with `--mcp-config .mcp.json --strict-mcp-config --tools ""`: the server
  is `connected` with 14 tools and no built-in tools.
- The done-when checks pass on the hand-written demo shot and fail on an empty film.
- 150 tests pass; ruff is clean.

**Skipped by the owner (2026-10-22): the Claude Code done-when run**
- The run needs the standalone `claude` CLI logged in, and the owner couldn't log it in. Every
  shell the app reaches (the agent's, sandboxed or not, and the Terminal panel) reports
  `loggedIn: false`.
- From inside a Claude Code session, the child `claude` also inherits the session's auth proxy
  and fails with "OAuth session expired". The script now drops those variables and checks the
  login first, so it fails with a clear message.
- **Open done-when item:** "From Claude Code as an MCP client, the LLM builds and renders a
  10-second shot". To close it later, run `uv run scripts/run_first_shot.py` in any terminal where
  `claude auth status` says `loggedIn: true`. It writes `docs/learning/mcp-first-shot.md` and the
  checks. Otherwise, Step 5's director (a local LLM driving these same tools) proves it.

**Notes**
- Inspector 2.9 asks for Node ≥ 22.19 (installed: 22.13.1). It works with warnings. Upgrading
  Node is not in the brief, so it was left alone.

## 2026-10-21: Step 2 task 2.7 done: the `synfig_mcp` server

**Done**
- `studio_core/shot_spec.py` (engine-neutral): the director's verbs as functions that edit
  `shots/<id>/shot.json`. Every edit re-checks the whole spec (schema, semantic rules, the film's
  assets, a dry run of the motion library) and saves nothing if it fails.
- `mcp/synfig_mcp/` (uv workspace member `synfig-mcp`, `mcp` 2.3.0, stdio). 14 tools:
  - read: `describe_film`, `describe_shot`
  - edit: `create_scene`, `add_character`, `apply_motion`, `pose_at`, `set_expression`,
    `apply_lipsync`, `add_parallax_background`, `camera_move`, `remove_from_shot`
  - characters: `build_rig`
  - render: `render_preview_frame`, `render_shot`
- Differences from the brief's tool table, and why: D-034.
- `studio_core/shot.py` gained `render_preview` (one frame → `shots/<id>/preview.png`) and an
  `audio` switch.
- The demo film now has the line's transcript (`audio/dialogue/l001.txt`).
- Note: `docs/learning/mcp.md` (a first version; 2.9 extends it).

**Verified**
- 150 tests pass (`uv run pytest`); ruff is clean. The new MCP tests use the SDK's real client:
  - all 14 tools are listed with descriptions and enums, and no tool schema names an engine
  - a 10-second shot is built step by step (motions, expression, lip-sync, a pose, a camera move),
    and `describe_shot` returns the expected spec with no errors or warnings
  - refusals come back as `is_error` with fixable messages (unknown film, background, motion,
    bone; a character not in the shot; an index out of range; a hand-broken spec refused before
    rendering)
  - `render_preview_frame` (192x108 PNG) and `render_shot` (24 frames at 640x360) work
  - the server starts over stdio and lists its tools
- 12 unit tests for the spec editor.

**Next**
- 2.8: list and call the tools from the MCP Inspector, then build and render the done-when shot
  from Claude Code as the client (`.mcp.json`), and save the transcript.

## 2026-10-21: Step 2 task 2.6 done: placement, parallax, camera and shot assembly

**Done**
- `studio_core/scene.py`: background layers as parallax planes, a characters plane (factor 1),
  in-front layers, a camera group with eased presets (`static`, `slow_pan_left/right`, `push_in`,
  `pull_out`) and a solid backdrop. Built at the 1920x1080 design size and rendered at any size.
- `schemas/background.schema.json` (`layers.json`) and a placeholder meadow with 4 layers
  (`scripts/make_placeholder_background.py` → `tests/fixtures/backgrounds/meadow/`).
- A character's `position` now means the point between its feet (`rig.ground_offset_px`, D-033).
- `studio_core/shot.py`: `shot.json` → `scene.sif` → frames → `shot.mp4`, with expression and
  lip-sync tracks per character and the dialogue mixed in at each line's start. `animate` takes
  manual key `poses`.
- `scripts/make_demo_film.py`: builds `films/step2-demo/` from the fixtures and renders shot
  `s01_sh01` (Pip waves, blinks and speaks line l001 in the meadow during a slow pan).
- Notes: `docs/learning/parallax-and-camera.md`; `motion-library.md` covers key poses.

**Verified**
- 132 tests pass (`uv run pytest`); ruff is clean. Render tests:
  - each layer slides by -pan x parallax, within 1 px
  - `push_in` widens a stripe x1.25
  - zoom 0.5 leaves no transparent pixel
  - a character lands within 1.5 px of its position: body centre on x, lowest pixel on y
  - `render_shot` end to end: 48 frames, plus a video and an audio stream
- The demo shot at 1080p: 240 frames in 55 s (~0.23 s/frame), 1.1 MB MP4. Checked on a contact
  sheet:
  - Pip's feet are on the path at y≈0.92.
  - Pip and the meadow move together during the pan; the hills and sky move slower.
  - The left arm waves, and the mouth changes while talking.
  - Speech is audible from 1.8 to 6.6 s (the line starts at 1.5 s; the WAV has a short lead-in).

**Not done**
- Sound effects and music are not mixed into `shot.mp4` yet (Step 3).
- Placement is fixed per shot. Walking across the frame needs a moving placement and side-view art.

**D-030 (landed during this task)**
- **Schema audit done:** none of the five schemas has an engine-specific field. Two descriptions
  named Synfig internals and were reworded (D-033).
- `scene.py`, `shot.py`, `sif/`, `rig.build_character` and the face layers are Synfig-specific, and
  the motion tracks use Synfig value types. ROADMAP Step 6 already schedules moving them under
  `studio_core/engines/synfig/` behind a backend interface, with no behavior change. So there's no
  extra Step 2 task. 2.7 keeps the MCP tools engine-neutral: they edit shot specs and call
  `render_shot(film, shot_id)`, never `.sif` details.

**Next**
- Agent: 2.7 (`synfig_mcp` server).
- Owner (optional): say so if you'd rather do the `engines/` move before 2.7 instead of in Step 6.

## 2026-10-21: Engine strategy decided (planning session)

**Done**
- OpenToonz spike finished: `docs/spikes/opentoonz.md` and three scripts in `scripts/spikes/`.
  Python-generated `.tnz` scenes render headless, and Plastic works from code. The Tahoma2D
  evaluation was stopped at the owner's request (notes are in the report's appendix). Spike
  leftovers were moved to the Trash. `~/Applications/OpenToonz.app` and
  `~/ai-studio/tools/opentoonz-stuff` were kept.
- The owner approved three decisions:
  - **D-030:** engine-neutral scene model, with engines as backends
  - **D-031:** OpenToonz is the strategic engine, and Synfig ships the first film
  - **D-032:** final rendering runs server-side in stateless containers
- ROADMAP: a new **Step 6, OpenToonz backend + render containers**. The old Step 6 (level up) is now
  Step 7, and its references were renumbered.
- ARCHITECTURE and the CLAUDE.md conventions were updated to match. D-001 (fully local) is unchanged.

**Impact on the current step**
- Step 2: audit the schemas for Synfig-specific fields and move any into the Synfig backend (D-030).
  Keep MCP tool names and arguments engine-neutral.

**Open question for the owner**
- Product delivery: hosted web app, desktop app, or both. This decides D-001's future and whether
  the web-preview backend is needed.

## 2026-10-21: Step 2 started: task 2.1 schemas done, waiting for owner review

The owner approved the Step 2 brief as written (D-028).

**Step 2 task list**

| Task | Status |
|---|---|
| 2.1 Schemas | **Done, approved by the owner (checkpoint 2, 2026-10-21)**: `schemas/rig`, `shot`, `shotlist`, `film`; `studio_core/schema.py` (schema + semantic checks with fixable messages); `scripts/validate.py`; valid examples in `tests/fixtures/schemas/`; 27 tests of specific mistakes; `film.json` now validated on save. Learning note: `docs/learning/json-schema.md`. |
| 2.2 Rig model + validator | **Done**: `studio_core/rig.py` (load + validate rig.json, bones from rest directions and joint pixels, flat bone-linked parts in draw order, skeleton layer, FK `world_pose`, `clamp_offset`); `studio_core/sif/validate.py` runs before every render (bones first, links complete, GUIDs resolve, no duplicates, images exist); placeholder **Pip** with a faceless head, both arms and two-segment legs (`tests/fixtures/characters/pip/`, `scripts/make_placeholder_character.py`). A render test lands parts within 1.5 px of FK. Note: `docs/learning/rigging.md`. |
| 2.3 Vector shapes in the builder | **Done**: `studio_core/sif/shapes.py` (splines with Hermite tangents, smooth/ellipse/arc helpers, region, outline, polygon); render tests measure ellipse and triangle areas within 1%. Found: `bgcolor` doesn't paint renders (transparent → black in MP4), so scenes need a background layer. |
| 2.4 Procedural face | **Done**: `studio_core/face.py` (eyes with open/half/closed and `blink_track`, brows for 6 expressions, Rhubarb mouths A–H + an expression-aware rest X), attached to the head bone via `build_character(attachments=...)`; render test: the face turns with the head (±1.5 px); preview sheet `scripts/preview_face.py`. |
| 2.5 Motion library (owner checkpoint 3) | **Done, approved by the owner (checkpoint 3, 2026-10-21)**: `studio_core/motions/` with 9 motions (idle_breathe, blink, wave, nod, head_tilt, walk_cycle, jump, point, talk_gesture), energy/side/cycles/duration/target params, per-bone override + additive composition, joint-limit clamping, root and joint shifts (`build_character(shifts=...)`); 22 tests (timing, composition, determinism, a rendered jump rising 160 px); preview video `scripts/preview_motions.py`. Bone `role` added to the rig schema (D-029). Note: `docs/learning/motion-library.md`. |
| 2.6 Parallax + camera | **Done**: `studio_core/scene.py` (parallax planes, camera presets, backdrop, feet placement), `schemas/background.schema.json` + placeholder meadow, `studio_core/shot.py` (spec → `scene.sif` → `shot.mp4` with dialogue), key poses, demo film `scripts/make_demo_film.py`; render tests for parallax rates, zoom, placement and the full shot (D-033). Note: `docs/learning/parallax-and-camera.md`. |
| 2.7 `synfig_mcp` server | **Done**: `mcp/synfig_mcp/` (workspace member, `mcp` 2.3.0, stdio, `uv run synfig-mcp`) with 14 tools over the engine-neutral editor `studio_core/shot_spec.py`; 18 tests, including a real client in-process and over stdio, fixable errors and renders (D-034). Note: `docs/learning/mcp.md`. |
| 2.8 Prove it from the Inspector and Claude Code | **Done, except the Claude Code run (skipped by the owner)**: Inspector check (`scripts/inspector_check.py`, 19/19 as expected); `.mcp.json`; headless Claude Code connects with only our 14 tools; the done-when run `scripts/run_first_shot.py` is ready but not run, because the CLI login isn't available (D-035). |
| 2.9 Docs, Step 3 brief | **Done**: `mcp.md` (the Inspector's findings, how a tool schema reaches the model), `motion-library.md` (keyframes and curves, follow-through, why energy is a parameter); Step 2 brief checklist ticked; Step 3 brief drafted for review. |

**Verified:** 75 tests pass (`uv run pytest`). The four example files validate; each mistake
case is reported at the right path.

**Open questions for the owner (checkpoint 2: schema review)**
- Are the motion list (9), expressions (6), camera presets (5), the 4-characters-per-shot and
  60 s-per-shot limits, and fps options {12, 24, 25, 30} right for v1?
- Rig convention: rest pose = the art as drawn, `direction_deg` per bone, joints attached at a
  pixel of the parent's part, and draw order separate from the hierarchy. OK?

---

## 2026-10-21: Step 1 done; Step 2 brief drafted

**Done**
- **Rig technique decided by the owner (D-027):** bones for characters, nested groups for
  scene layout (placement, camera, parallax, props).
- **Step 1 done-when is all ticked** (`docs/steps/STEP-1-synfig.md`). The hand-built scenes
  were replaced per D-026 (GUI-saved official example rigs, plus the scene generated both ways).
- **Step 2 brief drafted:** `docs/steps/STEP-2-synfig-mcp.md`. It covers schemas, the rig model
  with a validator, vector shapes for the procedural face, the motion library, parallax and
  camera, the `synfig_mcp` server (12 tools over stdio), and tests from the MCP Inspector and
  from Claude Code as a client.

**Verified**
- 48 tests pass (`uv run pytest`), including real Synfig renders. `uv run scripts/sif_demo.py`
  renders the waving, lip-syncing puppet with both rig techniques; the frames match.

**Next**
- Owner: review and approve (or edit) the Step 2 brief. It proposes a few decisions to confirm:
  - The shot spec JSON is the source of truth; `scene.sif` is regenerated from it.
  - Motion composition: overrides per bone, plus additive idle motions.
  - A vector face.
  - Installs: `mcp` 2.x, `jsonschema`, and the MCP Inspector via npx.
- Agent, after approval: Step 2 task 2.1 (schemas), then owner checkpoint 2.

**Open questions for the owner**
- Approve the Step 2 brief, including its installs and proposed decisions.

---

## 2026-10-20: Step 1 started (Synfig by hand + .sif generator)

The owner approved the Step 1 brief ("yes begin").

**Step 1 task list**

| Task | Who | Status |
|---|---|---|
| 1.0 Install Synfig Studio GUI | Owner | **Done**: installed 2026-10-20, opens (doctor OK) |
| 1.1 Hand-made scene, rigged with groups and with bones | Owner | **Replaced (D-026)**: the owner asked the agent to do it; GUI-saved official example rigs were surveyed and the scene was generated in both rig variants |
| 1.2 `docs/learning/synfig-format.md` | Agent | **Done**: canvas, units, layers, measured group transform and interpolation curves, switch layers, bones and Skeleton Deformation (verified by render tests), what the GUI writes vs what the CLI needs, gotchas. |
| 1.3 `studio_core/sif/` builder | Agent | **Done**: units, typed values and waypoints, import/group/switch/rectangle/circle layers, **bones, bone links and skeleton layer**, deterministic XML, render and encode helpers, Rhubarb cues → mouth waypoints. |
| 1.4 Tests | Agent | **Done**: 48 tests, including real Synfig renders that check the pivot rotation, switch timing, and bone rigs (hand-written and builder-made) against forward kinematics in pixels (`-m render`). |
| 1.5 Demo → MP4 | Agent | **Done and verified**: `uv run scripts/sif_demo.py` builds a waving, nodding, lip-syncing bunny over a panning background, **rigged with groups and with bones**; both render 168 frames at 1080p with the voice line, and match (worst PSNR 97 dB). About 22 s for both. |
| 1.6 Docs: rig decision, Step 2 brief | Agent | After the owner's scenes (checkpoint 2) |

**Verified facts worth knowing** (details in `docs/learning/synfig-format.md`)
- Group transform: `parent = offset + R(angle) · scale · (local − origin)`, angles CCW in degrees,
  y up. Measured by rendering.
- Interpolation names in files: `halt` = ease, `linear`, `clamped` (default), `constant`, `auto` =
  TCB. Measured curves: `halt` stops at every waypoint; `clamped` carries speed through.
- Switch `layer_name` changes are frame-exact; `end-time` is inclusive; times written as frames.

**Next**
- Owner: confirm the rig technique (checkpoint 2, below).
- Agent: record it in DECISIONS.md, then draft the Step 2 brief (`synfig_mcp`) for review.

**Open questions for the owner**
- **Checkpoint 2 (rig technique):** the agent's evidence-based recommendation is **bones for
  characters, nested groups for scene-level transforms**. Bones give draw order independent of the
  hierarchy (far arm behind the body) and image bending; render speed and output are the same
  (the demo renders both). Cost: ~1.4–1.9x the XML and GUID bookkeeping, all in tested code.
  See "Rig technique" in `docs/learning/synfig-format.md`.

---

## 2026-10-19 (evening): Step 0 complete: environment set up, verified and benchmarked

**Done and verified** (`uv run scripts/doctor.py` → `ALL GREEN`, exit 0: 38 OK + 1 DEFER with ComfyUI running; with it stopped, ComfyUI shows as an on-demand DEFER)
- **Tools:** uv 0.13.1, Python 3.12.15 (uv-managed), Synfig 1.5.5 CLI (Homebrew formula, native
  arm64, D-014), MLT `melt` 7.42.0, Rhubarb 1.14.0 (x86_64 under Rosetta, D-022), Kdenlive 26.08 and
  Krita 5.3.4 (notarized, Gatekeeper accepts them), ffmpeg 9.0.2. vtracer vectorized a test frame.
- **Services:** Qdrant v1.19.2 via `infra/docker-compose.yml` (round-trip verified). **Ollama now
  runs as a Homebrew service** (`sh.brew.ollama`, D-023). ComfyUI v0.42.1 starts with
  `scripts/comfy_server.sh`.
- **Models** (all in `docs/MODELS.md` with licenses; everything in the default pipeline is
  commercial-OK): qwen3:14b, gpt-oss:20b, qwen3-vl:8b-instruct (+ the thinking tag), SDXL Base 1.0
  + StoryBook LoRA + SDXL-Lightning 8-step + fp16-fix VAE, SAM 2.1 small, Depth Anything V2 Small,
  Kokoro-82M, ACE-Step 1.5.
- **Smoke tests:** Synfig renders a hand-written cut-out scene to MP4; melt renders a color clip +
  voice to MP4; Kokoro voices a line; Rhubarb produces mouth cues for it (fixtures in
  `tests/fixtures/audio/`); ACE-Step produces 30 s of music; ComfyUI runs SDXL (normal and
  Lightning), SAM 2 and depth through its HTTP API (a flat kids'-book rabbit, its mask, its depth).
- **Tool calling:** qwen3:14b 5/5; gpt-oss:20b 3/5 first try, 4/5 after a validation-error retry.
  Provisional director pick: qwen3:14b with thinking off for tool calls (D-024).
- **Benchmarks:** every stage in `docs/benchmarks.md`, with a summary table and a rough 30–40 min
  estimate for a 60 s film on the Mac alone.
- **Style switcher** (owner request, D-019 → D-025): all three candidates downloaded and
  license-checked. Styles in `config/models.toml`:
  - `storybook` (A, **default**, commercial yes)
  - `dreamshaper-lightning` (B, commercial **unclear**)
  - `animagine` (C, commercial yes, `safe` tag always)
  - `cutecartoon` (bonus)
  `studio_core.comfy_graphs.txt2img(style, ...)` builds the ComfyUI workflow from a style.
  `studio_core.film` locks a film's style once it has characters (`StyleLockedError`); tested.
  Side-by-side samples (character fast/normal + background per style) with timings are in
  benchmarks.md; the image grid is at `~/ai-studio/scratch/style-compare/grid.png` (not
  committed: generated media). Animagine breaks with the Lightning LoRA, so its fast variant
  uses 16 of its own steps.
- **Docs:** DECISIONS D-014..D-024; learning notes on Apple Silicon inference, model licenses and
  tool calling; Step 1 brief drafted.
- **Commits:** small commits on `main`, pushed to `origin/main` by the parent session through
  `d693aee` (open question 1).

**Problems found (documented, not hidden)**
- **ACE-Step 1.5 overuses memory:** ~30 GB process footprint (float32 on MPS, plus a second MLX copy
  of the DiT), free memory down to 0–1% and up to 13 GB of swap for one 30 s cue. Step 3 must fix
  this before music runs inside a pipeline (D-020 lists options).
- **ACE-Step's language model** (3.8 GB) was meant to be skipped but the library refuses to start
  without it; it is installed and unused (D-020).
- **GPU benchmarks were contaminated** by the owner's Montage app, which kept `qwen2.5:7b` loaded in
  Ollama and calling it every 10–20 s. SDXL timings are upper bounds. Re-run on a quiet machine:
  `uv run scripts/benchmark.py sdxl` (and `llm`, `music`).
- **gpt-oss:20b invents enum values** in tool calls; the director must validate every call.
- **The network was slow** (~3 MB/s) for the first ~2 hours, then fast (~30 MB/s). A network blip
  made Ollama restart one 9 GB download and Homebrew fail Krita once (retried fine).
- **Not done by the agent on purpose:** launching Kdenlive and Krita for the first time (macOS shows
  its "downloaded from the internet" confirmation, which is the owner's to click) and installing
  the Synfig Studio GUI (unsigned, Gatekeeper; owner installs at Step 1).

**Next**
- Owner: review and approve (or edit) `docs/steps/STEP-1-synfig.md`.
- Owner: open Kdenlive and Krita once and accept the first-launch prompt; install Synfig Studio
  from `~/ai-studio/downloads/synfig-1.5.5/SynfigStudio-1.5.5.dmg` (Privacy & Security → Open
  Anyway), then remove the `[doctor] deferred` entry in `config/studio.toml`.
- Agent, after approval: Step 1 tasks 1.2–1.6.

**Open questions for the owner**
1. **Push (resolved):** on your instruction "keep everything committed in this repo", the parent
   session pushed all Step 0 and style commits to `origin/main` (through `d693aee`). CLAUDE.md now
   says to commit and push after each verified task (`github-5889` alias, never force-push). If you
   want this session to push its own commits too, just confirm once here.
2. **Default style:** `storybook` stays the default. Pick another for a film with
   `Film.create(..., style)`; it locks once characters exist. `dreamshaper-lightning` is
   commercial-unclear and should not be used for published films.
3. **Step 1 rig technique** (nested groups vs Synfig bones) is decided after you build the scene;
   the brief asks you to rig it both ways.
4. **Disk:** the thinking variant `qwen3-vl:8b` (6.2 GB) is kept for comparison; delete it with
   `ollama rm qwen3-vl:8b` if you prefer.
5. **Montage app:** it uses Ollama continuously. Fine for normal work, but stop it during
   benchmarks and long pipeline runs (24 GB holds one big model at a time).

**How to re-check this machine**
```
uv run scripts/doctor.py                     # everything green?
docker compose -f infra/docker-compose.yml up -d
scripts/comfy_server.sh && uv run scripts/comfy_smoke.py
uv run scripts/smoke_engines.py all --wav tests/fixtures/audio/pip_line_01.wav
```

---

## 2026-10-19: Project planned and handed off

**Done**
- Project folder and planning docs created: CLAUDE.md, README, ARCHITECTURE, ROADMAP, DECISIONS,
  MODELS, Step 0 brief, `.gitignore`.

**Known machine state (Mac)**
- Installed: Homebrew, Node 22.13, ffmpeg, Ollama 0.40.6, Docker 28.3, Git 2.50.
- Missing: uv, Synfig, Krita, Kdenlive, MLT `melt`, ComfyUI, Rhubarb.
- System Python is 3.15. Use uv + Python 3.12 for everything (D-009).
- ~717 GB free disk.

- Git repository initialized on `main`, pushed to `git@github-5889:swapnilshah5889/animation-studio.git`.

**Next**
- Agent: start Step 0, task 0.1 (doctor script). Commit and push after each verified task.

**Open questions for the owner**
- None yet. Image checkpoint choice comes up during Step 0, task 0.5.
