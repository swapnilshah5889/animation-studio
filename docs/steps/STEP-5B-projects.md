# Step 5B / 5C data layer: projects, acts and the store

Status: the **data layer is built and tested**. Adoption by the MCP servers and the director is the task
list at the end (not started). Decisions: D-082 (projects), D-083 (acts, source vs cache), D-084 (store).
Learning note: `docs/learning/storage-interface-and-contract-tests.md`.

## What was built

| Piece | Where |
|---|---|
| `ProjectStore` Protocol (documents + assets), errors, ULID ids | `studio_core/src/studio_core/store/{base,errors,ids}.py` |
| `FileSystemStore` (the `projects/<id>/` layout), `MemoryStore` | `store/filesystem.py`, `store/memory.py` |
| `Project` API: library, versions, films, acts, shots, render records | `studio_core/src/studio_core/project/project.py` |
| Act cache key and `is_stale` (pure functions) | `project/staleness.py` |
| Schema check per document kind | `project/validation.py` + `schemas/{document,asset_record,project,character_entry,background_entry,film_spec,act,shot_doc,act_render}.schema.json` |
| Migration of the old film folders | `scripts/migrate_to_projects.py` |
| Tests | `tests/test_store_contract.py` (one suite, both stores), `tests/test_project.py`, `tests/test_migrate_to_projects.py` |

`projects/` is git-ignored like `films/`. Nothing existing was changed: old films are read exactly as before.

### Documents

Every spec is a JSON document with the same envelope: `schema_version`, `kind`, `id`, `project_id`,
`owner_id` (`"local"`), `created_at`, `updated_at`, `rev`, and for film-scoped kinds `parent_id` (the
film). The **store** sets `rev` and the timestamps; callers never do. Kinds today:

| kind | what | where on disk (`projects/<project-id>/`) |
|---|---|---|
| `project` | name, premise, style | `project.json` |
| `character`, `background` | one **entry** with an append-only `versions` list; a version maps relative file names (`rig.json`, `parts/head.png`) to asset records | `characters/<id>/character.json`, `backgrounds/<id>/background.json` |
| `film` | title, style, `cast` and `places` as `{id, version}` | `films/<id>/film.json` |
| `act` | `order`, title, `background` ref, `cast` refs, `beats`, ordered `shot_ids` | `films/<film-id>/acts/<id>.json` |
| `shot` | `act_id` and `spec`: the engine-neutral shot spec | `films/<film-id>/shots/<id>.json` |
| `act_render` | the cache key an act was last rendered from (id = the act id) | `films/<film-id>/act_renders/<id>.json` |
| any other | allowed; no kind schema, only the envelope | `films/<film-id>/<kind>s/` or `documents/<kind>/` |

Media are **assets**: `projects/<id>/assets/<aa>/<sha256>`, record `{id, sha256, mime, bytes}`, id = the
sha256. Specs hold ids and `{id, version}` references only, and the store rejects path-like strings.
Ids are ULIDs (`new_id()`); a project id may be chosen by the caller (`test-cast`) because it is also the
folder name. Characters, backgrounds and films also have a `slug` ("kit") that tools and the LLM can use:
the `Project` API accepts an id or a slug everywhere.

### Using it

```python
from studio_core.project import Project
from studio_core.store import FileSystemStore

store = FileSystemStore(REPO_ROOT / "projects")          # or MemoryStore() in tests
project = Project.create(store, name="Pip and friends", style="storybook")   # or Project.open(store, id)

kit = project.publish_character("kit", {"rig.json": rig_bytes, "parts/head.png": head_bytes})  # -> {id, version: 1}
project.publish_character("kit", {...}, note="bigger ears")     # same slug => version 2; version 1 never changes
project.publish_background("orchard", {"plate.png": plate_bytes})

film = project.create_film("The Lost Kite", cast=["kit", "bo"], places=["orchard"])  # pins latest versions
act = project.add_act(film["id"], "Morning", background="orchard", cast=["kit"], beats=["Kit wakes up"])
project.add_shot(film["id"], act["id"], {...shot spec...})       # one call per camera angle
project.upgrade_reference(film["id"], "character", "kit")        # opt in to kit's newest version (also in the acts)

resolved = project.resolve_character("kit")                       # latest; or resolve_character("kit", 1)
project.read_file(resolved, "rig.json")                           # bytes
project.materialize(resolved, workdir / "kit")                    # a real folder for tools that need files

key = project.act_key(film["id"], act["id"], "synfig-1.4")        # pure hash of the specs + versions + engine
project.is_act_stale(film["id"], act["id"], "synfig-1.4")         # True until a render is recorded for this key
project.record_render(film["id"], act["id"], "synfig-1.4", cache_key=key, video=asset_record)
project.stale_acts(film["id"], "synfig-1.4")                      # what "render" / "export all acts" must redo
```

