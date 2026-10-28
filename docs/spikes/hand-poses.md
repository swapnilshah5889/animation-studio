# Spike: swappable hand poses (4B)

Script: `scripts/spikes/hand_poses.py`. Sheets (git-ignored): `renders/spikes/hand-poses/sheet-ac.png`
(A and C), `sheet-b.png` (B, both seeds), `results.json`, `work/` (klein edits).

**Scope as run.** Kit, Bo and the girl in the yellow raincoat (`child`; there is no Mia in
`films/step4-cast`), the image-left arm only, four poses (fist, point, open, wave). Every variant is
pasted at the same wrist point under the same forearm stub, so tiles compare. The wrist row is
hand-picked per character (`WRIST`); production would take it from the fitted skeleton. The part's
place on the sheet is found by an exact masked match (rms colour error 0). Tiles are at part
resolution (native scale, roughly what a 1080p frame shows); I judged them at that size, not
animated, and not in the Synfig render.

## What each way looks like (as rendered)

- **A procedural** (cut hand squashed/stretched/rotated). Fastest, but it only moves pixels. Kit's
  paw: fist and open read as a paw of a slightly different size, not as different hands; the point
  (narrow and long) is an elongated paw, not a finger. The wave rotates the hand about its bbox and
  leaves a hard diagonal cut at the wrist on all three. Bo has no hand at all (the arm ends in a
  round tip), so there is nothing to vary: the variants are a longer or wider stump. The child's cut
  hand is ~40 px, and the cut includes a stray cuff piece. **Does not read as a pose. Reject.**
- **B AI redraw** (klein edit of a 200 px sheet crop around the hand, upscaled to 768, 4 steps).
  *Kit: very good.* All 8 results are real fist / point / open / wave hands in Kit's dark-brown
  flat style with a clean outline, on-model by eye in 8 of 8. Two flaws: klein drew a tan cuff at the
  wrist (Kit has none, so it needs removing or the forearm re-cut), and the hands are about 1.5 times the
  cut paw and angled, so each needs scaling and a rotation fit. *Bo and the child: failed in this
  setup.* Bo's arm hangs against the body and the child's against the legs and a cream background,
  so the colour key cut out the body or the background, not a hand (the tiles show the body, a belly
  and trousers). The redraws themselves looked fine for Bo (a fist, a pointing hand, a waving hand are
  in the crops), but cutting them out needs a mask, not the colour key: SAM, or redrawing with the
  arms held out against plain background as the 3/4 turn does (`puppet/turn.py`). I did not try either.
  The uncut redraws were not viewed on their own, so on-model is not judged for Bo and the child.
  Cost: **137 s per hand on average (84 to 181 s) on the M4, GPU, 24 runs**; 4 poses with best-of-2
  is about 18 min of GPU per character. A paw/hand each needs a look by a person to choose the seed.
- **C code** (capsules in the character's fill and the rig's face line colour, mitten, fist, point,
  open, wave). Under 10 ms for all five poses, no GPU. All five read as the pose at a glance (fist
  with finger lines, a pointing finger, spread fingers), the wave is the open hand splayed and tilted
  12 degrees. They are on-model only in colour and outline weight: they are a generic cartoon glove
  (5 fingers, same on every character), not Kit's ragged paw (four toes, fur edge) or the child's tiny
  hand. Kit's fill median is dark brown and its outline is the rig's light-brown face line, which looks
  like a halo on a dark paw. Sizes (`HAND_W`) are hand-picked, they should be the cut hand's width.
  The joint with the forearm is a flat cut with no cuff, as in A.

## Comparison

| | A procedural | B klein redraw | C drawn in code |
|---|---|---|---|
| Reads as the pose | no (a reshaped paw) | yes (Kit 8/8) | yes, all five |
| On-model | yes (same pixels) | Kit yes; Bo, child not shown (cut failed) | colour and line yes, shape generic |
| Cost per character | ~0 s, CPU | 4 poses, best of 2: ~18 min GPU + a human choice | ~0 s, CPU, no choice needed |
| Integration effort | medium: wrist alignment, rotate-about-wrist | high: needs a clean cut (mask or held-out arms), a fit (scale, angle, wrist), cuff removal | medium: the shapes exist, the same switch as B |
| Licensing and safety | none | klein 4B is Apache-2.0 (`docs/MODELS.md`); output is checked as other art; no new risk | none, deterministic, kid-safe by construction |

## Recommendation

**Start with C, keep B as an upgrade that fills the same slots.** C is the only way that gave five
readable poses on all three characters for free, deterministically, in the render environment (no GPU)
and offline. Its weakness (generic look) is real, so make the drawn hand data-driven: width from
the cut hand, fill from its median, outline from the rig, and the number of fingers and the
finger length as per-character knobs (a paw: 4 short rounded fingers, a mitten for Bo). B shows the
ceiling for characters with a visible hand on plain ground (Kit) and uses the same `hands` slots:
the slot's image is whatever file is listed, drawn or redrawn. A is not worth integrating.

**Smallest first integration step:** a `hands` switch on the forearm in the rig, with only `rest`
(the cut hand) and `fist` drawn by code, plus the build step that produces them. Prove the switch
in Synfig with one shot (rest to fist) before adding point, open and wave.

## Design: rig schema (additive, engine-neutral)

```json
"hands": {
  "forearm_l": {
    "wrist_px": [89.6, 138],
    "default": "rest",
    "poses": {
      "rest":  {"file": "parts/front/hand_l_rest.png",  "pivot_px": [26, 2]},
      "fist":  {"file": "parts/front/hand_l_fist.png",  "pivot_px": [26, 2]},
      "point": {"file": "parts/front/hand_l_point.png", "pivot_px": [26, 2]},
      "open":  {"file": "parts/front/hand_l_open.png",  "pivot_px": [26, 2]},
      "wave":  {"file": "parts/front/hand_l_wave.png",  "pivot_px": [26, 2]}
    }
  }
}
```

Per view, like `face`. `pivot_px` is the wrist point in the hand image. The forearm part is cut at the
wrist (as the stub here) so the `rest` hand is the cut one, and a pose is chosen over time as the face's
mouth is. A character without `hands` (every rig built so far) is unchanged: the schema addition is
optional. No Synfig names appear. In Synfig the generator emits a switch layer per hand parented to the
forearm bone, the same pattern as `studio_core/face.py` mouth shapes, with the stub under the hand so
the joint is covered.

Motion hooks (in `motions/`, data only): a motion may carry `hands: {forearm_r: [[t, "point"], ...]}`
keyframes, with a default per motion: `point` and `wave` take their own pose from anticipation to the
end of the hold (arm raised), `talk_gesture` alternates `open` and `rest`, `clap` uses `open`, the
rest `rest`. A shot spec can override per character (`set_hands`). The motion validator refuses a pose
the rig does not list.

## Open items / not verified

- Only the image-left arm, only the front view; the three-quarter view needs its own hands.
- B for Bo and the child was not completed (the cut failed, see above); I did not try a mask or an
  arms-out redraw. B timings are for the crop edit at 768 px with klein bf16 on the M4.
- No render in Synfig, no animated check; looked at stills only. Mia was not in the cast folder.
