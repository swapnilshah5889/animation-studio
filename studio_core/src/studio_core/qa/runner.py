"""The director's eyes: check a rendered frame against its shot spec, and check children's safety.

Two layers, kept apart in every result:

- **code checks are facts** (`frame_checks.py`, the word blocklist): always run, no model;
- **the vision model is advisory** (`qwen3-vl:8b-instruct`, D-018): temperature 0, thinking off,
  a JSON schema for the answer, one call per frame or text, unloaded afterwards.

Mac memory rule (AGENTS.md): one big model at a time. `make_room` unloads any other Ollama model
and refuses while ComfyUI is busy (an idle ComfyUI is asked to free its memory first).
"""

from __future__ import annotations

import base64
import contextlib
import json
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from studio_core import safety
from studio_core.comfy import Comfy
from studio_core.config import StudioConfig, load_config
from studio_core.ollama import Ollama
from studio_core.preview.sweep import PROBE, scratch_film
from studio_core.qa import frame_checks, rubric
from studio_core.qa.frame_checks import Finding
from studio_core.shot import ShotError, load_shot, render_preview

Say = Callable[[str], None]
PREVIEW_SCALE = 0.5  # 960x540, the size the sweep thresholds are tuned for
QUIET_MOTIONS = {"blink", "idle_breathe"}  # always on; they say nothing about the key moments


class QAError(RuntimeError):
    """A check could not run; the message says what to fix."""


# --------------------------------------------------------------------------- the model client


class VisionClient(Protocol):
    model: str

    def ask(self, prompt: str, schema: dict[str, Any], image_png: bytes | None) -> str:
        """One call; returns the model's raw JSON text."""

    def unload(self) -> None: ...


class OllamaVision:
    """qwen3-vl through studio_core.ollama: temperature 0, think off, JSON schema, 1 call."""

    def __init__(self, cfg: StudioConfig | None = None) -> None:
        self.cfg = cfg or load_config()
        self.model: str = self.cfg.get("ollama", "vision_model")
        self.client = Ollama(self.cfg.get("services", "ollama_url"))
        self.last_seconds = 0.0
        self.last_load_s = 0.0
        self.memory_gb: float | None = None

    def ask(self, prompt: str, schema: dict[str, Any], image_png: bytes | None) -> str:
        images = [base64.b64encode(image_png).decode()] if image_png else None
        t0 = time.perf_counter()
        try:
            resp = self.client.generate(
                self.model,
                prompt,
                images=images,
                think=False,
                options={"temperature": 0},
                keep_alive="5m",
                format=schema,
            )
        except OSError as e:
            raise QAError(
                f"cannot reach Ollama at {self.client.base_url} ({e}); start it with "
                "`ollama serve` and make sure the model is pulled"
            ) from e
        self.last_seconds = time.perf_counter() - t0
        self.last_load_s = resp.get("load_duration", 0) / 1e9
        try:
            for m in self.client.loaded():
                if m["name"] == self.model:
                    self.memory_gb = round(m["size"] / 1e9, 1)
        except OSError:
            pass
        return resp.get("response", "")

    def unload(self) -> None:
        with contextlib.suppress(OSError, TimeoutError):
            self.client.unload(self.model)


def make_room(cfg: StudioConfig, model: str) -> list[str]:
    """Free the GPU for the vision model. Returns what was freed (for the result's notes)."""
    freed: list[str] = []
    comfy = Comfy(cfg.get("services", "comfyui_url"), timeout=3)
    try:
        comfy.system_stats()
        up = True
    except OSError:
        up = False
    if up:
        try:
            q = json.loads(comfy._get("/queue"))
        except (OSError, ValueError):
            q = {}
        if q.get("queue_running") or q.get("queue_pending"):
            raise QAError(
                "ComfyUI is busy with an art job; wait for it to finish (one model at once)"
            )
        comfy.free_memory()
        freed.append("ComfyUI models")
    client = Ollama(cfg.get("services", "ollama_url"))
    try:
        for m in client.loaded():
            if m["name"] != model:
                client.unload(m["name"])
                freed.append(m["name"])
    except OSError:
        pass  # Ollama not running: ask() reports it
    return freed


# --------------------------------------------------------------------------- results


