# The director on a project: durable memory vs. a derived cache

**What it is.** A project film's working folder is a *cache* (D-091): the servers rebuild it from the store on every
call, so it can be deleted. The director's own files (its state, the story, the recorded-line list, the shot plans,
the owner's notes) are *memory*: lose them and the director forgets what the owner approved. Mixing the two in one
folder is the easy mistake. We keep both ideas and one folder by giving the director a home in the project
(`projects/<project>/director/<film>/`) and symlinking `story/` and `director/` into the working folder
(`director/project_mode.py`). Every stage and check still reads `<folder>/story/story.json`, so the old code runs
unchanged, and `rm -r` of the working folder loses renders but not progress.

**Why plan per act.** One planning call for a whole film asks a 14B model to hold every scene at once. An act (a
place, a few characters, 2 to 4 camera angles) is a size it plans well. It also lets the owner steer: act 2 is
planned only after act 1 is approved, so a note on act 1 reaches act 2. The cost is that film-level taste rules (an
arc with a peak, a calm ending, no more than one grumpy face) must judge the *film so far*. `advise_shotplan`
therefore gets the earlier acts' shots (`prior`) and a `final` flag: rules about the whole film that cannot hold
yet wait for the last act, and a complaint about a shot of an earlier act is dropped because this plan cannot fix it.

**Rules in code, choices in the model.** Which library characters exist, adding them to the film, creating acts,
removing shots a re-plan dropped, and the cache (does this act need rendering?) are code. The model decides the
story, the acts and each act's shots. Pins (`--pin-cast`, `--pin-places`) are enforced twice: as an `enum` in the
JSON schema the model must obey, and as a check (the model could still list one and not use it).

**Gotchas.**
- `render_act` is a no-op when the act's cache key is fresh, which is what makes resume cheap and idempotent: every
  step of the act loop can simply run again.
- A revised act changes its shots' specs, so only its cache key changes; `export_movie` then reuses the other act
  videos. That is the proof that acts are the unit of rendering.
- `StageCtx.tool(name, /, **args)`: `name` must be positional-only, because `build_puppet` takes a `name` argument
  of its own. (The old code had this latent bug; no test had built a puppet through the director.)
