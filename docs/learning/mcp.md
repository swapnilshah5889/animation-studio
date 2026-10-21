# MCP: how the director gets its hands

The **Model Context Protocol** is how an LLM application (the *client*: Claude Code today, our
director in Step 5) uses capabilities that live in another program (the *server*: `synfig_mcp`).
The model never imports our Python. It sees a list of tools, each with a name, a description and a
JSON Schema for its arguments, and asks the client to call one. The client sends a JSON-RPC message
to the server, the server runs the function, and the result comes back into the conversation.

First version, written with task 2.7. Task 2.9 extends it with what the Inspector and Claude Code
showed.

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

## Testing without a model

The SDK's `Client` connects to a server object in-process, or launches it over stdio:

```python
async with Client(create_server(films_root)) as client:
    result = await client.call_tool("apply_motion", {...})
```

`tests/test_synfig_mcp.py` drives the real protocol layer this way: argument validation,
structured results and error shapes, with no LLM involved.
