"""Sound-effect search: describe a sound, get library sounds (task 3.5, D-036).

    index_library()                                        # once, and after the library changes
    find_sfx(["a soft cartoon pop", "footsteps on wood"])  # → candidates per query

**How it works.** CLAP (scripts/audio/clap_embed.py in envs/clap) maps audio and text into one
512-dimensional space where a recording of a door creaking lands near the words "a creaking
door". Every library sound's audio vector is stored in Qdrant (collection `sfx`, cosine
distance) with its manifest entry as payload. A query is embedded with CLAP's *text* encoder and
Qdrant returns the nearest sounds.

**Hybrid ranking.** CLAP alone misses some obvious matches: a 0.3 s single footstep doesn't sit
near the words "footsteps on wood", although the file is tagged `footstep`, `wood`. So each
query gathers two candidate sets, the nearest `CANDIDATES` by vector and the sounds whose
tags or description match a query word (scored by Qdrant too), then re-ranks their union by
similarity plus a bonus for the share of query words a sound's words match (`KEYWORD_WEIGHT`).
Meaning first, words as the tiebreaker and the safety net.

**Idempotent indexing.** A sound's point id is derived from its audio's sha256, so re-indexing
only embeds new sounds and removes the ones no longer in the manifest.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio_core.audio.library import SoundLibrary, load_library
from studio_core.config import REPO_ROOT, StudioConfig, expand_path, load_config

COLLECTION = "sfx"
DIM = 512
WORKER = REPO_ROOT / "scripts" / "audio" / "clap_embed.py"
CANDIDATES = 40  # nearest by vector, then re-ranked
KEYWORD_POOL = 200  # sounds whose words match the query, scored by vector too
KEYWORD_WEIGHT = 0.25  # bonus for matching every query word (CLAP similarities span ~0-0.6)
STOPWORDS = {"a", "an", "the", "of", "on", "in", "and", "with", "sound", "some", "soft", "small"}


class SearchError(ValueError):
    """A search was refused or the index is missing. The message says what to fix."""


@dataclass(frozen=True)
class Candidate:
    sound_id: str
    score: float  # cosine similarity + keyword bonus
    duration_s: float
    description: str
    tags: list[str]
    file: Path


def point_id(sha256: str) -> str:
    return str(uuid.UUID(hex=sha256[:32]))


def _client(cfg: StudioConfig) -> Any:
    from qdrant_client import QdrantClient

    return QdrantClient(url=cfg.get("services", "qdrant_url"), timeout=30)


def _worker(job: dict[str, Any], cfg: StudioConfig) -> dict[str, Any]:
    python = expand_path(cfg.get("envs", "clap")["python"])
    proc = subprocess.run(
        [str(python), str(WORKER)], input=json.dumps(job), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise SearchError(f"the CLAP worker failed: {proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def embed_texts(texts: list[str], cfg: StudioConfig) -> list[list[float]]:
    return _worker({"mode": "text", "texts": texts}, cfg)["vectors"]


def index_library(
    library: SoundLibrary | None = None, cfg: StudioConfig | None = None
) -> dict[str, int]:
    """Bring the Qdrant collection in line with the manifest. Returns counts."""
    import numpy as np
    from qdrant_client import models

    cfg = cfg or load_config()
    library = library or load_library()
    client = _client(cfg)
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION,
            vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE),
        )
        client.create_payload_index(COLLECTION, "duration_s", models.PayloadSchemaType.FLOAT)
    if "tags" not in client.get_collection(COLLECTION).payload_schema:
        client.create_payload_index(COLLECTION, "tags", models.PayloadSchemaType.KEYWORD)

    wanted = {point_id(s["sha256"]): s for s in library.sounds.values()}
    present, offset = set(), None
    while True:
        points, offset = client.scroll(COLLECTION, limit=1000, offset=offset, with_payload=False)
        present |= {str(p.id) for p in points}
        if offset is None:
            break
    stale = sorted(present - set(wanted))
    if stale:
        client.delete(COLLECTION, points_selector=models.PointIdsList(points=stale))
    todo = [(pid, s) for pid, s in wanted.items() if pid not in present]
    if todo:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "vectors.npy"
            files = [str(library.root / s["file"]) for _, s in todo]
            _worker({"mode": "audio", "files": files, "out": str(out)}, cfg)
            vectors = np.load(out)
        for i in range(0, len(todo), 256):
            chunk = todo[i : i + 256]
            client.upsert(
                COLLECTION,
                points=[
                    models.PointStruct(id=pid, vector=vectors[i + j].tolist(), payload=sound)
                    for j, (pid, sound) in enumerate(chunk)
                ],
            )
    count = client.count(COLLECTION).count
    return {"indexed": len(todo), "removed": len(stale), "total": count}


def terms(text: str) -> set[str]:
    """Content words, roughly stemmed: 'footsteps' → 'footstep', 'dripping' → 'drip'."""
    out = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in STOPWORDS or len(w) < 3:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[: -len(suffix)]
                break
        if len(w) > 3 and w[-1] == w[-2]:  # dripp → drip
            w = w[:-1]
        out.add(w)
    return out


def matched(query_terms: set[str], sound: dict[str, Any]) -> int:
    """How many query terms a sound's tags/description contain (prefix match either way)."""
    words = terms(" ".join(sound.get("tags", [])) + " " + sound.get("description", ""))
    return sum(any(w.startswith(t) or t.startswith(w) for w in words) for t in query_terms)


