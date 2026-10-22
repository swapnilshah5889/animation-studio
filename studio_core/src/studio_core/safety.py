"""Children's-content word check, shared by every tool that takes free text (speech, art).

A deliberately small stand-in (config/safety_blocklist.txt): the Step 5 safety classifier
replaces it (D-036). Image prompts also always carry comfy_graphs.KID_SAFE_NEGATIVE.
"""

from __future__ import annotations

import re

from studio_core.config import REPO_ROOT

BLOCKLIST = REPO_ROOT / "config" / "safety_blocklist.txt"


def blocklist() -> set[str]:
    words = BLOCKLIST.read_text().splitlines() if BLOCKLIST.is_file() else []
    return {w.strip().lower() for w in words if w.strip() and not w.startswith("#")}


def blocked_words(text: str) -> list[str]:
    """The blocklisted words in `text`, matched as whole words, case-insensitively."""
    return sorted({w for w in re.findall(r"[a-z']+", text.lower()) if w in blocklist()})
