# Owner review of the engine bake-off (2026-10-30)

The owner watched `compare.mp4` and `bend_sheet.png` and said: **both look bad; the characters do not look
production ready and there are many inconsistencies.** They suspect the characters, not the engine.

## What the contact sheet shows (Kit, 6 engine/mode rows x 4 poses)
- The painted fox is a good still, but it is one front-on pose with the arms hidden against the coat, the legs
  together and the tail behind the legs. It was drawn as an illustration, not for rigging.
- Every engine shows the same faults: a bent knee exposes a pasted-looking shin over the tail; a raised arm is a
  straight sleeve-coloured rectangle that is not part of the body; limbs have no art for the hidden part.
- Painted shading (soft highlights and shadow baked into the part) does not match when a part rotates.
- Faces differ between engines (pixel face vs vector face), which reads as inconsistency across shots.

## Conclusion
The engine is not the main limit (D-090 already said the engines tie on defects). The character art pipeline is:
one painted figure cut into parts cannot reach the production bar. Fixing seams (skinned mesh, joint overlap)
helps at the edges but does not change this. Next lever: make characters that are **designed for rigging**
(see ROADMAP and the decision that follows this note).
