# Taste rules: a rule-based critic for a plan
> Why the director's shot plan is checked by rules about *taste*, not only about *sense*, and how the feedback round works.

**What it is.** A 14B model forced into a JSON schema always gives a *valid* plan, but not a *good*
one. Our first film showed it: one character per shot, "Look, Bo!" with Bo off screen, a grumpy face
on a happy jump. `director/taste.py` encodes the veteran-animator rules (`docs/craft/*.md`) as code
that returns *instructions* ("make shot s01_sh01 an establishing shot: framing wide, ...").

**Why code, not prompt.** A longer prompt makes a small model forget some rules and obey others at
random. A checker gives you a number (violations per film) that you can measure before and after any
change, which is the seed of the Step 7 evals. The prompt still states the rules once and shows one
worked example; the checker is the safety net, and its messages are the feedback.

**Schema fields exist so the rules have something to check.** Rules cannot judge what the plan does
not say, so the schema asks for `emotion` (the feeling picks the face), `framing`, `line.to`
(who hears it) and `target` (who `point` points at). All are *required*: a 14B model leaves optional
fields out. Empty string means "none".

**Two kinds of problem.** *Sense* (an unknown id, seconds that do not add up) ends the stage if the
retry fails. *Taste* is advice: it rides along in the same single feedback round, and if the model
still gets some wrong the plan is kept and the rest is logged as a `taste` event. A film with a
slightly dull camera is better than no film.

**Gotchas.** The feedback round is the model's second chance, not a loop (the design forbids loops).
Rules that are too strict make the model contort the plan to satisfy the checker, so each rule
has an escape (one close-up per scene may be a lone speaker; `to` "" for a line said to the world).
The emotion field is the model's own claim, so it cannot catch a model that labels a grumpy face
"joy"; the cross-rules (motion, arc, rare faces) catch most of it.