def find_sfx(
    queries: list[str],
    *,
    k: int = 5,
    max_duration_s: float | None = None,
    cfg: StudioConfig | None = None,
) -> list[list[Candidate]]:
    """The k best library sounds for each query (best first). One CLAP call for all queries."""
    from qdrant_client import models

    if not queries or any(not q.strip() for q in queries):
        raise SearchError("give at least one non-empty description of the sound")
    if not 1 <= k <= 20:
        raise SearchError(f"k must be between 1 and 20, not {k}")
    cfg = cfg or load_config()
    client = _client(cfg)
    if not client.collection_exists(COLLECTION) or client.count(COLLECTION).count == 0:
        raise SearchError("the sound library isn't indexed yet; run scripts/index_sfx.py")
    library = load_library(cfg.path("paths", "sfx_library"))
    duration = []
    if max_duration_s is not None:
        duration = [models.FieldCondition(key="duration_s", range=models.Range(lte=max_duration_s))]
    results = []
    for query, vector in zip(queries, embed_texts(queries, cfg), strict=True):
        wanted = terms(query)
        # candidates: nearest by meaning, plus the sounds whose words match the query
        by_words = sorted(
            (s for s in library.sounds.values() if wanted and matched(wanted, s)),
            key=lambda s: -matched(wanted, s),
        )[:KEYWORD_POOL]
        hits = {}
        filters = [models.Filter(must=duration) if duration else None]
        if by_words:
            ids = [point_id(s["sha256"]) for s in by_words]
            filters.append(models.Filter(must=[*duration, models.HasIdCondition(has_id=ids)]))
        for flt in filters:
            for hit in client.query_points(
                COLLECTION, query=vector, limit=CANDIDATES, query_filter=flt, with_payload=True
            ).points:
                hits[hit.id] = hit
        ranked = []
        for hit in hits.values():
            sound = hit.payload
            share = matched(wanted, sound) / len(wanted) if wanted else 0.0
            ranked.append(
                Candidate(
                    sound_id=sound["id"],
                    score=round(hit.score + KEYWORD_WEIGHT * share, 4),
                    duration_s=sound["duration_s"],
                    description=sound.get("description", ""),
                    tags=sound.get("tags", []),
                    file=library.root / sound["file"],
                )
            )
        results.append(sorted(ranked, key=lambda c: -c.score)[:k])
    return results
