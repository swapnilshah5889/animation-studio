"""Act cache keys and staleness (D-083): a pure function of the specs, no disk, no clock.

An act's render is derived data. Its key is a hash of everything that can change the picture:
the act's own spec, its shots' specs in order, the character and background versions it uses and
the engine. Edit one shot and only its act's key changes; the act that was rendered under another
key is stale. The key is stored beside the render (an `act_render` document) and compared.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

# Bookkeeping that changes without the picture changing.
VOLATILE_FIELDS = ("rev", "created_at", "updated_at", "owner_id", "project_id")
# Act fields that say where the act sits in the film or what it is about, not how it looks:
# reordering acts or retitling one must not make its render stale.
STORY_FIELDS = ("order", "title", "beats")
KEY_VERSION = 2  # bump to invalidate every cached render when the key recipe changes


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _content(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in VOLATILE_FIELDS}


def act_cache_key(
    act: Mapping[str, Any],
    shots: Sequence[Mapping[str, Any]],
    engine_id: str,
    *,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """The key of an act's render.

    `shots` are the act's shot documents, in the act's `shot_ids` order (a different order is a
    different cut). `extra` carries anything else the picture depends on that is not in these
    documents, such as the film's locked style id.
    """
    wanted = list(act.get("shot_ids", []))
    got = [s["id"] for s in shots]
    if got != wanted:
        raise ValueError(f"shots {got} do not match the act's shot_ids {wanted}")
    recipe = {
        "key_version": KEY_VERSION,
        "engine": engine_id,
        # The act carries its background and cast as {id, version}, so their versions are in here.
        "act": {k: v for k, v in _content(act).items() if k not in STORY_FIELDS},
        "shots": [_content(s) for s in shots],
        "extra": dict(extra or {}),
    }
    return content_hash(recipe)


def is_stale(current_key: str, last_render: Mapping[str, Any] | None) -> bool:
    """True when the act has never been rendered or was rendered from different specs."""
    return last_render is None or last_render.get("cache_key") != current_key
