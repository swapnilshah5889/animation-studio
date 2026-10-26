# Tool calling with a local LLM (Ollama)

The director (Step 5) is an **agent loop**: the model reads the situation, asks for a tool, our
code runs the tool, the result goes back to the model, and it continues until the stage is done.
"Tool calling" (also called function calling) is the part where the model asks for a tool in a
structured, machine-readable way instead of prose. Step 0 checks that both director candidates
can do it reliably (`scripts/check_tool_calling.py`).

## What goes over the wire

We send `POST /api/chat` with the conversation and a list of tools, each described by a JSON
Schema:

```json
{
  "model": "qwen3:14b",
  "messages": [{"role": "user", "content": "What's the weather like in Lisbon right now?"}],
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "Get the current weather for a city.",
      "parameters": {"type": "object",
                     "properties": {"city": {"type": "string"},
                                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}},
                     "required": ["city"]}
    }
  }],
  "stream": false
}
```

If the model decides to use a tool, the reply's message has `tool_calls` instead of (or as well
as) text:

```json
{"role": "assistant", "content": "",
 "tool_calls": [{"function": {"name": "get_weather", "arguments": {"city": "Lisbon"}}}]}
```

Our code runs the tool, then appends **both** the assistant message (with its `tool_calls`) and a
`{"role": "tool", "tool_name": "get_weather", "content": "<result JSON>"}` message, and calls the
model again. The model now answers in text using the result. That second call is what turns a
one-shot prompt into a loop.

## How it works under the hood

The model never "calls" anything. Each model family was fine-tuned to emit a special text format
for tool requests (Qwen uses `<tool_call>{...}</tool_call>` tags, gpt-oss uses its "harmony"
channels). Ollama's per-model **chat template** renders our `tools` list into the prompt in the
format that model was trained on, then parses the model's special output back into the neutral
`tool_calls` JSON. That is why tool calling quality depends on the model *and* its template.

## What can go wrong (and what the check tests)

| Failure | Example | How we catch it |
|---|---|---|
| No call when one is needed | Model guesses "It's sunny in Lisbon" | `call` case: exactly one `get_weather` call required |
| Malformed arguments | Arguments as an unparseable string, wrong key, value outside the enum | `validate_call` parses and checks name, `city`, `unit` |
| Ignores the result | Answers without the tool's 18 °C | `answer` case: the final text must contain "18" |
| Calls tools needlessly | Calls `get_weather` for "What is 7 times 6?" | `no_call` case: must answer 42 with no call |

Rules for the real director, learned here:

- **Validate every call in code** before running it (JSON Schema, then our own checks). Never trust
  the model's arguments; "rules live in code" (AGENTS.md).
- **Small, sharp tools** with precise descriptions beat one giant tool. The model reads the
  descriptions; they are part of the prompt.
- **Thinking models** (qwen3, gpt-oss) reason before calling. That helps planning but costs tokens
  and time. qwen3 can switch it off (`think: false`); gpt-oss only lowers it (`think: "low"`).
- **Unload after use** (`keep_alive: 0`) so the next stage gets the memory (Mac rule).

## Results on this machine

See the "Tool calling" section in [`../benchmarks.md`](../benchmarks.md) and the decision on the
director model in [`../DECISIONS.md`](../DECISIONS.md).
