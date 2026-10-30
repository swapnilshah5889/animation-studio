# Expressions
> Which of the eleven faces fits which feeling, what each really looks like on our puppets, and which ones read wrongly.

**When to use:** every shot. You name the *emotion* first, and the expression must come from that
emotion's list; code rejects a mismatch (`director/taste.py`).

**What a face is made of:** a brow shape and a mouth shape, drawn by code. **While a character
speaks the mouth is replaced by lip-sync shapes, so only the brows and eyes carry the feeling.**
Choose the face that reads in the brows during a line: `excited` (high round brows) reads clearly,
`happy` and `neutral` differ only a little.

| emotion | use expression | what it looks like (brows / mouth) |
|---|---|---|
| calm | `neutral`, `happy` | neutral: relaxed brows, a small closed smile. happy: lifted arched brows, wide smile |
| curious | `neutral`, `surprised`, `happy` | a little surprise (brows up) with an interested head tilt reads as curiosity |
| joy | `happy`, `excited` | happy: warm and wide. excited: very high brows, an open grin with teeth: the big one |
| excited | `excited`, `happy` | the peak of fun: pair with jump, clap, laugh |
| wonder | `surprised`, `excited` | surprised: very high brows, a round open "o" mouth: "oh!" |
| proud | `proud`, `happy` | lifted brows, a broad smile with one corner higher: a smirk of achievement |
| shy | `shy`, `neutral` | brows up, inner ends tilted up, a small smile pulled to one side: bashful |
| worried | `worried` | brows raised and tilted up inward, a wavy flat mouth: a short wobble before relief |
| sad | `sad`, `worried` | inner brows tilted way up and a downturned mouth: use briefly, never at the end |
| tired | `sleepy`, `neutral` | low flat brows, a tiny mouth: bedtime, the last shot of a sunset |
| effort | `neutral`, `proud`, `determined` | pushing or carrying something heavy, then it works |
| grumpy | `grumpy`, `neutral` | only if the story needs a grump, and then once |

**Faces that read wrongly (do not guess, these were seen in the first film):**
- `determined` is low brows in a shallow V over a flat mouth: children read it as **angry or cross**.
  Not for "brave", "trying hard" or "ready". Use `proud` or `neutral`. At most once per film.
- `grumpy` is the same V, steeper: cross. Not for jumping, cheering or any joyful motion.
  At most once per film, and never on a character the story likes at that moment.
- `sad` at a goodbye: a goodbye in a children's film is calm and warm. Use `calm`/`proud`, wave and
  smile. Sad is for a real loss, and then briefly.
- `surprised` held for a whole shot looks startled; use it for the first 1 to 2 seconds (the
  discovery) and let the next shot settle into `joy` or `curious`.
- `sleepy` only at bedtime.

**How to place them:** the expression is set once at the shot's start; changes between shots tell the
story (calm, then wonder, then joy). Do not change inside a shot. Never contradict the line: a happy
line gets a joy face, a worried line a worried one. Motions and faces agree: `jump`, `clap`, `laugh`
need `joy`, `excited`, `wonder` or `proud`. Negative feelings (sad, worried, grumpy) may fill at most
30 percent of the film.

**What fails and why:** a face that contradicts its line or motion (grumpy while jumping for joy)
confuses a 4 year old, who reads the face first. Changing faces every second looks twitchy.
