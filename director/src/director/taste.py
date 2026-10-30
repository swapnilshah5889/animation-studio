"""Taste rules for a shot plan: what a veteran animator would reject, written as code (D-065).

`plans.check_shotplan` checks *sense* (ids exist, seconds add up). This module checks *taste*:
staging, expression choice, emotional arc, camera intent, pointing. A 14B model plans legal but
dull films (one character per shot, "Look, Bo!" with Bo off screen, a grumpy face on a happy
jump), and the fix is not a longer prompt but a rule it is told about once, with the reason.

Everything here is engine-neutral: it reads the plan (`docs/craft/*.md` explains each rule to the
model; this file enforces it), and only knows our expression and camera names.
Every rule has an id, so a run can count violations per rule (scripts/measure_shotplans.py).
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Any

# What a character feels in a shot. The model names the feeling, code decides which faces fit it.
# Expression names are the puppet's (studio_core.face.EXPRESSIONS); a test keeps them in sync.
EMOTIONS: dict[str, tuple[str, ...]] = {
    "calm": ("neutral", "happy"),
    "curious": ("neutral", "surprised", "happy"),
    "joy": ("happy", "excited"),
    "excited": ("excited", "happy"),
    "wonder": ("surprised", "excited"),
    "proud": ("proud", "happy"),
    "shy": ("shy", "neutral"),
    "worried": ("worried",),
    "sad": ("sad", "worried"),
    "tired": ("sleepy", "neutral"),
    "effort": ("neutral", "proud", "determined"),
    "grumpy": ("grumpy", "neutral"),
}
# The face a plan written without an emotion (an old plan) most plausibly meant.
DEFAULT_EMOTION = {
    "neutral": "calm",
    "happy": "joy",
    "sad": "sad",
    "surprised": "wonder",
    "grumpy": "grumpy",
    "worried": "worried",
    "excited": "excited",
    "shy": "shy",
    "sleepy": "tired",
    "proud": "proud",
    "determined": "effort",
}
NEGATIVE = {"sad", "worried", "grumpy"}
BRIGHT = {"joy", "excited", "wonder", "proud"}  # a peak of the film
FEELING = BRIGHT | {"curious", "sad", "worried", "shy"}  # worth a push_in
OPENING = {"calm", "curious"}
ENDING = {"calm", "joy", "proud"}
RARE_FACES = ("determined", "grumpy")  # read as angry on our puppets: at most once per film
BIG_MOTIONS = {"jump", "clap", "laugh"}  # joy motions: need a bright emotion
QUIET_MOTIONS = {"nod", "head_tilt", "think", "shrug", "look_around"}  # what a listener may do
CALM_END_MOTIONS = QUIET_MOTIONS | {"wave", "bow", "talk_gesture"}
POINT_TARGETS = ("up", "down", "left_edge", "right_edge")
FRAMINGS = ("wide", "medium", "close")
NEGATIVE_SHARE = 0.3  # of the film's seconds

# Where a `where` lands (shots.X_BY_WHERE); the rule about sides only needs the order.
ORDER = {"left": 0, "center": 1, "right": 2}


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str  # phrased as an instruction to the model


def normalize(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan's shots with every taste field present (an older plan lacks them)."""
    out = []
    for sh in plan["shots"]:
        members = [
            {
                "emotion": DEFAULT_EMOTION.get(m["expression"], "calm"),
                "target": "",
                **m,
            }
            for m in sh["characters"]
        ]
        line = sh.get("line")
        out.append(
            {
                **sh,
                "framing": sh.get("framing") or ("close" if len(members) == 1 else "medium"),
                "characters": members,
                "line": {"to": "", **line} if line and line.get("text") else None,
            }
        )
    return out


def shot_emotion(sh: dict[str, Any]) -> str:
    """The feeling the shot is about: the speaker's, else the first character's."""
    if sh["line"]:
        for m in sh["characters"]:
            if m["id"] == sh["line"]["who"]:
                return m["emotion"]
    return sh["characters"][0]["emotion"]


def _names(story: dict[str, Any]) -> dict[str, str]:
    return {c["id"]: c["name"] for c in story["characters"]}


