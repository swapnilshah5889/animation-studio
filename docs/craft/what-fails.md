# What fails
> Known failures in these tools and what to do about them. Typed QA issues map to the fixing tool.

**When to use:** after `check_frame` reports problems, or when a tool refuses.

**How:** missing_character: add_character at a position inside the frame. cropped or off-frame:
`move_character` or add_character with a position between 0.15 and 0.85. overlap: move one character
or shorten the scale. hole_visible: the background pan range is too big, use `static` or a shorter
move. A refused call names what to fix: read it, change that one argument, try again. Do not repeat the
same call unchanged; after three refusals the stage stops and asks the owner.

**What fails and why:** the vision model's remarks are advice; code checks (holes, seams, a character
missing or cropped) are facts. Fix the facts first. At most two fix rounds per shot, then keep the shot
and record what is open.

Note: the numbers here are starting rules from the tool descriptions, not measured.
