# Embeddings and vector search: finding a sound by describing it

How `find_sfx("a soft cartoon pop")` works (`studio_core/audio/sfx.py`, task 3.5). The same
machinery (embed, store, search, re-rank) is the core of RAG, which later steps reuse for
scripts and story memory.

## An embedding is a position in "meaning space"

A model turns an input into a list of numbers (a **vector**) such that similar things land
close together. Our vectors have 512 numbers.

**CLAP** (Contrastive Language-Audio Pretraining, `laion/larger_clap_general`) has two
encoders, one for audio and one for text, trained on hundreds of thousands of (sound, caption)
pairs. Training pulls each sound's vector toward its own caption's vector and pushes it away
from the other captions. Afterwards, a recording of a door creaking and the words "a creaking
door" end up near each other. That's what lets a *text* query find *audio*: both live in the
same space.

## Similarity is an angle

We compare vectors by **cosine similarity**, the cosine of the angle between them: 1 means the
same direction, 0 unrelated. Our worker L2-normalizes every vector (length 1), so cosine is a
plain dot product. Our first test queries:

| | "birds singing" | "a dog barking" | "a soft cartoon pop" |
|---|---|---|---|
| "birds singing" | 1 | 0.55 | 0.08 |

Two animal sounds sit close together; a cartoon pop doesn't. Scores aren't probabilities. A
"good" CLAP match is often only 0.3–0.6, so compare scores against each other, not against a
fixed bar.

## The vector database

**Qdrant** stores **points**. Each point has an id, a vector and a **payload** (any JSON: here
the sound's manifest entry). One kind of point lives in one **collection** (`sfx`, 512-d,
cosine). A query sends a vector and gets back the nearest points. Payload **filters**
("duration ≤ 1 s", "id in this list") apply during the search, not afterwards.

To stay fast with millions of points, Qdrant uses an **HNSW** graph: approximate nearest
neighbours, trading a tiny bit of accuracy for speed. With our ~800 sounds it hardly matters,
but the code doesn't change when the library grows.

## Hybrid search: meaning plus words

Pure vector search failed one obvious query. "footsteps on wood" returned dice throws, even
though the library has files tagged `footstep`, `wood`. A single 0.3 s step is a poor match
for CLAP's idea of "footsteps". Words fix that:

1. Take the 40 nearest sounds by vector.
2. Add the sounds whose tags or description contain the query's words (roughly stemmed:
   `footsteps` ~ `footstep`), scored by the same vector similarity.
3. Re-rank the union: similarity + 0.25 × (share of query words matched).

After that change, "footsteps on wood" finds footsteps first, and "a door opening" rises from
0.44 to 0.65. Meaning still decides when there are no matching words. This "dense + keyword"
combination is standard in RAG systems for the same reason: embeddings catch paraphrases,
keywords catch exact names.

## Indexing is idempotent

A point's id is derived from the sha256 of the sound's audio. Re-running the indexer only
embeds new sounds and deletes the ones gone from the manifest, so it's safe to run after
every library change, and a crashed run just resumes.

## Gotchas

- **Randomness in preprocessing.** CLAP's feature extractor takes random crops of clips
  longer than 10 s. Without re-seeding, the same file would get a slightly different vector
  each run. The worker seeds per clip.
- **Short clips embed poorly.** A 50 ms click carries little information. Tags carry a lot
  of the weight for very short sounds.
- **The library bounds the answers.** Search can only return what's there. "A dog barking"
  returns *something* with a low score. The spot-check reports such gaps instead of hiding
  them.
- **Embeddings are model-specific.** Changing the CLAP model means re-indexing everything:
  vectors from different models aren't comparable.