@dataclass
class Match:
    what: str  # "pip present", "pip expression", "background"
    ok: bool
    reason: str


@dataclass
class FrameReport:
    shot_id: str
    time_s: float
    frame_path: str
    code_ok: bool
    code_findings: list[Finding]
    matches: list[Match]
    problems: list[str]
    description: str
    model_ok: bool
    ok: bool
    model_seconds: float  # the whole call, including loading the model when it was not loaded
    notes: list[str] = field(default_factory=list)
    model_load_seconds: float = 0.0
    model_memory_gb: float | None = None


@dataclass
class SafetyReport:
    ok: bool
    needs_human: bool
    categories: list[str]
    reasons: list[str]
    blocked_words: list[str]
    model_seconds: float
    subject: str = ""


# --------------------------------------------------------------------------- frames


def _png(path: Path) -> bytes:
    return path.read_bytes()


def render_probes(
    film_dir: Path, shot: dict[str, Any], t: float, work: Path, cfg: StudioConfig
) -> dict[str, np.ndarray]:
    """Per character: the shot at time t with only that character, on the magenta backdrop."""
    out: dict[str, np.ndarray] = {}
    for ch in shot["characters"]:
        cid = ch["id"]
        folder = film_dir / "characters" / cid
        if not folder.is_dir():
            raise QAError(f"character {cid!r} has no folder at {folder}")
        scratch = scratch_film(work / cid, {cid: folder})
        spec = {
            "schema_version": shot.get("schema_version", 1),
            "id": "s01_sh01",
            "duration_s": shot["duration_s"],
            "background": PROBE,
            "characters": [ch],
            "camera": shot.get("camera", {"move": "static", "zoom": 1.0}),
        }
        sdir = scratch.root / "shots" / "s01_sh01"
        sdir.mkdir(parents=True)
        (sdir / "shot.json").write_text(json.dumps(spec))
        png, _, _ = render_preview(scratch.root, "s01_sh01", t, scale=PREVIEW_SCALE, cfg=cfg)
        out[cid] = np.asarray(Image.open(png).convert("RGB"))
    return out


def render_frame(film_dir: Path, shot_id: str, t: float, cfg: StudioConfig) -> Path:
    """The frame as the film shows it, saved under shots/<id>/qa/ (preview.png is refreshed by
    the shared preview path; the copy is kept so later calls don't overwrite it)."""
    png, _, _ = render_preview(film_dir, shot_id, t, scale=PREVIEW_SCALE, cfg=cfg)
    keep = png.parent / "qa" / f"frame_{t:06.2f}.png"
    keep.parent.mkdir(exist_ok=True)
    shutil.copy(png, keep)
    return keep


def code_checks(film_dir: Path, shot: dict[str, Any], frame: Path, t: float, cfg: StudioConfig):
    findings = frame_checks.black_frame(np.asarray(Image.open(frame).convert("RGB")))
    with tempfile.TemporaryDirectory(prefix="qa_probe_") as tmp:
        for cid, rgb in render_probes(film_dir, shot, t, Path(tmp), cfg).items():
            findings += frame_checks.probe_findings(cid, rgb)
    return findings


