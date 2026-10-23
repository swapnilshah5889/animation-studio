"""Owner checkpoint previews (Step 4): one short test shot, rendered and checked.

    preview_puppet(film, "kit")          # puppet.py: a puppet waving, blinking, talking (cp 3)
    preview_background(film, "meadow")   # background.py: a slow pan with a hole check (cp 4)

Each one stages a test shot in scene 00 (outside the story's numbering) through the same
engine-neutral shot_spec edits the director uses, renders it with the Synfig backend, and
returns the video, a contact sheet and what it measured. A preview that can't run is refused
with a `PreviewError` that says what to fix. scripts/preview_puppet.py and
scripts/preview_background.py are thin command lines over these functions.
"""

from __future__ import annotations

from studio_core.preview.common import ensure_film

__all__ = ["PreviewError", "ensure_film"]


class PreviewError(ValueError):
    """A preview was refused. The message says what to fix."""
