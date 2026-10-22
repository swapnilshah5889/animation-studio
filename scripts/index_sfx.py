"""Index the sound-effect library for search: CLAP audio vectors → Qdrant (task 3.5).

    uv run scripts/index_sfx.py      # after scripts/fetch_sfx_library.py; Qdrant must be up

Idempotent: only new sounds are embedded, and sounds gone from the manifest are removed.
"""

from __future__ import annotations

import sys
import time

from studio_core.audio.sfx import index_library


def main() -> int:
    t0 = time.monotonic()
    counts = index_library()
    print(f"{counts} in {time.monotonic() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
