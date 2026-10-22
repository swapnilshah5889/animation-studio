# Lip-sync: from sounds to mouth shapes

How a recorded line drives the puppet's mouth (`studio_core/audio/lipsync.py`, task 3.3, and
`studio_core.sif.lipsync.mouth_track` on the animation side).

## Phonemes and visemes

- A **phoneme** is a unit of sound: the "p" in *pip*, the "ee" in *see*. English has ~40.
- A **viseme** is what the mouth *looks like* while making it. Many phonemes share one: "p",
  "b" and "m" all close the lips. So animation needs far fewer mouth drawings than there are
  sounds.

Rhubarb Lip Sync maps speech to nine mouth shapes, the classic cartoon set. Our procedural mouth
draws exactly these (D-007):

| Shape | Mouth | Sounds |
|---|---|---|
| A | closed, lips pressed | P, B, M |
| B | slightly open, teeth together | most consonants (K, S, T, EE) |
| C | open | EH, AE |
| D | wide open | AA (as in *father*) |
| E | slightly rounded | AO, ER |
| F | puckered | UW, OW, W |
| G | upper teeth on lower lip | F, V |
| H | tongue raised | long L |
| X | at rest | silence |

G, H and X are Rhubarb's "extended" shapes. We keep all three because our mouth has them.

## Recognition vs alignment

Rhubarb has to find *when* each sound happens. With only the audio, it runs speech
**recognition** (PocketSphinx) and guesses the words. With the text as well (`--dialogFile`),
it mostly has to **align** known words to the audio, which is much more accurate. We always
know the text, because we generated the line, so we always pass it.

PocketSphinx only knows English. For other languages Rhubarb's `phonetic` recognizer
works on sounds without words: less accurate, but language-independent.

## Cues → keyframes

Rhubarb's output is a list of cues: `{start, end, value}` in seconds, covering the line with no
gaps. On the animation side, `mouth_track` turns them into **constant** (stepped) keyframes on
the mouth switch, shifted to the line's start time in the shot. Mouths don't tween in cut-out
animation: they snap from drawing to drawing, which is also how hand-animated cartoons do it.

## Why cues are computed from the final audio

`speak` trims silence and may apply a pitch step, which changes timing slightly. Cues made from
the raw synthesis would drift by the trimmed amount. So lip-sync always runs on the finished
WAV, and a re-take deletes the old cues. The shot checks also refuse cues whose length doesn't
match the audio ("run lipsync on it again").

## Gotchas

- Rhubarb is deterministic: same audio + same text = identical cues. That makes the cache safe
  and the tests exact.
- Rhubarb's macOS build is x86_64 and runs under Rosetta (D-022). It takes ~1.1x real time.
  Lines run in parallel.
- The cues store the audio file relative to themselves (`../dialogue/l001.wav`), so a film
  folder can move to another machine or a render container.
