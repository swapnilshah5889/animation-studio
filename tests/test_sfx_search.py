"""Sound-effect search (task 3.5): word matching, ids, refusals, and a retrieval spot-check on
the real library (marked `models`: needs Qdrant, the indexed library and the CLAP env).

The spot-check is a test, not the Step 7 eval harness: each cartoon query must find a sound of
the right kind in its top 5 (24 queries). Known gaps (sounds the CC0 library doesn't have) are
printed, not asserted, so the owner can decide what to add.
"""

import json
import urllib.request

import pytest

from studio_core.audio.sfx import SearchError, find_sfx, matched, point_id, terms
from studio_core.config import expand_path, load_config

CFG = load_config()


def _ready() -> bool:
    try:
        url = f"{CFG.get('services', 'qdrant_url')}/collections/sfx"
        with urllib.request.urlopen(url, timeout=2) as r:
            points = json.load(r)["result"]["points_count"]
    except (OSError, KeyError, ValueError):
        return False
    return points > 0 and expand_path(CFG.get("envs", "clap")["python"]).exists()


def test_terms_stem_roughly() -> None:
    assert terms("Footsteps on the wooden floor, dripping water") == {
        "footstep",
        "wooden",
        "floor",
        "drip",
        "water",
    }
    assert terms("a soft sound of some small things") == {"thing"}


def test_matching_counts_query_terms_found() -> None:
    sound = {"tags": ["footstep", "wood"], "description": "Impact Sounds: footstep wood"}
    assert matched(terms("footsteps on wood"), sound) == 2
    assert matched(terms("a wooden knock"), sound) == 1  # wood ~ wooden
    assert matched(terms("birds singing"), sound) == 0


def test_point_ids_come_from_the_audio_hash() -> None:
    sha = "ab" * 32
    assert point_id(sha) == point_id(sha) and len(point_id(sha)) == 36
    assert point_id(sha) != point_id("cd" * 32)


def test_refusals() -> None:
    with pytest.raises(SearchError, match="non-empty"):
        find_sfx(["  "])
    with pytest.raises(SearchError, match="k must be between 1 and 20"):
        find_sfx(["a pop"], k=50)


SPOT_CHECK = {  # query → words, any of which a top-5 result must contain
    "footsteps on wood": ["footstep", "step"],
    "a door opening": ["door"],
    "coins clinking": ["coin"],
    "a button click": ["click", "switch"],
    "cards shuffling": ["card"],
    "dice rolling": ["dice", "die"],
    "metal clang": ["metal"],
    "a whoosh": ["swish", "whoosh", "swoosh"],
    "wind blowing": ["wind"],
    "water dripping": ["water", "drip"],
    "bubbles popping": ["pop", "bubble"],
    "a power up sound": ["power", "level"],
    "landing after a jump": ["jump", "land"],
    "a wooden knock": ["wood", "knock"],
    "a happy jingle": ["jingle"],
    # animals and nature, from FSD50K's CC0 clips (D-044)
    "birds singing": ["bird", "chirp"],
    "a dog barking": ["bark", "dog"],
    "a cat meowing": ["meow", "cat"],
    "a rooster crowing": ["rooster", "chicken"],
    "frogs croaking": ["frog"],
    "rain falling": ["rain"],
    "thunder rumbling": ["thunder"],
    "waves on the beach": ["waves", "surf"],
    "a squeaky door": ["door"],
}
KNOWN_GAPS = ["a cow mooing", "a cartoon boing", "a slide whistle"]


@pytest.mark.models
@pytest.mark.skipif(not _ready(), reason="sound library not indexed (or no Qdrant / CLAP env)")
def test_retrieval_spot_check() -> None:
    queries = list(SPOT_CHECK) + KNOWN_GAPS
    results = dict(zip(queries, find_sfx(queries, k=5), strict=True))
    misses = []
    for query, expected in SPOT_CHECK.items():
        text = " ".join(
            f"{c.sound_id} {c.description} {' '.join(c.tags)}".lower() for c in results[query]
        )
        if not any(word in text for word in expected):
            misses.append(f"{query}: {[c.sound_id for c in results[query][:3]]}")
    for query in KNOWN_GAPS:  # reported for the owner, not asserted
        best = results[query][0]
        print(f"gap? {query!r} → {best.sound_id} ({best.score:.2f})")
    assert not misses, misses
    with_cap = find_sfx(["a happy jingle"], k=5, max_duration_s=1.0)[0]
    assert all(c.duration_s <= 1.0 for c in with_cap)
    clean = find_sfx(["birds singing in the morning"], k=5, avoid=["traffic", "vehicle"])[0]
    assert len(clean) == 5
    for c in clean:
        text = f"{c.description} {' '.join(c.tags)}".lower()
        assert "traffic" not in text and "vehicle" not in text, c.sound_id
        assert "bird" in text or "chirp" in text, c.sound_id