def check_frame(
    film_dir: Path,
    shot_id: str,
    time_s: float,
    client: VisionClient,
    *,
    cfg: StudioConfig | None = None,
    say: Say = lambda _: None,
    keep_model: bool = False,
    room_made: bool = False,
) -> FrameReport:
    """Render the frame, run the code checks, ask the model once, combine."""
    cfg = cfg or load_config()
    try:
        shot = load_shot(film_dir, shot_id)
    except (ShotError, FileNotFoundError) as e:
        raise QAError(str(e)) from None
    notes: list[str] = []
    try:
        say(f"rendering {shot_id} at {time_s:.1f}s")
        frame = render_frame(film_dir, shot_id, time_s, cfg)
        say("code checks (holes, cropping, missing characters)")
        findings = code_checks(film_dir, shot, frame, time_s, cfg)
    except ShotError as e:
        raise QAError(str(e)) from None
    if not room_made:
        notes += [f"freed {n}" for n in make_room(cfg, client.model)]
    facts = rubric.shot_facts(shot, time_s)
    ids = [c["id"] for c in facts["characters"]]
    say(f"asking {client.model}")
    t0 = time.perf_counter()
    try:
        raw = client.ask(rubric.frame_prompt(facts, time_s), rubric.frame_schema(ids), _png(frame))
    finally:
        if not keep_model:
            client.unload()
    seconds = round(time.perf_counter() - t0, 1)
    try:
        answer = rubric.parse_frame(raw, ids)
    except rubric.ModelAnswerError as e:
        raise QAError(f"{e}; run the check again") from None
    matches = []
    for c in answer["characters"]:
        matches.append(Match(f"{c['id']} present", c["present"], c["reason"]))
        matches.append(
            Match(f"{c['id']} expression ({_expr(facts, c['id'])})", c["expression_plausible"], "")
        )
    matches.append(Match("background", answer["background_present"], answer["background_reason"]))
    model_ok = all(m.ok for m in matches) and not answer["problems"]
    return FrameReport(
        shot_id=shot_id,
        time_s=time_s,
        frame_path=str(frame),
        code_ok=not findings,
        code_findings=findings,
        matches=matches,
        problems=answer["problems"],
        description=answer["description"],
        model_ok=model_ok,
        ok=not findings and model_ok,
        model_seconds=seconds,
        notes=notes,
        model_load_seconds=round(getattr(client, "last_load_s", 0.0), 1),
        model_memory_gb=getattr(client, "memory_gb", None),
    )


def _expr(facts: dict[str, Any], cid: str) -> str:
    return next(c["expression"] for c in facts["characters"] if c["id"] == cid)


# --------------------------------------------------------------------------- safety


def check_text_safety(
    text: str, client: VisionClient, *, image: Path | None = None, subject: str = ""
) -> SafetyReport:
    """Word blocklist (fact), then the rubric judgement (advisory). Conservative: any doubt
    gives ok False with needs_human True."""
    words = safety.blocked_words(text) if text else []
    t0 = time.perf_counter()
    raw = client.ask(
        rubric.safety_prompt(text=text or None, has_image=image is not None),
        rubric.SAFETY_SCHEMA,
        _png(image) if image else None,
    )
    seconds = round(time.perf_counter() - t0, 1)
    try:
        cats, reasons, unsure = rubric.parse_safety(raw)
    except rubric.ModelAnswerError as e:
        return SafetyReport(
            False, True, [], [f"model answer unusable: {e}"], words, seconds, subject
        )
    if words:
        reasons = [f"blocklisted words: {', '.join(words)}", *reasons]
    return SafetyReport(
        ok=not words and not cats and not unsure,
        needs_human=unsure,
        categories=cats,
        reasons=reasons,
        blocked_words=words,
        model_seconds=seconds,
        subject=subject,
    )


# --------------------------------------------------------------------------- the whole film


def key_times(shot: dict[str, Any], limit: int = 3) -> list[float]:
    """Up to `limit` times worth looking at: start, middle and end of the shot's real action
    (blink and idle_breathe don't count), or of the whole shot when nothing else happens."""
    d = float(shot["duration_s"])
    spans = []
    for c in shot["characters"]:
        for a in c.get("actions", []):
            if a["motion"] in QUIET_MOTIONS:
                continue
            start = float(a.get("start_s", 0))
            spans.append((start, start + float(a.get("duration_s") or 1.0)))
    last = max(d - 0.05, 0.0)
    if spans:
        first = min(s for s, _ in spans) + 0.25
        end = max(e for _, e in spans) - 0.1
    else:
        first, end = 0.1, d - 0.1
    times = sorted({round(min(max(t, 0.0), last), 2) for t in (first, (first + end) / 2, end)})
    kept: list[float] = []
    for t in times:
        if not kept or t - kept[-1] >= 0.5:
            kept.append(t)
    return kept[:limit]


def film_texts(film_dir: Path, shots: list[str]) -> tuple[str | None, list[tuple[str, str]]]:
    """(premise, [(label, text)]) for every dialogue line of the given shots."""
    premise = None
    film_json = film_dir / "film.json"
    if film_json.is_file():
        premise = json.loads(film_json.read_text()).get("premise")
    lines = []
    for sid in shots:
        for ln in load_shot(film_dir, sid).get("dialogue", []):
            lines.append((f"{sid} {ln.get('character', '?')} {ln.get('line_id', '')}", ln["text"]))
    return premise, lines
