# Rain over the painted forest: drawn-look spike

**Status: NEEDS WORK. No look adopted; animation did not start.** Owner's delegated preference was painterly 2.5D. The
test held the character, forest plate, pose, framing and Blender 5.2.3 constant while changing only the render treatment.
All output is scratch media, not a film deliverable: `~/ai-studio/scratch/slice-look/`.

## What was tested

1. **Flat 2D and soft-lit painterly 2.5D stills:** the independent reviewer marked both NEEDS WORK. The flat character
   looked too clean against the painted forest; the soft-lit Rain rig read as CG over a painting.
2. **Localized character-only paint treatment:** softened and grouped Rain's rendered values, added restrained texture
   and contour, then restored the face area to keep the eyes and mouth sharp. Independent review still marked NEEDS WORK:
   Rain's rounded 3D shading remained distinct from the forest brushwork. A stronger first version blurred the facial
   features, so it was rejected.
3. **EEVEE toon material proof:** `Shader to RGB` → grayscale → three-band constant ramp, multiplied by each authored
   material colour/texture; warm key/fill/rim light; Freestyle contours. An initial 0.85 px silhouette plus crease pass
   made dark marks across the face/chin. Removing crease lines and using a 1.6 px warm silhouette improved the drawing
   edge and kept the face readable. The independent reviewer still marked NEEDS WORK: rounded dimensional forms and
   crisp contours did not cohere with the softly painted background.

The best failed still is `~/ai-studio/scratch/slice-look/line-refined/rain_toon.png`; its face crop is
`~/ai-studio/scratch/slice-look/line-refined/rain_toon_face.png`. The face has two level eyes, a nose and a small mouth.
The reviewer could not judge motion, foot contact over time, turns, lip-sync, transitions or shot consistency from it.

## Finding and next move

The limitation is not a missing Blender control. With the frozen Rain rig and a painted plate, character-only postprocessing
and a direct toon shader both leave the character reading as a CG model. Do not spend more time turning isolated shader
knobs or build the four-shot film on this failed look.

**Recommendation:** keep the painted plate as the source, but test one shared illustrative treatment across both plate and
character so their edges, value grouping and texture belong to the same visual world. If that cannot pass the independent
review, ask the owner to reopen the character-art constraint before proceeding. This next move changes visual treatment,
not engine, cast, model or animation scope.
