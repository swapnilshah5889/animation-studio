# MCP: how the director gets its hands

The **Model Context Protocol** is how an LLM application (the *client*: Claude Code today, our
director in Step 5) uses capabilities that live in another program (the *server*: `synfig_mcp`).
The model never imports our Python. It sees a list of tools, each with a name, a description and a
JSON Schema for its arguments, and asks the client to call one. The client sends a JSON-RPC message
to the server, the server runs the function, and the result comes back into the conversation.

Written with tasks 2.7–2.8.

## The three things a server can offer

| Primitive | Who decides to use it | Ours |
|---|---|---|
| **Tools** | the model | all of `synfig_mcp`: edit a shot, render it |
| Resources | the application (read-only data it attaches) | none yet; `describe_*` tools play this role, because every client supports tools |
| Prompts | the user (templates they pick) | none yet |

## Transports

- **stdio:** the client starts the server as a subprocess and they talk over stdin/stdout. This is
  what Claude Code and the Inspector use locally (`uv run synfig-mcp`).
- **Streamable HTTP:** the server runs on its own, maybe on another machine. That comes in Step 5
  for the Windows render node.

**Gotcha:** on stdio, stdout *is* the protocol. A stray `print()` in a tool corrupts the stream
and the client disconnects. Log to stderr. Our subprocesses (Synfig, ffmpeg) capture their
output, so they're safe.

## How a Python function becomes a tool

```python
@server.tool()
def set_expression(
    film: FilmArg, shot_id: ShotArg, character_id: CharArg, expr: Expression, start_s: Seconds
) -> ShotUpdate:
    """Change the character's expression (brows and resting mouth) from start_s on. ..."""
```

The SDK (`MCPServer`, formerly called FastMCP) reads the function:
- the **name** becomes the tool name
- the **docstring** becomes the description the model reads to decide when to call it
- the **type hints** become the input JSON Schema: `Literal[...]` becomes an `enum`, and
  `Annotated[float, Field(ge=0, description=...)]` adds a range and a description
- the **return type** (a pydantic model) becomes an output schema, and the result is sent as
  structured JSON

So type hints and docstrings are prompt engineering. Ranges and enums in the schema stop many bad
calls before they reach our code, and the model sees the allowed values upfront.

## Errors the model can fix

A tool raising `ToolError("unknown bones ['tail']; ...")` returns a normal result with
`is_error: true` and that message (the SDK prefixes "Error executing tool <name>:"). The model
reads it and tries again. Any other exception is a crash: the model only sees "Error executing
tool". So we turn every validation error into a `ToolError` with a message that says what to do
next (the `fixable()` context manager in `server.py`).

## Why many small tools

One `make_shot(everything)` tool would need the model to write a perfect spec in one go, and one
mistake would fail the whole call. Small verbs (`add_character`, `apply_motion`, ...) each change
one thing, each is checked, and a failure points at exactly one argument. They are also easy to
log, replay and evaluate later (Step 7 evals).

## The Inspector: a client for humans

The MCP Inspector (`@modelcontextprotocol/inspector`, pinned to 2.9.0) is a client you drive by
hand. It shows exactly what a model would see:
- each tool's name, description and input schema (the enums and ranges from our type hints)
- each call's raw result: `content` (text for the model), `structuredContent` (the JSON that
  matches the output schema) and `isError`

It reads the same `.mcp.json` as Claude Code:

```bash
npx -y @modelcontextprotocol/inspector@2.9.0 --config .mcp.json --server synfig_mcp
```

That opens the web UI (the URL it prints carries a session token). `--cli` mode makes it
scriptable: `scripts/inspector_check.py` lists the tools and calls every one, including calls
that must be refused, on a scratch film. Gotcha: Inspector 2.9 asks for Node ≥ 22.19; with this
machine's Node 22.13 it prints warnings but works.

**What it showed us** (task 2.8):
- **Docstrings reach the model verbatim, indentation included.** Every description carried
  `\n        ` from the source code: noise in the model's prompt on every request. Tools are now
  registered with `inspect.cleandoc`, and a test guards it.
- **Argument validation happens before our code runs.** `motion: "wavee"` never reaches
  `apply_motion`. pydantic rejects it against the enum and the error lists the allowed values.
  That's why enums and ranges belong in the type hints.
- **Errors arrive as normal results** with `isError: true` and the text prefixed
  "Error executing tool <name>:". A client that only reads text still gets the full message.
- **Every result is sent twice:** as JSON text in `content` and as an object in
  `structuredContent`. Clients that ignore output schemas still work.

## How a tool schema reaches the model

```
server: @tool functions ──tools/list──▶ client (Claude Code, the director) ──▶ model request:
        name, description,                 adds the server prefix:              "tools": [{name,
        inputSchema, outputSchema          mcp__synfig_mcp__apply_motion         description,
                                                                                 input_schema}]
model ──tool_use {name, input}──▶ client ──tools/call──▶ server ──result──▶ client ──▶ model
```

The model only ever sees the name, the description and the input schema. Those three are its
whole manual for the tool, so every word in a docstring is paid for on every request.

## Claude Code as the client

`.mcp.json` at the repo root registers the server for anyone who opens the project:

```json
{"mcpServers": {"synfig_mcp": {"type": "stdio", "command": "uv", "args": ["run", "--quiet", "synfig-mcp"]}}}
```

- Project servers run code on your machine, so Claude Code asks before starting one:
  `claude mcp list` shows "Pending approval" until you approve it in an interactive session.
- In the model's tool list our tools are named `mcp__synfig_mcp__<tool>`.
- Headless runs can pin exactly what the model gets: `claude -p ... --mcp-config .mcp.json
  --strict-mcp-config --tools ""` gives a session with *only* our 14 tools and no built-in ones
  (no shell, no file edits). `scripts/run_first_shot.py` uses this for Step 2's done-when and
  saves the transcript to `mcp-first-shot.md`.

## Two servers, one film

From Step 3 there are two servers: `synfig_mcp` edits and renders shots, and `audio_mcp` makes
sound (voices, music, sound-effect search). A client like Claude Code or our director connects
to both, and the model sees one list of tools. The servers never call each other. They share
the film folder and pass **ids** through the model:

```
audio_mcp.speak(...)         → line_id "l007"   → synfig_mcp.apply_lipsync(line_id="l007")
audio_mcp.compose(...)       → cue_id "m01"     → synfig_mcp.set_music(cue_id="m01")
audio_mcp.find_sfx("a door") → sound_id "..."   → synfig_mcp.add_sound_effect(sound_id=...)
```

Splitting by *kind of work* keeps each server's tool list short and its failure modes
separate. Making sound can take a minute and needs models; editing a shot is instant and
engine-neutral. Each server's instructions mention the other, so the model knows where to get
an id.

## Testing without a model

The SDK's `Client` connects to a server object in-process, or launches it over stdio:

```python
async with Client(create_server(films_root)) as client:
    result = await client.call_tool("apply_motion", {...})
```

`tests/test_synfig_mcp.py` drives the real protocol layer this way: argument validation,
structured results and error shapes, with no LLM involved.
