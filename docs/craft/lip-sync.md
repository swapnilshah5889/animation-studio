# Lip-sync
> Lines are recorded first (audio server), then placed with apply_lipsync at a start time.

**When to use:** whenever a plan shot has a line.

**How:** the audio stage has already recorded each line and given it a `line_id`; the shot brief lists
them with their length. `apply_lipsync` with that `line_id` and a `start_s`. Leave about 0.6 s before
the line (the listener's reaction) and about 0.6 s after it; the shot must be longer than
`start_s` plus the line's length. Two speakers in a shot: the second starts after the first ends plus
about 0.4 s. The speaker also gets a `talk_gesture` or a nod from the listener on the beat.

**What fails and why:** a line placed past the end of the shot is cut off and refused. Calling
`apply_lipsync` again with the same `line_id` moves the line, it does not add a second one. Lines
over about 12 words make shots long and dull for ages 4 to 6: keep them short.