Rules enforced: a film's and an act's references must exist; an act's background and cast must belong to
its film; published versions are append-only (`ImmutableVersionError`); two writers on one rev, one wins
(`RevConflict`; `Project` retries its read-modify-write helpers).

**Staleness.** The key is `sha256` over canonical JSON of: the act (which carries its background and cast as
`{id, version}`), its shot documents in `shot_ids` order, the engine id string, and an `extra` dict (the film's
style id). `rev`, timestamps, owner and project id are left out, so saving without changing anything does not
invalidate a render. Compute the key *before* rendering and pass it to `record_render`, so an edit made during
a render still shows as stale. Bump `KEY_VERSION` to invalidate every cache.

### Migration

```bash
uv run scripts/migrate_to_projects.py            # dry run: prints the plan, writes nothing
uv run scripts/migrate_to_projects.py --apply    # builds projects/test-cast/
```

Each `films/<f>/characters/<slug>/` and `backgrounds/<slug>/` folder becomes a *version* of a character or
background (identical folders in different films are one version; a changed one is the next version, so
kit and bo each have two). Each old film that has a `film.json` becomes a film document referencing them
(`source.folder` records `films/<slug>`, relative). Films without `film.json` (step1-3, first-shot,
inspector-check, review-reel) are skipped. **No big copies:** each file enters the content-addressed store by
copy-on-write clone (APFS), else hard link, else copy (`--mode auto|clone|link|copy`, default auto), and
identical files across films are stored once. Verified on the real films: 12 versions and 4 films, about
17 MB of disk used for about 130 MB of files. The old folders are only read; re-running adds only what is new.
Shots, audio, edits and director state stay in the old folders until the adoption below.

## Follow-up tasks (not started)

1. **Config and entry points.** Add a `projects_dir` to `config/studio.toml` (default `<repo>/projects`) and a
   small `open_project(project_id)` helper in `studio_core`, so servers do not build paths. A film's working
   folder (render scratch, `materialize` output) is derived data under the cache dir, not in the store.
2. **MCP servers take `project` and `film` ids** (no engine fields, D-030), one at a time, each with its
   own tests; keep accepting the old `film` folder name until all five are done:
   - `comfy_mcp`: `build_puppet` and `choose_background` publish a new character/background *version* to the
     project; `describe_art` lists the project library, not one film. Biggest change: the art stages write
     into `store.put_asset` / `publish_*` instead of `films/<film>/characters/`.
   - `synfig_mcp`: `add_character` / `add_parallax_background` resolve `{id, version}` from the project (via
     `materialize` into a cache folder for the engine); `create_scene` stores a shot document (`add_shot`) and
     takes an act id; `render_shot` returns an asset record and `describe_film` lists acts and shots.
   - `audio_mcp`: voices live on the character version; lines and music cues become assets in the project;
     shots reference them by asset id.
   - `edit_mcp`: `create_film` becomes `create_film` in the project; `assemble` / `render_film` work on act
     videos; **add `export_all_acts`** (render stale acts, then stitch the act videos in `order`).
   - `qa_mcp`: `check_frame` / `check_film` take project + film (+ act) ids and read specs from the store.
3. **Director (`director/`):** open a project instead of a flat film folder; the cast stage first reuses
   project characters and places and only runs the art stages for missing ones (publishing them to the
   library); the shot-planning stage plans per act (several camera angles per act); approvals and state become
   per-act documents, with an append-only event log document for stage runs (D-084); `retry` of one act
   touches only that act; replace `--import-cast` with "film references project cast". Run *after* the director
   session currently editing `director/` has finished.
4. **Shot specs:** validate `shot` documents' `spec` against `schemas/shot.schema.json` (today only the
   envelope and `act_id` are checked) and put audio line cues in the shot (so a changed line makes the act stale).
5. **Render scheduling:** `stale_acts` -> render each -> `record_render` with the key computed before the render;
   decide where act videos live (assets in the store; local cache path derived from the asset id).
6. **Concurrency:** if render jobs ever run in parallel on several nodes, add per-document claim/lock documents
   (the Windows node, Step 6 containers).
7. **Later (Step 14):** a database/object-storage store passing `tests/test_store_contract.py` unchanged; users
   replace `owner_id`; a `list_documents` query with filters/paging.

## Open questions for the owner

- Ids are opaque ULIDs with a readable `slug`; folders under `projects/` are therefore ULIDs. Fine, or would you
  prefer `FileSystemStore` to name folders `<slug>-<ulid>` for browsing (an implementation detail of that store)?
- Old films without `film.json` were skipped by the migration (smoke-test films). Say if you want them imported.
