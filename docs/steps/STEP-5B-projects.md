# Step 5B / 5C data layer: projects, acts and the store

Status: the **data layer is built and tested, and the five MCP servers have adopted it** (section
"Adoption by the MCP servers" below). Adoption by the director is the open task list at the end.
Decisions: D-082 (projects), D-083 (acts, source vs cache), D-084 (store).
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

## Adoption by the MCP servers (done)

One door: `studio_core.workspace.Workspace.open_film(film, project=None)` returns the `FilmFolder` every
tool already works on. No `project` = an old film folder under `films/`, exactly as before (every old
tool call and test is unchanged). With a `project` the folder is **derived data** in the work directory
(`[paths] work`, default `~/ai-studio/work/<project>/<film>/`, safe to delete) and is kept in sync with the
store by a `ProjectLink` (`studio_core/project/link.py`):

| Direction | When | What |
|---|---|---|
| store to folder (`pull`) | every tool call | cast and places at the **versions the film pins** (`materialize`, a clone, a `.pinned` marker skips unchanged ones), every shot document as `shots/<id>/shot.json`, the film's audio, a derived `film.json` (style) |
| folder to store, shots | `shot_spec.save` calls `FilmFolder.link.shot_saved` before writing the file | a saved spec becomes a `shot` document of an act (a new shot needs `act` when the film has several; an existing shot stays where it is). Refused saves write nothing |
| folder to store, audio | audio tools call `sync_audio` | lines, mouth cues, music cues and voices become assets in the film's `audio` document; every shot document gets an `audio` snapshot (content ids of its lines and music cue), so **a re-recorded line or a new cue makes its act stale** even though the spec only names the line |
| folder to store, art | `build_rig`, `build_puppet`, `split_depth_layers` call `publish_character` / `publish_background` | a new **version** in the project library (no change = no new version), added to the film (the film and its acts move to it) |

| Server | What changed |
|---|---|
| `edit_mcp` | `create_film(project=...)`; new `describe_project`, `list_acts` (with `stale`), `add_act`, `edit_act`, `reorder_acts`, `remove_act`, `reorder_shots`, `remove_shot`, `render_act`, `export_movie` ("export all acts"), `clear_renders`. `assemble` / `render_film` stay for old film folders |
| `synfig_mcp` | every tool takes `project`; `create_scene` takes `act`; `build_rig` publishes the character |
| `audio_mcp` | every tool takes `project`; recordings are kept in the project after each call |
| `comfy_mcp` | every tool takes `project`; `build_puppet` / `split_depth_layers` publish a library version (`library_version` in the result); `describe_art` lists the project library |
| `qa_mcp` | every tool takes `project` |

**Acts** (`studio_core/acts.py`): `render_act` renders the act's shots in cut order through the engine
(`Renderer`, today Synfig), joins them with melt into the act video, stores it as an asset and records the
render with the cache key computed *before* rendering. `export_movie` renders only acts that are stale (or have
no video), then joins the act videos in the acts' `order` (cut or crossfade, optional title cards), writes
`edit/final.mp4` and checks it (size, streams, length, loudness). The engine and the quality are part of the
key (`Target`, id `synfig:final`), so a preview never satisfies a final export. The act key leaves out
`order`, `title` and `beats` (story, not picture), so reordering or retitling acts re-renders nothing.
`clear_renders` deletes every render record and derived video; export then rebuilds the same film from the specs.

**Verified:** `tests/test_acts.py::test_three_acts_with_the_real_engine_end_to_end` (real Synfig, preview
quality): 3 acts, a place each, 3 camera angles each, one recorded line, renders per act; editing one shot
renders only its act; export gives one movie that passes the checks; after `clear_renders` and deleting the
work folder, the re-exported movie has identical frames (frame md5). The same flow runs with a stand-in
renderer through the MCP client (`tests/test_edit_mcp_acts.py`). Key guards were mutation-checked (always-fresh
staleness, shots/audio/engine left out of the key, acts stitched in id order, stale check skipped, work folder
or shot listing not scoped by project/film, preview satisfying final): every mutant failed a test.

**Not done / notes:**

- Sound effects are named by library id in the shot spec and are not part of the shot's audio snapshot (the
  CC0 library is treated as stable). A voice change only re-renders acts once the line is spoken again.
- Voices live in the film's `audio` document (written to `characters/<slug>/voice.json` in the folder), not in
  the character version: casting a voice must not publish a new character version. Migrated character versions
  that still contain `voice.json` keep it; the film's voice wins in the folder.
- Character slugs used in shot specs must match `^[a-z][a-z0-9_]{0,39}$` (the shot schema); library slugs allow
  `-` too, so name library characters with `_`, not `-`, if a shot will use them.
- Act videos and the movie are re-encoded by melt (cut joins); music restarts per shot, as before. The movie
  is not stored in the project (derived, at `edit/final.mp4` of the work folder); old act video assets stay in
  the store after a re-render until a clean-up task exists.
- Shots are re-rendered per act, not per shot (an act with one changed shot renders all its shots again).
- `render_shot` / `render_preview_frame` on a project film render in the work folder and record nothing; only
  `render_act` / `export_movie` record renders.
- The director (`director/`) still builds flat film folders; the servers accept both.

## Follow-up tasks

1. ~~**Config and entry points.**~~ Done: `[paths] projects` / `work` in `config/studio.example.toml`,
   `Workspace` (see above).
2. ~~**MCP servers take `project` and `film` ids**~~ Done for all five servers (see above). The original plan, for reference:
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
4. **Shot specs:** validate `shot` documents' `spec` against `schemas/shot.schema.json` (today the servers
   validate on save through `shot_spec.check`, the store only checks the envelope and `act_id`). ~~Audio line
   cues in the shot~~ done (the `audio` snapshot).
5. ~~**Render scheduling**~~ Done in `studio_core/acts.py` (act videos are assets; the local copy is a clone in
   the work folder). Still open: per-shot render cache inside an act, and parallel act rendering on two nodes.
6. **Concurrency:** if render jobs ever run in parallel on several nodes, add per-document claim/lock documents
   (the Windows node, Step 6 containers).
7. **Later (Step 14):** a database/object-storage store passing `tests/test_store_contract.py` unchanged; users
   replace `owner_id`; a `list_documents` query with filters/paging.

## Open questions for the owner

- Ids are opaque ULIDs with a readable `slug`; folders under `projects/` are therefore ULIDs. Fine, or would you
  prefer `FileSystemStore` to name folders `<slug>-<ulid>` for browsing (an implementation detail of that store)?
- Old films without `film.json` were skipped by the migration (smoke-test films). Say if you want them imported.