def check_taste(plan: dict[str, Any], story: dict[str, Any]) -> list[Violation]:
    shots = normalize(plan)
    scenes = {s["id"]: s for s in story["scenes"]}
    names = _names(story)
    total = sum(s["seconds"] for s in shots) or 1.0
    out: list[Violation] = []

    def add(rule: str, message: str) -> None:
        out.append(Violation(rule, message))

    # -- staging: establish, show who is talking to whom, show them together -------------------
    first_of: dict[str, dict[str, Any]] = {}
    prev_place = None
    for sh in shots:
        scene = scenes.get(sh["scene"])
        if scene is None:
            continue
        place = scene["place"]
        if sh["scene"] not in first_of:
            first_of[sh["scene"]] = sh
            if prev_place != place:  # the film's opening, or a new place
                opens = "the film" if prev_place is None else "a new place"
                everyone = {m["id"] for m in sh["characters"]} >= set(scene["characters"])
                if sh["framing"] != "wide" or not everyone:
                    add(
                        "establishing",
                        f"shot {sh['id']} opens {opens}: make it an establishing shot: "
                        f'framing "wide" with every character of scene {scene["id"]} in it '
                        "(it may carry the scene's first line when there is no time to spare) "
                        f"({', '.join(scene['characters'])}).",
                    )
        prev_place = place

    lone = {}
    for sh in shots:
        scene = scenes.get(sh["scene"])
        if scene is None or not sh["line"]:
            continue
        who = {m["id"] for m in sh["characters"]}
        ln = sh["line"]
        if ln["to"] and ln["to"] not in who:
            add(
                "addressee",
                f"shot {sh['id']}: {ln['who']} speaks to {ln['to']} but {ln['to']} is not in the "
                f"shot. Add {ln['to']} to the shot so the line has someone to hear it.",
            )
        else:
            words = set(re.findall(r"[\w']+", ln["text"].lower().replace("\u2019", "'")))
            for cid, name in names.items():
                if cid != ln["who"] and cid not in who and name.lower() in words:
                    add(
                        "addressee",
                        f"shot {sh['id']}: the line says {name} but {name} is not in the shot. "
                        f"Put {name} in the shot, next to {ln['who']}.",
                    )
        if len(scene["characters"]) >= 2 and len(who) == 1:
            if sh["framing"] == "close" and lone.get(scene["id"], 0) == 0:
                lone[scene["id"]] = 1  # one emotional close-up per scene is a choice
            else:
                add(
                    "lone_speaker",
                    f"shot {sh['id']}: {ln['who']} speaks alone in a scene of "
                    f"{len(scene['characters'])}. Show everyone who is in the scene (a two-shot); "
                    'a single-character "close" shot is allowed once per scene, for a big feeling.',
                )
    for sc in scenes.values():
        if len(sc["characters"]) < 2:
            continue
        mine = [s for s in shots if s["scene"] == sc["id"]]
        if mine and not any(
            {m["id"] for m in s["characters"]} >= set(sc["characters"]) for s in mine
        ):
            add(
                "two_shot",
                f"scene {sc['id']} never shows {' and '.join(sc['characters'])} together. At least "
                "one shot of the scene must have them all in it.",
            )

    # -- eyeline: characters keep their side of the frame within a scene -----------------------
    for a, b in itertools.pairwise(shots):
        if a["scene"] != b["scene"]:
            continue
        for m in a["characters"]:
            for n in a["characters"]:
                if m["id"] >= n["id"] or m.get("moves_to") or n.get("moves_to"):
                    continue
                ma = next((x for x in b["characters"] if x["id"] == m["id"]), None)
                na = next((x for x in b["characters"] if x["id"] == n["id"]), None)
                if not ma or not na or ma.get("moves_to") or na.get("moves_to"):
                    continue
                before = ORDER[m["where"]] - ORDER[n["where"]]
                after = ORDER[ma["where"]] - ORDER[na["where"]]
                if before * after < 0:
                    add(
                        "side_flip",
                        f"shots {a['id']} to {b['id']}: {m['id']} and {n['id']} swap sides of the "
                        "frame. Keep each character on the same side within a scene (eyeline).",
                    )

    # -- faces: the emotion decides the expression ---------------------------------------------
    for sh in shots:
        speaker = sh["line"]["who"] if sh["line"] else None
        for m in sh["characters"]:
            allowed = EMOTIONS.get(m["emotion"], ())
            if m["expression"] not in allowed:
                add(
                    "expression",
                    f"shot {sh['id']}: {m['id']} feels {m['emotion']} but the expression is "
                    f"{m['expression']!r}. For {m['emotion']} use one of {list(allowed)}.",
                )
            if m["does"] in BIG_MOTIONS and m["emotion"] not in BRIGHT:
                add(
                    "motion_mood",
                    f"shot {sh['id']}: {m['id']} does {m['does']} while feeling {m['emotion']}. "
                    f"{m['does']} is a joyful motion: feel one of {sorted(BRIGHT)} or pick a "
                    "quieter motion.",
                )
            if speaker and m["id"] != speaker and m["does"] not in QUIET_MOTIONS:
                add(
                    "listener_motion",
                    f"shot {sh['id']}: {m['id']} listens while {speaker} speaks, so give "
                    f"{m['id']} a quiet motion ({sorted(QUIET_MOTIONS)}), not {m['does']}.",
                )
            if m["does"] == "point":
                tgt = m["target"]
                who = {x["id"] for x in sh["characters"]} - {m["id"]}
                if not tgt:
                    add(
                        "point_target",
                        f"shot {sh['id']}: {m['id']} points but has no target. Set target to the "
                        f"character pointed at ({sorted(who) or 'none in the shot'}) or one of "
                        f"{list(POINT_TARGETS)}, or choose another motion.",
                    )
                elif tgt not in POINT_TARGETS and tgt not in who:
                    add(
                        "point_target",
                        f"shot {sh['id']}: {m['id']} points at {tgt!r}, who is not in the shot "
                        f"(or is itself). Target a character in the shot or one of "
                        f"{list(POINT_TARGETS)}.",
                    )
    for face in RARE_FACES:
        n = sum(1 for sh in shots if any(m["expression"] == face for m in sh["characters"]))
        if n > 1:
            add(
                "rare_face",
                f"{face!r} appears in {n} shots; on our puppets it reads as angry. Use it at most "
                "once in a film, for real effort or a real grumble.",
            )
    neg = sum(s["seconds"] for s in shots if shot_emotion(s) in NEGATIVE)
    if neg > NEGATIVE_SHARE * total:
        add(
            "negative_share",
            f"{round(100 * neg / total)}% of the film is sad, worried or grumpy. Children aged 4 "
            f"to 6 get at most {round(100 * NEGATIVE_SHARE)}%: make the other shots warmer.",
        )

    # -- arc: a start, a peak, a calm end ------------------------------------------------------
    emo = [shot_emotion(s) for s in shots]
    if len(shots) >= 3:
        want = 3 if len(shots) >= 4 else 2
        if len(set(emo)) < want:
            add(
                "arc",
                f"the film feels only {sorted(set(emo))}. Give it an arc: at least {want} "
                "different "
                "feelings, rising to a peak (joy, excited, wonder or proud) and ending calm.",
            )
        elif not any(e in BRIGHT for e in emo[1:]):
            add(
                "arc",
                "the film has no emotional peak: some shot after the first must feel joy, "
                "excited, wonder or proud.",
            )
    if len(shots) >= 2 and emo[0] not in OPENING:
        add("arc", f"open quietly: the first shot should feel calm or curious, not {emo[0]}.")
    if emo[-1] not in ENDING:
        add(
            "arc",
            f"end warm and settled: the last shot should feel calm, joy or proud, not {emo[-1]}.",
        )
    last = shots[-1]
    if (
        last["camera"] not in ("static", "pull_out")
        or last["seconds"] < 3
        or any(m["does"] not in CALM_END_MOTIONS for m in last["characters"])
    ):
        add(
            "ending",
            f"the last shot {last['id']} must be a calm hold: at least 3 s, camera static or "
            f"pull_out, and quiet motions ({sorted(CALM_END_MOTIONS)}).",
        )

    # -- camera and framing --------------------------------------------------------------------
    if len(shots) >= 3:
        if len({s["camera"] for s in shots}) < 2 or all(s["camera"] == "static" for s in shots):
            add(
                "camera_variety",
                "every shot has the same camera. Use at least two different camera moves "
                "(push_in toward a feeling, slow_pan_* to follow a walk, pull_out to end).",
            )
        if len({s["framing"] for s in shots}) < 2:
            add(
                "framing_variety",
                f"every shot is framed {shots[0]['framing']!r}. Mix wide (place), medium (two "
                "characters talking) and close (one big feeling).",
            )
    for sh in shots:
        cam = sh["camera"]
        walks = any(m.get("moves_to") for m in sh["characters"])
        if cam == "push_in" and (sh["framing"] == "wide" or shot_emotion(sh) not in FEELING):
            add(
                "camera_intent",
                f"shot {sh['id']}: push_in needs a feeling to push toward "
                f"(one of {sorted(FEELING)}) "
                "and a medium or close framing, not wide.",
            )
        if cam.startswith("slow_pan") and sh["line"] and not walks:
            add(
                "camera_intent",
                f"shot {sh['id']}: a pan during a line distracts. Pan only to follow a walk "
                "(moves_to) or over a shot with no line.",
            )
    return out
