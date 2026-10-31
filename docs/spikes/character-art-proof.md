# Character-art proof: Rowan

**Date:** 2026-10-31
**Decision:** D-105
**Outcome:** FAIL; no rig approved.

## Setup

Two local ComfyUI generations with SDXL Base 1.0 and StorybookRedmondV2 LoRA. No downloads or installs. The first image used 30 steps, CFG 6, DPM++ 2M Karras, seed 418027351. The second used the same model/settings with seed 731904286. Final scratch images and JSON run records are in `~/ai-studio/scratch/character-art-proof/`.

## Results

- First image: adult-looking front figure plus clothing diagrams; it did not provide the requested matching views or face detail.
- Second image: richer watercolor detail and readable normal faces, but three different children appear. Hair, clothing and proportions differ; no clear front/three-quarter pair, no face-detail panel, and no composite against the existing meadow plate.
- Independent reviewer verdict: **FAIL**. Blocker: three characters instead of one. Majors: no identity-consistent front/three-quarter pair; missing face detail and design description. Minor: foliage is part of the generated art rather than the existing forest plate.
- No animation, rigging or engine behavior was reviewed.

## Staged workflow (owner-approved as D-106)

Select one canonical illustration before generating views. Then create the three-quarter view by reference-conditioned image editing, compare the face, hair, outfit and proportions against the canonical view, and only build a model sheet/rig after independent identity review passes. Do not reuse the current multi-view prompt workflow as a consistency guarantee.

## Prompts

### Seed 418027351

```text
KidsRedmAF, illustrated storybook character design sheet, clean hand-painted ink and watercolor texture, warm gentle children's book illustration. One original 9-year-old forest explorer child named Rowan, full body, large readable figure with unmistakable silhouette: short sturdy child proportions, oversized soft moss-green hooded capelet with broad rounded shoulder shape, asymmetrical hem and small acorn-shaped wooden clasp, rust-red quilted vest, cream linen shirt, deep teal knee-length shorts, ochre socks, sturdy brown boots, small crossbody satchel with a stitched fern motif and two tiny brass leaf charms. Layered fabrics visibly distinct: brushed wool cape, quilted cotton vest, linen shirt, leather boots, woven strap; fine restrained seams and embroidery, details readable at full figure scale. Forest palette of moss, fern, bark brown, muted cranberry, warm cream and subdued golden ochre. Painterly edges, delicate dark olive linework, soft natural light, subtle paper grain, richly designed but uncluttered. Model sheet layout on warm pale parchment background with three clearly separated panels: left full-body FRONT view, center full-body THREE-QUARTER view turned slightly toward viewer, right enlarged FACE DETAIL. Exactly the same child, same outfit, same proportions, same short wavy dark chestnut hair with one small fern-green hair clip in all views. Face front-facing in front and face detail: exactly two level evenly spaced dark brown eyes, one tiny simple nose, one small closed friendly mouth; clean unmarked cheeks, no freckles, no face decorations. No text, no labels, no border, no extra figures, no props beyond described clothing accessories.
```

### Seed 731904286

```text
KidsRedmAF, hand-painted watercolor and ink children’s storybook illustration, original character Rowan, unmistakably an 8-year-old child, short child height, large head relative to body, compact torso, short arms and legs, round soft child face. Exactly two full-body views of the SAME child side-by-side at equal scale: left a straight front view, right a three-quarter view turned slightly toward viewer. Both standing neutrally, entire head and boots visible, generous clean space between figures. Preserve this exact design in both views: moss-green hooded capelet worn down on shoulders, rust-red vest, cream shirt, deep teal shorts, ochre socks, brown boots, small crossbody satchel with a clear fern motif, short chestnut hair and one small green hair clip. Warm restrained forest palette, gentle painterly paper texture, fine clean olive linework, readable simple shapes, childlike rounded proportions, clear silhouette. Plain pale warm cream background. Face visible in both views, exactly two level eyes, one small nose and one small closed mouth, no marks on cheeks.
```

### Negative prompt (both runs)

```text
text, letters, labels, watermark, logo, extra person, duplicate child, adult, teen, baby, photoreal, 3d render, plastic, glossy, anime, huge eyes, asymmetrical eyes, third eye, extra eyes, eye-like dots, freckles, cheek spots, face marks, eyebrows resembling eyes, extra nose, extra mouth, open mouth, teeth, beard, makeup, clutter, excessive jewelry, weapons, frightening, grim, sexualized, cropped feet, cropped head, missing limbs, fused limbs, extra fingers, bad hands, inconsistent outfit, mismatched views, different character, hat, hood covering face, modern branding
```

