# Voices and loudness

How a line of text becomes a finished line of dialogue (`studio_core/audio/voices.py`, task 3.2),
and how the shot mix (task 3.6) uses loudness.

## A voice is a vector

Kokoro-82M is one model for every voice. What makes `af_heart` sound like `af_heart` is a small
tensor (a "voice pack", ~0.5 MB) that conditions the model: a learned style vector. Two
consequences:

- **Blending is arithmetic.** A weighted average of two packs gives a voice in between
  (`af_heart` 70% + `af_bella` 30%). Kokoro's own `"af_heart,af_bella"` syntax averages equally;
  our worker does weighted sums.
- **New voices cost almost nothing:** another 0.5 MB file, not another model.

Kokoro has **no child voices and no pitch control**. Voice casting (STEP-3 checkpoint 2)
approaches a child's voice three ways: young-sounding packs and blends, a slightly faster pace,
and a small pitch step after synthesis.

## Pitch and formants

A voice has a **pitch** (how fast the vocal folds vibrate) and **formants** (resonances of the
vocal tract, which give a vowel its color). Children have higher pitch *and* higher formants,
because their vocal tract is shorter.

Our pitch step (`ffmpeg.pitch_filter`) plays the audio faster (`asetrate`), which raises both,
then stretches time back (`atempo`). Raising formants is usually an artifact, but here it's the
point: a little of it reads as "younger". Too much (beyond ~3 semitones) sounds like a chipmunk,
which is why `voice.json` limits it to −3…+4.

## Loudness is not peak level

- **Peak level** (dBFS) is the single loudest sample. It says nothing about how loud a line
  *feels*.
- **Loudness** (LUFS, EBU R128) is a perceptual average: weighted toward the frequencies ears are
  sensitive to, and gated so silences don't drag it down. Two lines at −20 LUFS sound equally
  loud, whatever their peaks.
- **True peak** (dBTP) estimates the peaks *between* samples, the ones that clip after MP3/AAC
  encoding. We keep it ≤ −1.5 dBTP.

Targets:

| Use | Integrated loudness |
|---|---|
| Each dialogue line (before mixing) | −20 LUFS (`voice.json`) |
| Web video, finished shot or film | −14 LUFS, ≤ −1.5 dBTP (task 3.6) |
| Broadcast (EBU R128) | −23 LUFS |

## Linear gain vs dynamic normalization

ffmpeg's `loudnorm` can reach a target in one pass by compressing as it goes, which changes the
shape of the sound. We measure first, then apply **one fixed gain**: the line only gets louder or
softer, and the same input always gives the same output. The gain is capped so the true peak
stays under the ceiling. That cap is the only case where a line ends up quieter than its target.

## The mix: buses, ducking, one gain

A shot's soundtrack (`studio_core/audio/mix.py`, task 3.6) is three **buses** summed:
dialogue, sound effects, and music. Each is built sample-exactly with numpy after ffmpeg has
converted every input to 48 kHz stereo.

- **Sound effects** come from many sources at wildly different levels. Each one is normalized
  to −20 LUFS before its `volume` scales it. A 50 ms click can't be measured as loudness (the
  meter needs 400 ms blocks), so very short sounds are peak-normalized instead.
- **Ducking** lowers the music while someone speaks, so a child can follow the words. Radio
  does it with a compressor listening to the voice (`sidechaincompress`). We don't need to
  listen: we *know* when every line plays. So the music gets a computed envelope:
  - −10 dB under each line
  - a 150 ms ramp down before the line and a 400 ms ramp back up after it
  - lines closer together than the two ramps count as one, so the music doesn't swell in
    short gaps

  Same input, same output, and a test can measure the dip exactly (−10 dB ± 0.5).
- **One gain** brings the whole mix to −14 LUFS for the web.

## True peaks hide between samples

A limiter that watches samples can still let the *signal* go over. When the waveform is
rebuilt between two samples (by a DAC, or by an MP3/AAC decoder), it can swing higher than
either sample. A sharp click showed this: −1.5 dBFS sample peaks, but −0.4 dBTP true peak. The
fix is the standard one: run the limiter at 4× the sample rate, where those in-between peaks
become real samples, then measure the result and trim if anything still pokes over.

## Caching by content

A line's hash covers its text, its voice settings and the model. Asking for the same line again
costs nothing, and changing the voice (casting) or the model invalidates exactly the lines it
affects. The same idea comes back for music (seeded) and any other generated asset.

## Gotchas

- Kokoro gets weaker on very short inputs (under ~10–20 tokens). The casting page's line 2 is
  short on purpose, so the owner hears it.
- Kokoro voice ids encode the accent (`a` US, `b` UK) and the gender (`f`/`m`). The pipeline
  picks its pronunciation rules from the first voice in a blend.
- Silence trimming must leave a little air (80/120 ms), or soft consonants at the edges are cut.
