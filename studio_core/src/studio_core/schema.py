"""Validate film project files: JSON Schema first, then the rules a schema cannot express.

    issues = validate("rig", data)          # [] when valid
    issues = validate_file(Path("films/x/characters/pip/rig.json"))

Schemas live in schemas/*.schema.json (draft 2020-12). Every issue has a JSON path and a message
written so that an LLM can fix its own output from it ("characters[0].actions[1].motion: 'wavee'
is not one of [...]"). Semantic checks only run once the schema passes, so they can trust types.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from studio_core.config import REPO_ROOT

SCHEMA_DIR = REPO_ROOT / "schemas"
SCHEMAS = (
    "rig",
    "shot",
    "shotlist",
    "film",
    "background",
    "voice",
    "line",
    "lipsync",
    "music",
    "sfx_library",
    "design",
    "plates",
)
FILE_KINDS = {
    "rig.json": "rig",
    "shot.json": "shot",
    "shotlist.json": "shotlist",
    "film.json": "film",
    "layers.json": "background",
    "voice.json": "voice",
    "manifest.json": "sfx_library",
    "candidates.json": "design",
    "plates.json": "plates",
}
# Files named by id (l001.json) are recognized by their folder instead.
FOLDER_KINDS = {"dialogue": "line", "lipsync": "lipsync", "music": "music"}


@dataclass(frozen=True)
class Issue:
    path: str  # e.g. "views.front.bones.forearm.attach.part"; "" = the document itself
    message: str

    def __str__(self) -> str:
        return f"{self.path or '(root)'}: {self.message}"


def _json_path(parts: Any) -> str:
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


@cache
def _registry() -> Registry:
    resources = []
    for name in SCHEMAS:
        schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry())


def schema_issues(name: str, data: Any) -> list[Issue]:
    errors = sorted(
        _validator(name).iter_errors(data), key=lambda e: list(map(str, e.absolute_path))
    )
    return [Issue(_json_path(e.absolute_path), e.message) for e in errors]


# --------------------------------------------------------------------------- rig


def _inside(point: list[float], size: list[int]) -> bool:
    return 0 <= point[0] <= size[0] and 0 <= point[1] <= size[1]


def _role(bones: dict[str, Any], name: str) -> str:
    """A bone's role, from its name (`arm_l` -> `arm`) when the rig does not say."""
    spec = bones[name]
    return spec.get("role", name[:-2] if name.endswith(("_l", "_r")) else name)


def _check_secondary(at: str, bones: dict[str, Any]) -> list[Issue]:
    """Ears and tails are optional, but where they exist: an ear hangs from the head and has a
    side; a tail segment hangs from the torso or from another tail segment."""
    issues: list[Issue] = []
    for name, spec in bones.items():
        role, parent = _role(bones, name), spec["parent"]
        if role == "ear":
            if spec.get("side") not in ("left", "right"):
                issues.append(Issue(f"{at}.bones.{name}.side", "an ear needs side left or right"))
            if parent in bones and _role(bones, parent) != "head":
                issues.append(
                    Issue(f"{at}.bones.{name}.parent", "an ear's parent must be the head")
                )
        elif role == "tail" and parent in bones and _role(bones, parent) not in ("torso", "tail"):
            issues.append(
                Issue(f"{at}.bones.{name}.parent", "a tail hangs from the torso or another tail")
            )
    tails = [n for n in bones if _role(bones, n) == "tail"]
    if len(tails) > 3:
        issues.append(Issue(f"{at}.bones", f"a tail has 1 to 3 segments, not {len(tails)}"))
    return issues


