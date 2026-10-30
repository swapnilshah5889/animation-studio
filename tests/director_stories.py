"""Five fixed 15 s story plans (the story stage's output) to measure shot-planning taste on.

Offline fixtures: scripts/measure_shotplans.py plans their shots with the real model and counts
rule violations (director/taste.py); tests use them with a fake model. Characters are the
studio's cast; places are painted backgrounds or plausible ones (planning never renders).
"""

from __future__ import annotations

from typing import Any

CAST = {
    "kit": ("Kit", "A small curious fox cub with a red scarf.", "child_high"),
    "bo": ("Bo", "A cheerful little brown bear cub in blue dungarees.", "child_low"),
    "pim": ("Pim", "A tiny shy field mouse with big round ears.", "child_high"),
    "mia": ("Mia", "A kind girl of six in a yellow raincoat.", "child_high"),
    "bolt": ("Bolt", "A small friendly round robot with a blinking lamp.", "child_low"),
}
PLACES = {
    "orchard": ("A sunny orchard with apple trees and flowers.", "day"),
    "pond": ("A quiet pond with lily pads and tall reeds.", "morning"),
    "meadow": ("A wide green meadow with a hill and wild flowers.", "afternoon"),
    "porch": ("A cosy wooden porch at sunset with a garden below.", "sunset"),
}


def story(title: str, logline: str, chars: list[str], scenes: list[dict[str, Any]]) -> dict:
    used = {p for s in scenes for p in [s["place"]]}
    return {
        "title": title,
        "logline": logline,
        "characters": [
            {
                "id": c,
                "name": CAST[c][0],
                "description": CAST[c][1],
                "voice_hint": CAST[c][2],
                "role": "friend",
            }
            for c in chars
        ],
        "places": [
            {"id": p, "description": PLACES[p][0], "time_of_day": PLACES[p][1]}
            for p in PLACES
            if p in used
        ],
        "scenes": scenes,
    }


def scene(i, place, summary, secs, chars, lines, mood, energy):
    return {
        "id": f"s{i:02d}",
        "place": place,
        "summary": summary,
        "seconds": secs,
        "characters": chars,
        "lines": [{"who": w, "text": t} for w, t in lines],
        "mood": mood,
        "energy": energy,
    }


STORIES: dict[str, dict[str, Any]] = {
    "balloon": story(
        "The Lost Balloon",
        "Kit and Bo find a red balloon in the orchard and help it back to the sky.",
        ["kit", "bo"],
        [
            scene(
                1,
                "orchard",
                "Kit and Bo find a red balloon tangled in a tree.",
                7,
                ["kit", "bo"],
                [("kit", "Look, Bo! A red balloon!"), ("bo", "Let's send it back to the sky!")],
                "curious",
                0.3,
            ),
            scene(
                2,
                "orchard",
                "They free the balloon and watch it float up.",
                8,
                ["kit", "bo"],
                [("bo", "Up, up, up!"), ("kit", "Goodbye, little friend!")],
                "triumphant",
                0.4,
            ),
        ],
    ),
    "pond": story(
        "Pim and the Pond",
        "Shy Pim is afraid to cross the stepping stones until Mia cheers her on.",
        ["pim", "mia"],
        [
            scene(
                1,
                "pond",
                "Pim and Mia reach the pond. Pim stares at the stepping stones.",
                6,
                ["pim", "mia"],
                [("mia", "Pim, you can do it!"), ("pim", "The stones look wobbly.")],
                "calm",
                0.2,
            ),
            scene(
                2,
                "pond",
                "Pim hops across, one stone at a time, and reaches the other side.",
                9,
                ["pim", "mia"],
                [("pim", "I did it, Mia!"), ("mia", "I knew you could!")],
                "playful",
                0.5,
            ),
        ],
    ),
    "robot": story(
        "Bolt Learns to Dance",
        "Bolt the robot is stiff and shy about dancing; Kit teaches a wiggle.",
        ["bolt", "kit"],
        [
            scene(
                1,
                "meadow",
                "Kit dances in the meadow. Bolt watches, stiff and unsure.",
                7,
                ["bolt", "kit"],
                [("kit", "Wiggle your arms, Bolt!"), ("bolt", "I only know how to beep.")],
                "playful",
                0.4,
            ),
            scene(
                2,
                "meadow",
                "Bolt tries a wiggle, then dances happily with Kit.",
                8,
                ["bolt", "kit"],
                [("bolt", "Beep boop, I am dancing!")],
                "triumphant",
                0.7,
            ),
        ],
    ),
    "apples": story(
        "Apples for Bo",
        "Bo cannot reach the apples. Kit and Mia find a clever way and share the harvest.",
        ["bo", "kit", "mia"],
        [
            scene(
                1,
                "orchard",
                "Bo jumps but cannot reach the high apples.",
                5,
                ["bo", "kit"],
                [("bo", "Just a little higher!"), ("kit", "Let me think, Bo.")],
                "curious",
                0.3,
            ),
            scene(
                2,
                "orchard",
                "Mia brings a ladder and Kit holds it steady while Bo climbs.",
                6,
                ["bo", "kit", "mia"],
                [("mia", "Here is a ladder!")],
                "playful",
                0.5,
            ),
            scene(
                3,
                "orchard",
                "The three friends share the apples.",
                4,
                ["bo", "kit", "mia"],
                [("bo", "Thank you, friends!")],
                "calm",
                0.2,
            ),
        ],
    ),
    "sunset": story(
        "Goodnight, Sun",
        "Mia and Pim watch the sun set from the porch and say goodnight to the day.",
        ["mia", "pim"],
        [
            scene(
                1,
                "porch",
                "Mia and Pim sit on the porch as the sky turns orange.",
                7,
                ["mia", "pim"],
                [("pim", "Look how orange the sky is!")],
                "calm",
                0.2,
            ),
            scene(
                2,
                "porch",
                "The sun dips low. They wave goodnight to it and yawn.",
                8,
                ["mia", "pim"],
                [("mia", "Goodnight, sun."), ("pim", "See you tomorrow.")],
                "calm",
                0.1,
            ),
        ],
    ),
}
