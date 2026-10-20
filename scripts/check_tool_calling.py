"""Does a local model emit valid tool calls through Ollama?

The director (Step 5) is an agent loop: the model asks for a tool, our code runs it, the result goes
back, and the model continues. This script tests that loop with one dummy tool, `get_weather`, in
these cases per trial:

  first    "What's the weather in Lisbon?"  -> must call get_weather(city="Lisbon"), valid args
  call     if the first call is invalid, we return the validation error as the tool result (as
           the real director will) and accept one corrected call
  answer   feed the tool result back        -> must answer in text, using the result (18 °C)
  no_call  "What is 7 times 6?"             -> must answer directly, without calling the tool

Run from the repo root:

    uv run scripts/check_tool_calling.py                      # director models from config
    uv run scripts/check_tool_calling.py qwen3:14b --trials 5
    uv run scripts/check_tool_calling.py --out docs/results/tool_calling.json

Each model is unloaded afterwards (keep_alive=0), so the script is safe to run between other work.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from studio_core.config import load_config
from studio_core.ollama import Ollama

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'Paris'"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    },
}
SYSTEM = "You are a helpful assistant. Use a tool only when it is needed to answer."
TOOL_RESULT = {"city": "Lisbon", "temperature": 18, "unit": "celsius", "sky": "sunny"}


@dataclass
class Trial:
    first: bool = False  # valid on the first try
    call: bool = False  # valid on the first try or after one validation-error retry
    answer: bool = False
    no_call: bool = False
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def validate_call(message: dict[str, Any]) -> tuple[bool, str]:
    """True if the message holds exactly one well-formed get_weather call for Lisbon."""
    calls = message.get("tool_calls") or []
    if len(calls) != 1:
        return False, f"expected 1 tool call, got {len(calls)}: {message.get('content', '')[:80]!r}"
    fn = calls[0].get("function", {})
    args = fn.get("arguments")
    if isinstance(args, str):  # some models return a JSON string instead of an object
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return False, f"arguments are not JSON: {args!r}"
    if fn.get("name") != "get_weather":
        return False, f"wrong tool name: {fn.get('name')!r}"
    if not isinstance(args, dict) or "lisbon" not in str(args.get("city", "")).lower():
        return False, f"bad arguments: {args!r}"
    if "unit" in args and args["unit"] not in ("celsius", "fahrenheit"):
        return False, f"unit outside enum: {args['unit']!r}"
    return True, f"get_weather({json.dumps(args)})"


def run_trial(client: Ollama, model: str, think: bool | str | None) -> Trial:
    trial = Trial()
    start = time.perf_counter()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "What's the weather like in Lisbon right now?"},
    ]
    resp = client.chat(model, messages, tools=[WEATHER_TOOL], think=think)
    message = resp["message"]
    trial.first, note = validate_call(message)
    trial.call = trial.first
    trial.notes.append(f"call: {note}")

    if not trial.first and message.get("tool_calls"):
        # What the director will do: reject the call, explain why, let the model try again.
        messages.append(message)
        error = {"error": f"invalid call: {note}. Arguments must match the tool's JSON Schema."}
        messages.append({"role": "tool", "tool_name": "get_weather", "content": json.dumps(error)})
        resp = client.chat(model, messages, tools=[WEATHER_TOOL], think=think)
        message = resp["message"]
        trial.call, note = validate_call(message)
        trial.notes.append(f"retry: {note}")

    if trial.call:
        messages.append(message)  # the assistant turn, including its tool_calls
        messages.append(
            {"role": "tool", "tool_name": "get_weather", "content": json.dumps(TOOL_RESULT)}
        )
        resp = client.chat(model, messages, tools=[WEATHER_TOOL], think=think)
        text = resp["message"].get("content", "")
        trial.answer = "18" in text and not resp["message"].get("tool_calls")
        trial.notes.append(f"answer: {text.strip()[:100]!r}")

    resp = client.chat(
        model,
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "What is 7 times 6?"}],
        tools=[WEATHER_TOOL],
        think=think,
    )
    text = resp["message"].get("content", "")
    trial.no_call = not resp["message"].get("tool_calls") and "42" in text
    trial.notes.append(f"no_call: {text.strip()[:60]!r}")

    trial.seconds = time.perf_counter() - start
    return trial


def parse_think(value: str | None) -> bool | str | None:
    if value is None:
        return None
    return {"true": True, "false": False}.get(value.lower(), value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("models", nargs="*", help="default: [ollama] director_models in config")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument(
        "--think",
        default=None,
        help="true/false, or low/medium/high for gpt-oss (default: model default)",
    )
    parser.add_argument("--out", type=Path, help="write full results as JSON")
    parser.add_argument("--md", type=Path, help="append the results table to this Markdown file")
    args = parser.parse_args()

    cfg = load_config()
    client = Ollama(cfg.get("services", "ollama_url"))
    models = args.models or cfg.get("ollama", "director_models")
    think = parse_think(args.think)

    report: dict[str, Any] = {}
    lines = [
        "| Model | Valid call, 1st try | Valid after 1 retry | Uses result | No needless call "
        "| Avg s/trial |",
        "|---|---|---|---|---|---|",
    ]
    print("\n".join(lines))
    for model in models:
        trials = [run_trial(client, model, think) for _ in range(args.trials)]
        client.unload(model)
        n = len(trials)
        keys = ("first", "call", "answer", "no_call")
        row = {k: sum(getattr(t, k) for t in trials) for k in keys}
        avg = sum(t.seconds for t in trials) / n
        counts = " | ".join(f"{row[k]}/{n}" for k in keys)
        lines.append(f"| {model} | {counts} | {avg:.1f} |")
        print(lines[-1])
        report[model] = {"think": think, "trials": [asdict(t) for t in trials]}

    for model, data in report.items():
        print(f"\n{model}")
        for i, t in enumerate(data["trials"], 1):
            print(f"  trial {i}: " + " | ".join(t["notes"]))

    if args.md:
        stamp = time.strftime("%Y-%m-%d %H:%M")
        with args.md.open("a") as fh:
            fh.write(
                f"\n### Tool calling (scripts/check_tool_calling.py)\n\n_Measured {stamp}, "
                f"{args.trials} trials per model, think={think}._\n\n" + "\n".join(lines) + "\n"
            )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2))

    passed = all(all(t["call"] for t in d["trials"]) for d in report.values())
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