def check_rig(data: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    if data["default_view"] not in data["views"]:
        issues.append(Issue("default_view", f"view {data['default_view']!r} is not in views"))
    for view_name, view in data["views"].items():
        at = f"views.{view_name}"
        bones, parts = view["bones"], view["parts"]

        roots = [b for b, spec in bones.items() if spec["parent"] is None]
        if roots != [view["root"]]:
            issues.append(
                Issue(
                    f"{at}.root",
                    f"exactly one bone must have parent null and be "
                    f"the root {view['root']!r}; bones with parent null: {roots}",
                )
            )
        for name, spec in bones.items():
            parent = spec["parent"]
            if parent is not None and parent not in bones:
                issues.append(Issue(f"{at}.bones.{name}.parent", f"unknown bone {parent!r}"))
            if parent is not None and "attach" not in spec:
                issues.append(Issue(f"{at}.bones.{name}", "non-root bones need `attach`"))
            if "attach" in spec:
                part = spec["attach"]["part"]
                if part not in parts:
                    issues.append(Issue(f"{at}.bones.{name}.attach.part", f"unknown part {part!r}"))
                elif parts[part]["bone"] != parent:
                    issues.append(
                        Issue(
                            f"{at}.bones.{name}.attach.part",
                            f"{part!r} is carried by bone {parts[part]['bone']!r}, but a joint "
                            f"must attach to a part of the parent bone {parent!r}",
                        )
                    )
                elif not _inside(spec["attach"]["at_px"], parts[part]["size_px"]):
                    issues.append(
                        Issue(
                            f"{at}.bones.{name}.attach.at_px",
                            f"outside the {part!r} image {parts[part]['size_px']}",
                        )
                    )
        # Cycles: walk up from every bone; more steps than bones means a loop.
        for name in bones:
            seen, current = set(), name
            while current is not None and current in bones:
                if current in seen:
                    issues.append(Issue(f"{at}.bones.{name}.parent", "bone hierarchy has a cycle"))
                    break
                seen.add(current)
                current = bones[current]["parent"]

        issues += _check_secondary(at, bones)

        for name, part in parts.items():
            if part["bone"] not in bones:
                issues.append(Issue(f"{at}.parts.{name}.bone", f"unknown bone {part['bone']!r}"))
            if not _inside(part["pivot_px"], part["size_px"]):
                issues.append(Issue(f"{at}.parts.{name}.pivot_px", "outside the image"))
        missing = sorted(set(parts) - set(view["draw_order"]))
        extra = sorted(set(view["draw_order"]) - set(parts))
        if missing or extra:
            issues.append(
                Issue(
                    f"{at}.draw_order",
                    f"must list every part once; missing {missing}, unknown {extra}",
                )
            )

        issues += _check_limbs(at, view)

        face = view.get("face")
        if face:
            if face["part"] not in parts:
                issues.append(Issue(f"{at}.face.part", f"unknown part {face['part']!r}"))
            else:
                size = parts[face["part"]]["size_px"]
                anchors = {
                    "eyes.left_px": face["eyes"]["left_px"],
                    "eyes.right_px": face["eyes"]["right_px"],
                    "mouth.at_px": face["mouth"]["at_px"],
                }
                if "brows" in face:
                    anchors["brows.left_px"] = face["brows"]["left_px"]
                    anchors["brows.right_px"] = face["brows"]["right_px"]
                for key, point in anchors.items():
                    if not _inside(point, size):
                        issues.append(Issue(f"{at}.face.{key}", f"outside the face part {size}"))
    return issues


def _check_limbs(at: str, view: dict[str, Any]) -> list[Issue]:
    """`bendable_limbs`: two bones in a parent-child chain, the joint inside the image and where
    the rig's own joint is, no bone in two limbs, unique names."""
    issues: list[Issue] = []
    bones, parts = view["bones"], view["parts"]
    seen_names: set[str] = set()
    used: dict[str, str] = {}
    for i, limb in enumerate(view.get("bendable_limbs", [])):
        where = f"{at}.bendable_limbs[{i}]"
        if limb["name"] in seen_names:
            issues.append(Issue(f"{where}.name", f"limb {limb['name']!r} appears twice"))
        seen_names.add(limb["name"])
        upper, lower = limb["bones"]
        unknown = [b for b in (upper, lower) if b not in bones]
        for b in unknown:
            issues.append(Issue(f"{where}.bones", f"unknown bone {b!r}"))
        for b in (upper, lower):
            if b in used and b not in unknown:
                issues.append(Issue(f"{where}.bones", f"bone {b!r} is already in limb {used[b]!r}"))
            used[b] = limb["name"]
        if not unknown and bones[lower]["parent"] != upper:
            issues.append(
                Issue(
                    f"{where}.bones",
                    f"{lower!r} must be a child of {upper!r} (its parent is "
                    f"{bones[lower]['parent']!r})",
                )
            )
        for key in ("pivot_px", "joint_px"):
            if not _inside(limb[key], limb["size_px"]):
                issues.append(Issue(f"{where}.{key}", f"outside the limb image {limb['size_px']}"))
        attach = bones[lower].get("attach") if not unknown else None
        if attach and attach["part"] in parts:
            pivot = parts[attach["part"]]["pivot_px"]
            want = (attach["at_px"][0] - pivot[0], attach["at_px"][1] - pivot[1])
            got = (
                limb["joint_px"][0] - limb["pivot_px"][0],
                limb["joint_px"][1] - limb["pivot_px"][1],
            )
            if abs(want[0] - got[0]) > 3 or abs(want[1] - got[1]) > 3:
                issues.append(
                    Issue(
                        f"{where}.joint_px",
                        f"the joint is {got} px from the pivot in the limb image but the rig's "
                        f"{lower!r} joint is {want} px from the {upper!r} pivot",
                    )
                )
    return issues


# --------------------------------------------------------------------------- shots


def check_shot(shot: dict[str, Any], at: str = "") -> list[Issue]:
    issues: list[Issue] = []
    end = shot["duration_s"]
    pre = f"{at}." if at else ""

    def after_end(path: str, t: float, label: str) -> None:
        if t >= end:
            issues.append(Issue(f"{pre}{path}", f"{label} at {t}s is not inside the {end}s shot"))

    camera = shot.get("camera")
    if camera and camera.get("start_s", 0) + camera.get("duration_s", 0) > end + 1e-9:
        issues.append(Issue(f"{pre}camera", f"camera move runs past the end of the {end}s shot"))

    ids = [c["id"] for c in shot["characters"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        issues.append(Issue(f"{pre}characters", f"character {dup!r} appears twice"))
    for ci, char in enumerate(shot["characters"]):
        for ai, action in enumerate(char.get("actions", [])):
            path = f"characters[{ci}].actions[{ai}]"
            after_end(f"{path}.start_s", action["start_s"], action["motion"])
            if "duration_s" in action and action["start_s"] + action["duration_s"] > end + 1e-9:
                issues.append(
                    Issue(
                        f"{pre}{path}.duration_s",
                        f"{action['motion']} runs past the end of the {end}s shot",
                    )
                )
        last = 0.0
        for wi, key in enumerate(char.get("path", [])):
            path = f"{pre}characters[{ci}].path[{wi}].time_s"
            if key["time_s"] <= last + 1e-9:
                issues.append(
                    Issue(
                        path, f"waypoint at {key['time_s']}s is not after the one before ({last}s)"
                    )
                )
            elif key["time_s"] > end + 1e-9:
                issues.append(Issue(path, f"waypoint at {key['time_s']}s is past the {end}s shot"))
            last = max(last, key["time_s"])
        for ei, expr in enumerate(char.get("expressions", [])):
            after_end(f"characters[{ci}].expressions[{ei}].start_s", expr["start_s"], expr["expr"])
        for pi, pose in enumerate(char.get("poses", [])):
            after_end(f"characters[{ci}].poses[{pi}].time_s", pose["time_s"], "pose")
    for li, line in enumerate(shot.get("dialogue", [])):
        after_end(f"dialogue[{li}].start_s", line["start_s"], f"line {line['line_id']}")
        if line["character"] not in ids:
            issues.append(
                Issue(
                    f"{pre}dialogue[{li}].character",
                    f"{line['character']!r} speaks but is not in this shot ({ids})",
                )
            )
    for si, sfx in enumerate(shot.get("sfx", [])):
        after_end(f"sfx[{si}].start_s", sfx["start_s"], f"sound '{sfx['query']}'")
    return issues


def check_shotlist(data: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    ids = [s["id"] for s in data["shots"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        issues.append(Issue("shots", f"shot id {dup!r} is used twice"))
    for i, shot in enumerate(data["shots"]):
        issues += check_shot(shot, at=f"shots[{i}]")
    return issues


# --------------------------------------------------------------------------- audio (Step 3)

CUE_TOLERANCE_S = 0.05  # Rhubarb rounds times to 10 ms; allow a little slack against audio length


def _duplicates(values: list[Any]) -> list[Any]:
    return sorted({v for v in values if values.count(v) > 1}, key=str)


def check_voice(data: dict[str, Any]) -> list[Issue]:
    ids = [v["id"] for v in data.get("voices", [])]  # parler voices name a speaker instead
    issues = [Issue("voices", f"voice {d!r} is listed twice") for d in _duplicates(ids)]
    if data["engine"] == "parler":
        issues += [
            Issue(key, f"a parler voice doesn't use {key!r} (it names a speaker); remove it")
            for key in ("voices",)
            if key in data
        ]
    else:
        issues += [
            Issue(key, f"only parler voices use {key!r}; remove it")
            for key in ("speaker", "pitch")
            if key in data
        ]
    return issues


def check_line(data: dict[str, Any]) -> list[Issue]:
    issues = []
    if not data["text"].strip():
        issues.append(Issue("text", "the text is blank"))
    if data["voice"]["character"] != data["character"]:
        issues.append(
            Issue(
                "voice.character",
                f"the voice belongs to {data['voice']['character']!r}, "
                f"but the line is {data['character']!r}'s",
            )
        )
    return issues


def check_lipsync(data: dict[str, Any]) -> list[Issue]:
    """Cues start at 0, are in order with no gaps or overlaps, and end with the audio."""
    issues = []
    cues = data["mouthCues"]
    if cues[0]["start"] > 1e-6:
        issues.append(Issue("mouthCues[0].start", "the first cue must start at 0"))
    for i, cue in enumerate(cues):
        if cue["end"] <= cue["start"]:
            issues.append(Issue(f"mouthCues[{i}]", "end must be after start"))
        if i and abs(cue["start"] - cues[i - 1]["end"]) > 1e-6:
            gap = "a gap" if cue["start"] > cues[i - 1]["end"] else "an overlap"
            issues.append(Issue(f"mouthCues[{i}].start", f"{gap} after the previous cue"))
    duration = data["metadata"]["duration"]
    if abs(cues[-1]["end"] - duration) > CUE_TOLERANCE_S:
        issues.append(
            Issue(
                f"mouthCues[{len(cues) - 1}].end",
                f"the cues end at {cues[-1]['end']}s but the audio lasts {duration}s",
            )
        )
    return issues


def check_music(data: dict[str, Any]) -> list[Issue]:
    issues = [
        Issue("instruments", f"{d!r} is listed twice")
        for d in _duplicates(data.get("instruments", []))
    ]
    if not data["caption"].strip():
        issues.append(Issue("caption", "the caption is blank"))
    return issues


def check_sfx_library(data: dict[str, Any]) -> list[Issue]:
    sounds = data["sounds"]
    issues = []
    for key, what in (("id", "id"), ("file", "file"), ("sha256", "audio")):
        for dup in _duplicates([s[key] for s in sounds]):
            owners = [s["id"] for s in sounds if s[key] == dup]
            issues.append(Issue("sounds", f"the same {what} appears more than once: {owners}"))
    return issues


def check_design(data: dict[str, Any]) -> list[Issue]:
    ids = [c["id"] for c in data["candidates"]]
    issues = [
        Issue("candidates", f"candidate {d!r} appears more than once") for d in _duplicates(ids)
    ]
    for i, c in enumerate(data["candidates"]):
        if c["sheet"] != f"{c['id']}/sheet.png":
            issues.append(Issue(f"candidates[{i}].sheet", f"should be {c['id']}/sheet.png"))
        if c["ok"] == bool(c["problems"]):
            issues.append(
                Issue(f"candidates[{i}].ok", "ok must be true exactly when problems is empty")
            )
    if "chosen" in data and data["chosen"] not in ids:
        issues.append(Issue("chosen", f"unknown candidate {data['chosen']!r}; known: {ids}"))
    return issues


def check_plates(data: dict[str, Any]) -> list[Issue]:
    ids = [c["id"] for c in data["candidates"]]
    issues = [Issue("candidates", f"draft {d!r} appears more than once") for d in _duplicates(ids)]
    for i, c in enumerate(data["candidates"]):
        for key in ("draft", "plate"):
            if key in c and c[key] != f"{c['id']}/{key}.png":
                issues.append(Issue(f"candidates[{i}].{key}", f"should be {c['id']}/{key}.png"))
        if c["ok"] == bool(c["problems"]):
            issues.append(
                Issue(f"candidates[{i}].ok", "ok must be true exactly when problems is empty")
            )
    if "chosen" in data and data["chosen"] not in ids:
        issues.append(Issue("chosen", f"unknown draft {data['chosen']!r}; known: {ids}"))
    return issues


SEMANTIC = {
    "rig": check_rig,
    "shot": check_shot,
    "shotlist": check_shotlist,
    "voice": check_voice,
    "line": check_line,
    "lipsync": check_lipsync,
    "music": check_music,
    "sfx_library": check_sfx_library,
    "design": check_design,
    "plates": check_plates,
}


def validate(name: str, data: Any) -> list[Issue]:
    """Schema issues; if there are none, the semantic issues. [] means valid."""
    if name not in SCHEMAS:
        raise ValueError(f"unknown schema {name!r}; known: {SCHEMAS}")
    issues = schema_issues(name, data)
    if issues or name not in SEMANTIC:
        return issues
    return SEMANTIC[name](data)


def validate_file(path: Path, name: str | None = None) -> list[Issue]:
    name = name or FILE_KINDS.get(path.name) or FOLDER_KINDS.get(path.parent.name)
    if name is None:
        raise ValueError(f"can't tell the schema for {path.name}; pass name= (one of {SCHEMAS})")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [Issue("", f"not valid JSON: {exc}")]
    return validate(name, data)
