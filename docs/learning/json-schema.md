# JSON Schema: the contract between the LLM and our code

**What:** JSON Schema is a standard language for describing the shape of JSON: required fields,
types, allowed values, number ranges, patterns. A validator checks a document against it and lists
every mismatch with its location. We use draft 2020-12 with the `jsonschema` Python package.

**Where:** `schemas/rig.schema.json`, `shot.schema.json`, `shotlist.schema.json`,
`film.schema.json`. Code: `studio_core/schema.py`. CLI: `uv run scripts/validate.py <file>`.

## Why it matters in an LLM pipeline

"Rules in code, judgment in the LLM" (CLAUDE.md) needs a precise boundary, and the schema is it:

1. **The LLM writes intent as JSON** (a shot: who, where, which motions, when), and code turns it
   into a `.sif`. The schema is the exact contract for that JSON.
2. **The schema is part of the prompt.** Field descriptions, enums (`"motion": one of wave, nod,
   …`) and ranges tell the model what is allowed. Good descriptions are prompt engineering.
3. **Errors are feedback.** `characters[0].actions[2].motion: 'wavee' is not one of [...]` is
   specific enough for the model to fix its own output; the director loop (Step 5) sends it back,
   as `scripts/check_tool_calling.py` already does for tool arguments.
4. **Constrained decoding.** Ollama can force a model's output to match a schema (the `format`
   field of `/api/chat` accepts a JSON Schema). Invalid JSON then becomes impossible, though
   *semantically* wrong JSON is still possible. That is why we also have semantic checks.
5. **The same contract serves MCP tools.** Every MCP tool declares a JSON Schema for its inputs;
   the shot schema's `$defs` can be reused there.
6. **Evals (Step 7) and fine-tuning:** "the shot list validates" is the first, free, objective
   reward signal for GRPO (ROADMAP Step 7).

## Two layers of checking

| Layer | Catches | Example |
|---|---|---|
| **Schema** (`schema_issues`) | types, required fields, enums, ranges, patterns, typos via `additionalProperties: false` | `motion: "wavee"`, `position: [3, 0.9]`, an unknown `speed` param |
| **Semantic** (`check_rig`, `check_shot`, `check_shotlist`) | rules across fields that a schema can't express | one root bone; no cycles; a joint attaches to a part of the parent bone; draw order lists every part once; actions start inside the shot; the speaker is in the shot; unique shot ids |

Semantic checks run only after the schema passes, so they can trust the types.

## Design choices in our schemas

- **Closed by default:** `additionalProperties: false` everywhere, so a misspelled field is an
  error instead of being silently ignored.
- **Enums for everything the code implements** (motions, expressions, camera moves, views). Adding
  a motion to the library means adding it to the enum, so the model can never ask for one that
  doesn't exist.
- **Pixels in rigs, frame fractions in shots:** rigs are about art (image pixels); shots are about
  composition (`[0.5, 0.9]` = centre, near the bottom), independent of resolution.
- **Seconds in shots, frames in `.sif`:** the LLM thinks in seconds; code converts
  (`studio_core.sif.frames`), so frame math never reaches the model.
- **Rest pose = the art as drawn:** bones declare `direction_deg` (90 = up, -90 = down) and
  motions are offsets from rest, so "raise the arm 150°" means the same thing on every rig.

## Gotchas

- `prefixItems` + `items: false` is the 2020-12 way to say "exactly an [x, y] pair". The old
  `items: [..]` tuple form is a different draft.
- `$ref` across files (`shotlist` → `shot.schema.json`) resolves against each schema's `$id`; our
  validator registers every schema in a `referencing.Registry`, so nothing is fetched from the
  network.
- `default` in a schema is documentation; validators don't fill it in. Code applies defaults.
- A schema can't express cross-field rules; don't contort it trying. Write a semantic check with a
  test.
