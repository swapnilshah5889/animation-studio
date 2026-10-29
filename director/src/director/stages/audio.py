"""Stage 4, audio: cast voices, record every line, compose one music cue per scene. Code-driven.

Writes two small files the shots stage needs: director/lines.json (which line_id is which line, and
how long it is) and director/music.json (scene -> cue id).
"""

from __future__ import annotations

import json
from typing import Any

from director.checks import lines_of, read_json, story_of
from director.context import StageCtx, StageFailed
from director.plans import norm

# voice_hint -> Kokoro voices to try, in order (the first not used by another character wins).
VOICES: dict[str, list[dict[str, Any]]] = {
    "child_high": [
        {"id": "af_heart", "pitch_semitones": 2.0, "speed": 1.08},
        {"id": "af_nicole", "pitch_semitones": 2.0, "speed": 1.05},
    ],
    "child_low": [
        {"id": "am_puck", "pitch_semitones": 2.5, "speed": 1.0},
        {"id": "am_michael", "pitch_semitones": 3.0, "speed": 1.0},
    ],
    "warm_adult": [
        {"id": "af_bella", "pitch_semitones": 0.0, "speed": 1.0},
        {"id": "af_sky", "pitch_semitones": 0.0, "speed": 1.0},
    ],
    "gentle_adult": [
        {"id": "bf_emma", "pitch_semitones": 0.0, "speed": 0.98},
        {"id": "bm_george", "pitch_semitones": 0.0, "speed": 0.98},
    ],
}


def pick_voice(hint: str, taken: set[str], installed: list[str]) -> dict[str, Any]:
    options = [v for v in VOICES.get(hint, VOICES["child_high"]) if v["id"] in installed] or [
        {"id": installed[0]}
    ]
    return next((v for v in options if v["id"] not in taken), options[0])


async def run(ctx: StageCtx) -> None:
    story = story_of(ctx.film)
    assert story is not None
    state = await ctx.tool("describe_audio")
    installed = state["installed_voices"].get("kokoro", [])
    if not installed:
        raise StageFailed("no Kokoro voices installed (describe_audio)")
    voiced = {c["id"]: c["voice"] for c in state["characters"] if c.get("voice")}
    taken = {v["voices"][0]["id"] for v in voiced.values()}
    speaking = {ln["who"] for s in story["scenes"] for ln in s["lines"]}
    for c in story["characters"]:
        if c["id"] in speaking and c["id"] not in voiced:
            v = pick_voice(c["voice_hint"], taken, installed)
            taken.add(v["id"])
            await ctx.tool(
                "set_voice",
                character_id=c["id"],
                voices=[{"id": v["id"]}],
                speed=v.get("speed", 1.0),
                pitch_semitones=v.get("pitch_semitones", 0.0),
                notes=f"Chosen by the director from hint {c['voice_hint']!r}; recast at casting.",
            )

    recorded = lines_of(ctx.film)
    have = {(x["scene"], x["who"], norm(x["text"])) for x in recorded}
    for s in story["scenes"]:
        for ln in s["lines"]:
            if (s["id"], ln["who"], norm(ln["text"])) in have:
                continue
            made = (await ctx.tool("speak", character_id=ln["who"], lines=[{"text": ln["text"]}]))[
                "lines"
            ][0]
            recorded.append(
                {
                    "scene": s["id"],
                    "who": ln["who"],
                    "text": ln["text"],
                    "line_id": made["line_id"],
                    "duration_s": made["duration_s"],
                }
            )
            (ctx.film / "director").mkdir(exist_ok=True)
            (ctx.film / "director" / "lines.json").write_text(json.dumps(recorded, indent=2) + "\n")
    ctx.save()

    # Music last: it needs the GPU to itself (compose refuses while ComfyUI is up).
    music: dict[str, str] = read_json(ctx.film / "director" / "music.json") or {}
    for i, s in enumerate(story["scenes"], 1):
        cue = f"m{i:02d}"
        if music.get(s["id"]) == cue and list((ctx.film / "audio" / "music").glob(f"{cue}.*")):
            continue
        await ctx.tool(
            "compose",
            cue_id=cue,
            mood=s["mood"],
            duration_s=float(s["seconds"]),
            energy=s["energy"],
        )
        music[s["id"]] = cue
        (ctx.film / "director" / "music.json").write_text(json.dumps(music, indent=2) + "\n")
