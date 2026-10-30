# One storage interface, one contract test suite

Where: `studio_core/src/studio_core/store/` and `tests/test_store_contract.py`. Decision: D-084.

## The idea

Everything that reads or writes project data talks to a `ProjectStore` (a `typing.Protocol`: a list of
method signatures, no base class). Today two classes satisfy it:

- `FileSystemStore`: the `projects/<id>/...` folders on disk.
- `MemoryStore`: dicts, for tests.

A database plus object-storage store can be added later without touching the director, the MCP servers
or the GUI, *if* it behaves the same. "Behaves the same" is the hard part, and it is what the contract
test suite is for.

## The contract suite

`tests/test_store_contract.py` has one fixture, `store`, parametrised over the implementations
(`params=["memory", "filesystem"]`). Every test takes `store` and nothing else, so each test runs once per
implementation and cannot know which one it got. A new store is one more fixture param. It must pass
unchanged. If a test needs an `if isinstance(store, ...)`, the interface is leaking.

The same pattern is used for any "many backends, one behaviour" seam: TTS engines, render engines
(Step 6), vector stores.

## What the contract pins down (and why each rule exists)

- **Optimistic concurrency (`rev`).** A write names the rev it read. A stale rev raises `RevConflict` and
  changes nothing. This replaces locks across processes (the director and five MCP servers all write).
  A test fires 8 threads at one rev and asserts exactly one wins.
- **Project scoping.** Every call takes a `project_id`; the same document id in two projects is two
  documents; assets are per project. This is the tenancy boundary that per-user permissions will hang off.
- **Content addressing.** An asset's id *is* the sha256 of its bytes. Same bytes give the same id (stored
  once), and the id can be verified by anyone. This is what lets blobs move to S3-style storage.
- **No paths in specs.** The store refuses any string that looks like a path (`/...`, `~`, `C:\`).
  References are `{id, version}`. This rule lives in the store so no caller can forget it.
- **Copies out.** What `get` returns is a copy: editing it does not change the store. (Dict-backed
  stores get this wrong by accident, so it is tested.)

## Mutation checking the tests

Passing tests only prove something if they can fail. After writing the suite, break each guard on purpose
(turn the rev check into a no-op, make the filesystem store ignore the project id, hash the wrong bytes,
drop the paths rule) and confirm a test goes red; then restore it. A guard that nothing notices missing is
not tested. All the guards above were checked this way; one cache-key field was found to be redundant
that way too (the act already carries its `{id, version}` references) and removed.

## Gotchas

- **Content-addressed + hard links.** Importing a file into the asset store by hard link is free, but
  if a tool later rewrites the original *in place*, the stored asset changes under its own hash. The
  migration therefore prefers a copy-on-write clone (APFS `cp -c`), then a hard link, then a copy.
- **Ids.** ULIDs (time-sortable, no dependency, 26 characters) identify things; a short `slug` is the
  human/LLM handle. Never put a name or a path in an id.
- **Cross-process safety** on the filesystem store is an advisory `flock` on the project folder plus an
  atomic rename for each write. It is enough for local use; a database store gets it from transactions.
- **Derived data is not stored as truth.** Renders are cache; their keys are in `project/staleness.py`
  (a pure function), tested without any store.
