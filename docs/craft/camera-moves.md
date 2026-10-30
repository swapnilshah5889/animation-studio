# Camera moves
> What each of our five camera moves is for, and when not to move the camera.

**When to use:** when you set a shot's `camera` and `framing`.

**The moves we have:** `static`, `push_in` (zoom in 1.25x), `pull_out` (zoom out 1.25x),
`slow_pan_left`, `slow_pan_right` (a small, gentle drift). All ease in and out, one per shot.

**Move with a reason:**
- `push_in` leans toward a feeling: the discovery ("a red balloon!"), the proud grin, a worry
  that needs comfort. Medium or close framing, on a shot whose emotion is joy, excited, wonder,
  proud, sad, worried or shy. Never on a wide shot (it crops the sides for nothing).
- `pull_out` lets go: the last shot, a goodbye, a calm hold. Pair with a settled emotion.
- `slow_pan_*` follows a walk (a character `moves_to` that side) or reveals the place in an
  establishing shot with no line. A pan during a line distracts (the code rejects it).
- `static` is for talking and for reaction shots: when two friends talk, the frame sits still.

**Vary the shots:** a 3+ shot film with every shot static feels dead; with every shot moving it is
seasick. Typical 15 s: establishing (slow pan or static), two-shot talking (static), discovery
(push_in), peak (static, big motion), landing (pull_out). Code requires at least two different moves
and at least two different framings.

**What fails and why:** a push_in on a wide shot crops both sides; a pan under a long line makes
children look at the background; the camera moving every shot hides the story's few real moves.
