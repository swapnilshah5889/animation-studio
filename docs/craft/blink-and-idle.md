# Blink and idle
> Every character in every shot gets blink and idle_breathe for the whole shot, or it looks dead.

**When to use:** every shot, every character, including the one who is only listening.

**How:** `apply_motion blink` from 0 for the shot's duration, then `apply_motion idle_breathe` from 0
(it runs until the shot ends). Both are additive: a waving character still breathes. The builder
code adds these for you when it scaffolds a shot; check `describe_shot` and add them if the warnings
say one is missing.

**What fails and why:** a held pose without breathing reads as a freeze frame; a character who never
blinks stares. A blink with a short `duration_s` stops blinking before the shot ends. Do not use
idle_breathe as the only motion of a character who has a line: add a gesture on the beat.
