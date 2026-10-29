# The agent loop: what makes a model an agent

Read with `tool-calling.md` (the wire format). This note is about the *loop around it* in
`director/src/director/` and why it is shaped the way it is. The files to read, in order:
`loop.py` (one conversation), `dispatch.py` (one tool call), `runner.py` (the stages around
conversations). About 400 lines in all.

## The loop in five lines

```
ask the model (messages + the tools it may use)
  it asked for tools?  -> run each, append the results as `tool` messages, ask again
  it answered in text? -> ask CODE whether the work is complete
                           complete: stop.   not complete: nudge once, then give up.
```

An LLM call is stateless. The "conversation" is a list of messages that we send in full each
time; the model's memory is that list and nothing else. Everything below is about managing it.

## Tool calling: the model proposes, code disposes

The model never runs anything. It returns `tool_calls: [{name, arguments}]`, and `dispatch.py`
decides what happens. Before a call runs, code checks it in this order (cheapest first), and a
failed check is **not an exception**: it becomes the text of the `tool` message, because the model
can only fix what it can read:

1. Is the tool in this stage's list? (A model with 60 tools picks worse than one with 15.)
2. Are the arguments an object? (Some models send a JSON *string*; we parse it.)
3. Does the tool's own JSON Schema accept them?
4. Do the ids exist (`character_id` must be one of the characters in this shot)?
5. A precondition: `render_shot` is refused until a frame was checked (`CallContext.preconditions`).

Two tricks that remove whole classes of mistakes: **hide what code already knows** (`film`,
`shot_id` are stripped from the schema the model sees and injected on every call, so it cannot
get them wrong), and **short results** (a result is cut to ~600 tokens; a model drowning in JSON
forgets the task).

## State: three different memories

| Memory | Lives in | Why |
|---|---|---|
| The conversation | the `messages` list, one fresh list per stage / per shot | Small history = cheap, fast, fewer distractions. Never replayed after a crash |
| Progress | `films/<slug>/director/state.json` | Which stage, attempts, approvals, cost counters. Saved atomically (temp file + rename) |
| The work | the film folder | The truth about what exists. A stage is complete when `checks.py` looks at the folder and says so |

Resume = read the state file, then **re-verify from the top** with the checks (a deleted file
puts that stage and everything after it back to pending), then restart the stage that was
`running` with a fresh conversation. This works because the tools are idempotent (the same
request makes the same file), so asking again is safe.

## Stop conditions: a loop that cannot stop is the classic agent bug

The model is never trusted to say it is finished. Every way the loop could run forever has a
number in `config.LoopLimits`, enforced by code:

- **done**: `complete()` returned None (checked after every batch of tool calls, so the loop
  stops the moment the shot is rendered, not when the model decides to say so);
- **unfinished**: the model answered in text, was nudged once ("Not finished yet: shot X is not
  rendered"), and still did not finish;
- **stuck**: the same tool was refused 3 times in a row, or the identical call (name +
  arguments) was requested 3 times;
- **limit**: 25 model calls, 12 refusals, or the stage's wall clock ran out.

Why code and not instructions: "stop after three tries" in a prompt is a request; a counter is a
fact. A stuck stage ends `failed` with the reason in `state.json` and waits for the owner. It
never retries silently.

## Planning is a different kind of call

Story and shot plans are not tool calls. They use Ollama's `format` (a JSON Schema), which
constrains *decoding* so the reply is always valid JSON of the right shape. That fixes syntax,
not sense: the schema cannot know a scene's place exists or that the seconds add up. So code
checks the sense (`plans.check_story`, `check_shotplan`), and on a problem sends the model the
list once more ("Fix these problems...") with thinking on. The enums are built at run time from
the tools' own capability lists (`describe_film`), so the model can only name a motion that
exists.

## Human approval: a pause that survives a restart

An approval is not a prompt to the user in the middle of a run. The stage finishes, the director
writes `director/review/<name>.md`, sets `awaiting_approval` in the state file and **exits**.
`approve` flips one field; `resume` carries on. `revise "note"` re-runs the stage with the note
added to the model's brief. Nothing waits in memory, so a laptop reboot between "story" and
"characters" loses nothing. `--auto` approves every checkpoint, for runs you trust.

## Gotchas met while building it

- A refusal must reach the model as a normal tool result. An exception would end the loop;
  feedback lets the model repair itself, and the caps still bound it.
- Check `complete()` *after tool calls*, not only after a text reply, or a model that never writes
  a closing sentence runs to the model-call cap.
- Thinking models burn tokens on planning (a 15-second story took ~230 s and ~2300 output tokens
  on qwen3:14b with thinking on). Use it for plans, switch it off for tool calls.
- Two big models do not fit the 24 GB Mac together: the vision check (qwen3-vl) unloads the chat
  model first (`MemoryGuard.release_llm`), and the chat model reloads on the next call.
- Tests use a scripted fake model (`tests/director_world.py`): the loop, caps, refusal feedback,
  approvals and crash-resume are all tested offline in under a second.
