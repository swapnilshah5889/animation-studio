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

**Follow-up:** a shared whole-frame softened/posterized treatment was tried on the toon proof. It kept the forest
recognizable and the face readable, but looked like a generic filter while Rain still read as 3D. No helper was kept, and
this still did not receive independent review. It did not close the gap.

**Recommendation:** reopen the character-art source while keeping Blender. The current Rain model's sculpted face and
rounded forms resist the drawn look through small render treatments. Before making a film, approve a character source or
design approach intended to match the forest's illustrated style. This is a meaningful change to the frozen cast rule;
the owner must approve it. Do not quietly substitute another rig or begin a new character build.
