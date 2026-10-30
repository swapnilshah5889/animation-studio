"""ULID-style ids: 26 Crockford-base32 characters: a 48-bit millisecond timestamp, 80 random bits.

They sort by creation time, are safe in file names and URLs, and need no dependency. Ids made in the
same millisecond by one process still sort in creation order (the random part is incremented).
"""

from __future__ import annotations

import os
import re
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_lock = threading.Lock()
_last: tuple[int, int] = (0, 0)  # (timestamp ms, random part) of the last id

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
_ID_RE = re.compile(ID_PATTERN)


def new_id(now_ms: int | None = None) -> str:
    global _last
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    with _lock:
        rand = int.from_bytes(os.urandom(10), "big")
        if ms <= _last[0]:
            ms, rand = _last[0], min(_last[1] + 1, (1 << 80) - 1)
        _last = (ms, rand)
    n = (ms << 80) | rand
    return "".join(_ALPHABET[(n >> shift) & 31] for shift in range(125, -1, -5))


def is_valid_id(value: object) -> bool:
    """Any id the stores accept: a ULID, or a caller-chosen id such as a project id."""
    return isinstance(value, str) and _ID_RE.match(value) is not None