## Independent review

Reviewer followed `docs/craft/visual-review.md` without seeing the artist assessment. The face is small and readable with two eyes, a small nose and restrained mouth; the watercolor rendering, layered clothing and green-brown palette work. The identity and sheet-layout failures above prevent a pass. The existing-plate composite, animation and rig behavior were not checked.

## Stage 1: canonical Rowan candidate (2026-10-31)

Output: `~/ai-studio/scratch/character-art-proof/canonical/rowan-canonical.png` (832×1216), with a face crop and full run notes beside it. The image contains one front-facing child, readable full body, layered outdoor clothing, small nose and mouth, and two eyes. The local model changed several requested outfit details and added a leafy forest setting; do not treat the prompt as a locked design specification. Model: SDXL Base 1.0 + StorybookRedmondV2 LoRA (0.9), seed `684291735`, 30 steps, CFG 6, DPM++ 2M Karras. The full prompt is in the adjacent `rowan-notes.json` scratch artifact; the image itself is not committed.

**Independent review verdict: NEEDS WORK.** No blocker or major. Minor: the viewer-right eye is slightly higher and turned outward relative to the other. The watercolor linework, gentle shading, green/teal/ochre/rust palette, child proportions, detail and silhouette were judged promising. Style was compared against the forest reference image but not an exact composite; views, animation and rigging were not checked. The reviewer was separate from the image author and had not seen the author's notes.

**Status:** candidate awaits owner approval. D-106 permits additional reference-conditioned views only after the owner approves this canonical design. No turnaround, rig or animation was created.

## Stage 2: reference-conditioned turnarounds (2026-10-31)

Owner approved the Stage 1 canonical image before these views were generated. Both use FLUX.2 Klein 4B distilled bf16, Qwen3-4B encoder and FLUX.2 VAE (Apache-2.0, local files; no download), 4 steps, with the canonical full-body image as primary reference and its face crop as a secondary reference. Output contact sheet: `~/ai-studio/scratch/character-art-proof/turnaround/rowan-all-views.png`; individual source renders and `run.json` files are kept in the same scratch directory.

| View | Seed | Render time | Output |
|---|---:|---:|---|
| gentle three-quarter facing right | 614209731 | 240.89 s | `three_quarter_run/rowan-three-quarter.png` |
| clear side profile facing right | 614209732 | 226.14 s | `side_profile_run/rowan-side-profile.png` |

**Artist self-check:** both views retain the rust cap, chestnut hair, teal shirt, olive vest, deep teal pants and tall brown boots. The vest pocket/buttons drift slightly; the side view adds cap seams/top button and a ground shadow. This is not independent review. The current status is pending a separate identity review and owner approval; no rig or animation was made.

### Prompt 1: gentle three-quarter facing right

```text
Reference image 1 is the approved full-body character design and is the source of truth. Reference image 2 is a close-up of that same face and is only a secondary face-identity reference. Redraw exactly one full-body view of the same child, about age 9, changing only the viewing angle to a gentle three-quarter view facing right, about 35 degrees. Keep the exact visible design, child proportions, face shape, small nose and mouth, two eyes, short rust-orange cap, chestnut wavy hair, pale teal long-sleeve shirt, olive buttoned pocket vest, deep teal pants, and tall brown lace-up boots, with the same watercolor storybook finish and muted colors. Keep both eyes visible in a natural three-quarter face, with the far eye smaller. Keep the clothing and all visible details exactly as in reference image 1; do not invent, remove, or add accessories or costume details. One standing child, full figure from cap to boot soles, arms relaxed close to the body, centered, on a simple warm off-white background. No other figures, no text, no labels, no diagrams, no panels.
```

### Prompt 2: clear side profile facing right

```text
Reference image 1 is the approved full-body character design and is the source of truth. Reference image 2 is a close-up of that same face and is only a secondary face-identity reference. Redraw exactly one full-body view of the same child, about age 9, changing only the viewing angle to a clear true side profile facing right, the head, shoulders, torso, hips, knees and feet all in profile. Keep the exact visible design, compact child proportions, face shape, small nose and mouth, short rust-orange cap, chestnut wavy hair, pale teal long-sleeve shirt, olive buttoned pocket vest, deep teal pants, and tall brown lace-up boots, with the same watercolor storybook finish and muted colors. Show the face in profile with one visible eye and a small natural nose and mouth. Keep clothing and all visible details exactly as in reference image 1; do not invent, remove, or add accessories or costume details. One standing child, full figure from cap to boot soles, arms relaxed close to the body, centered, on a simple warm off-white background. No other figures, no text, no labels, no diagrams, no panels.
```
