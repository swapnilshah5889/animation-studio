"""audio_mcp: the director's sound tools over MCP (stdio), task 3.7.

    uv run audio-mcp                                      # stdio (Claude Code, Inspector)
    npx @modelcontextprotocol/inspector uv run audio-mcp  # browse and call the tools

The tools make **audio assets** for a film (D-036): voices and spoken lines with their mouth
cues, music cues, and sound-effect search. Shots use them by id through the animation server
(apply_lipsync, set_music, add_sound_effect). preview_mix mixes a shot's audio without rendering
its picture.

Same conventions as synfig_mcp (D-034): docstrings written for the model, validated arguments,
structured results with absolute file paths inside the film folder, refused requests raised as
ToolError with a message saying what to fix, and slow work (models, ffmpeg) in a worker thread.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from studio_core import shot_spec
from studio_core.audio import ffmpeg
from studio_core.audio.library import load_library
from studio_core.audio.lipsync import lipsync as run_lipsync
from studio_core.audio.mix import mix_shot
from studio_core.audio.music import INSTRUMENTS, MOODS
from studio_core.audio.music import compose as run_compose
from studio_core.audio.sfx import find_sfx as run_find_sfx
from studio_core.audio.voices import available, existing_lines, save_voice
from studio_core.audio.voices import speak as run_speak
from studio_core.config import load_config
from studio_core.sif.render import RenderError

Mood = Literal[tuple(MOODS)]  # type: ignore[valid-type]
Instrument = Literal[tuple(INSTRUMENTS)]  # type: ignore[valid-type]
FilmArg = Annotated[str, Field(description="Film folder name under films/, e.g. 'step2-demo'.")]
CharArg = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$", description="Character id, e.g. 'pip'.")
]
LineId = Annotated[str, Field(pattern=r"^l[0-9]{3,}$", description="A line id, e.g. 'l007'.")]

INSTRUCTIONS = """\
Sound tools for a children's film. They make audio assets; the animation server places them in
shots by id.

- Voices: describe_audio shows each character's voice and the installed voices. set_voice casts
  a character (once). speak turns text into recorded lines in that voice, with mouth cues, and
  returns line ids for apply_lipsync. Same text and voice = the cached take.
- Music: compose makes a cue from a mood, an energy (0 gentle, 1 lively) and optional
  instruments. Instrumental only. Use the cue id with set_music.
- Sound effects: find_sfx searches the CC0 library by description ("a squeaky door",
  "birds in the morning"). Use a sound_id with add_sound_effect.
- preview_mix mixes a shot's dialogue, effects and music (music dips under speech) to check
  levels without rendering the picture.

Everything must suit young children. Text that isn't is refused with the reason.
"""


class LineIn(BaseModel):
    text: str = Field(min_length=1, max_length=300, description="What the character says.")
    line_id: LineId | None = Field(
        default=None, description="Reuse or replace this line id; omit for a new line."
    )


class VoicePart(BaseModel):
    id: str = Field(pattern=r"^[a-z]{2}_[a-z]+$", description="A kokoro voice, e.g. 'af_heart'.")
    weight: float = Field(default=1.0, gt=0, le=1)


class CharacterAudio(BaseModel):
    id: str
    voice: dict[str, Any] | None = Field(description="Its voice.json, or null if not cast yet.")


class LineInfo(BaseModel):
    line_id: str
    character: str | None
    text: str | None
    duration_s: float
    has_mouth_cues: bool


class CueInfo(BaseModel):
    cue_id: str
    mood: str | None
    duration_s: float
    caption: str | None


class AudioDescription(BaseModel):
    film: str
    characters: list[CharacterAudio]
    lines: list[LineInfo]
    music_cues: list[CueInfo]
    installed_voices: dict[str, list[str]] = Field(description="Engine → voices you can cast.")
    moods: dict[str, str] = Field(description="Mood → what compose makes of it.")
    instruments: list[str]
    sound_library: dict[str, int] = Field(description="Sounds per source in the CC0 library.")


class VoiceResult(BaseModel):
    character_id: str
    voice_path: str
    voice: dict[str, Any]
    note: str


class SpokenLineOut(BaseModel):
    line_id: str
    text: str
    duration_s: float
    take: int
    cached: bool
    audio_path: str
    cues_path: str | None


class SpeakResult(BaseModel):
    character_id: str
    lines: list[SpokenLineOut]


class CuesOut(BaseModel):
    line_id: str
    cues_path: str
    n_cues: int
    shapes: str
    cached: bool


class ComposeResult(BaseModel):
    cue_id: str
    audio_path: str
    duration_s: float
    caption: str
    seed: int
    cached: bool
    peak_memory_gb: float | None


class SoundOut(BaseModel):
    sound_id: str
    score: float
    duration_s: float
    description: str
    tags: list[str]


class SearchResult(BaseModel):
    query: str
    sounds: list[SoundOut]


class SearchResults(BaseModel):
    results: list[SearchResult]


class MixResult(BaseModel):
    shot_id: str
    mix_path: str | None = Field(description="Null when the shot has no audio yet.")
    duration_s: float
    integrated_lufs: float | None
    true_peak_db: float | None
    warnings: list[str]


@contextmanager
def fixable() -> Iterator[None]:
    """Turn our validation errors into ToolErrors the model can read and act on."""
    try:
        yield
    except ToolError:
        raise
    except (ValueError, RenderError, RuntimeError) as e:
        raise ToolError(str(e)) from None


def create_server(films_root: Path | None = None, sfx_root: Path | None = None) -> MCPServer:
    """The server, with every tool registered."""
    cfg = load_config()
    root = films_root or cfg.path("paths", "films")
    server = MCPServer(
        "audio_mcp",
        title="Animation studio: sound (voices, music, sound effects)",
        instructions=INSTRUCTIONS,
        version="0.1.0",
    )

    def tool(name: str | None = None) -> Any:
        def register(fn: Any) -> Any:
            server.add_tool(fn, name=name, description=inspect.cleandoc(fn.__doc__ or ""))
            return fn

        return register

    def open_film(film: str) -> shot_spec.FilmFolder:
        return shot_spec.FilmFolder.open(root, film, sfx_root=sfx_root)

    async def in_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))

    @tool()
    def describe_audio(film: FilmArg) -> AudioDescription:
        """The film's sound: each character's voice (or that it isn't cast yet), recorded lines,
        music cues, the voices you can cast, the moods and instruments compose knows, and the
        size of the sound-effect library. Call this first."""
        with fixable():
            f = open_film(film)
            chars = []
            for cid in f.characters():
                voice_file = f.root / "characters" / cid / "voice.json"
                voice = json.loads(voice_file.read_text()) if voice_file.is_file() else None
                chars.append(CharacterAudio(id=cid, voice=voice))
            meta = existing_lines(f.root)
            lines = []
            for line_id in f.lines():
                wav, cues, txt = f.line_files(line_id)
                m = meta.get(line_id, {})
                text = m.get("text") or (txt.read_text().strip() if txt.is_file() else None)
                lines.append(
                    LineInfo(
                        line_id=line_id,
                        character=m.get("character"),
                        text=text,
                        duration_s=round(ffmpeg.duration(wav), 2),
                        has_mouth_cues=cues.is_file(),
                    )
                )
            cues = []
            for cue_id in f.music_cues():
                meta_file = f.music_file(cue_id).with_suffix(".json")
                m = json.loads(meta_file.read_text()) if meta_file.is_file() else {}
                cues.append(
                    CueInfo(
                        cue_id=cue_id,
                        mood=m.get("mood"),
                        duration_s=round(ffmpeg.duration(f.music_file(cue_id)), 2),
                        caption=m.get("caption"),
                    )
                )
            library = load_library(sfx_root)
            per_source: dict[str, int] = {}
            for sound in library.sounds.values():
                per_source[sound["source"]] = per_source.get(sound["source"], 0) + 1
            return AudioDescription(
                film=film,
                characters=chars,
                lines=lines,
                music_cues=cues,
                installed_voices=available(),
                moods={name: m["words"] for name, m in MOODS.items()},
                instruments=list(INSTRUMENTS),
                sound_library=per_source,
            )

    @tool()
    def set_voice(
        film: FilmArg,
        character_id: CharArg,
        voices: Annotated[
            list[VoicePart],
            Field(min_length=1, max_length=4, description="Kokoro voices to blend, by weight."),
        ],
        speed: Annotated[float, Field(ge=0.7, le=1.4, description="1 = natural pace.")] = 1.0,
        pitch_semitones: Annotated[
            float,
            Field(ge=-3, le=4, description="Raise for younger-sounding voices (+1 to +2)."),
        ] = 0.0,
        notes: Annotated[str | None, Field(max_length=500)] = None,
    ) -> VoiceResult:
        """Cast a character's voice (Kokoro voices; see installed_voices in describe_audio).
        Every line the character speaks from now on uses it. Lines spoken before keep their
        old voice until spoken again with speak."""
        with fixable():
            f = open_film(film)
            settings: dict[str, Any] = {
                "engine": "kokoro",
                "voices": [v.model_dump() for v in voices],
                "speed": speed,
                "pitch_semitones": pitch_semitones,
            }
            if notes:
                settings["notes"] = notes
            path = save_voice(f.root, character_id, settings)
            return VoiceResult(
                character_id=character_id,
                voice_path=str(path),
                voice=json.loads(path.read_text()),
                note="Speak lines again to hear them in this voice; cached takes stay as they are.",
            )

    @tool()
    async def speak(
        film: FilmArg,
        character_id: CharArg,
        lines: Annotated[list[LineIn], Field(min_length=1, max_length=20)],
        regenerate: Annotated[
            bool, Field(description="Make a new take even if this exact line exists.")
        ] = False,
    ) -> SpeakResult:
        """Record lines in the character's voice, with mouth cues (about 1-2 s per line). Returns
        line ids to place in shots with apply_lipsync. The same text in the same voice returns
        the existing take instantly."""
        with fixable():
            f = open_film(film)
            spoken = await in_thread(
                run_speak,
                f.root,
                character_id,
                [line.model_dump(exclude_none=True) for line in lines],
                regenerate=regenerate,
            )
            return SpeakResult(
                character_id=character_id,
                lines=[
                    SpokenLineOut(
                        line_id=s.line_id,
                        text=s.text,
                        duration_s=round(s.duration_s, 2),
                        take=s.take,
                        cached=s.cached,
                        audio_path=str(s.wav),
                        cues_path=str(s.cues) if s.cues else None,
                    )
                    for s in spoken
                ],
            )

    @tool()
    async def lipsync(
        film: FilmArg,
        line_ids: Annotated[list[LineId], Field(min_length=1, max_length=20)],
        force: Annotated[bool, Field(description="Redo even if the cues are current.")] = False,
    ) -> list[CuesOut]:
        """Make (or check) the mouth cues of recorded lines. speak already does this; use it for
        lines recorded elsewhere."""
        with fixable():
            f = open_film(film)
            results = await in_thread(run_lipsync, f.root, line_ids, force=force)
            return [
                CuesOut(
                    line_id=r.line_id,
                    cues_path=str(r.cues),
                    n_cues=r.n_cues,
                    shapes=r.shapes,
                    cached=r.cached,
                )
                for r in results
            ]

    @tool()
    async def compose(
        film: FilmArg,
        cue_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$", description="e.g. 'm01'.")],
        mood: Mood,
        duration_s: Annotated[float, Field(gt=0, le=60, description="Usually the shot's length.")],
        energy: Annotated[float, Field(ge=0, le=1, description="0 gentle, 1 lively.")] = 0.5,
        instruments: Annotated[
            list[Instrument] | None,
            Field(max_length=6, description="Defaults to the mood's own instruments."),
        ] = None,
        seed: Annotated[int | None, Field(ge=0, description="Another seed = another take.")] = None,
        regenerate: bool = False,
    ) -> ComposeResult:
        """Compose an instrumental music cue for a children's cartoon (about 20-40 s of work).
        Pick a mood and an energy; code writes the music model's prompt. Then place it with
        set_music. The same request returns the existing cue."""
        with fixable():
            f = open_film(film)
            cue = await in_thread(
                run_compose,
                f.root,
                cue_id,
                mood,
                duration_s,
                energy=energy,
                instruments=list(instruments) if instruments else None,
                seed=seed,
                regenerate=regenerate,
            )
            return ComposeResult(
                cue_id=cue.cue_id,
                audio_path=str(cue.wav),
                duration_s=round(cue.duration_s, 2),
                caption=cue.caption,
                seed=cue.seed,
                cached=cue.cached,
                peak_memory_gb=round(cue.peak_gb, 1) if cue.peak_gb else None,
            )

    @tool()
    async def find_sfx(
        queries: Annotated[
            list[Annotated[str, Field(min_length=2, max_length=100)]],
            Field(min_length=1, max_length=10, description="Describe each sound in words."),
        ],
        k: Annotated[int, Field(ge=1, le=20, description="Sounds per query.")] = 5,
        max_duration_s: Annotated[
            float | None, Field(gt=0, description="Only shorter sounds.")
        ] = None,
    ) -> SearchResults:
        """Search the CC0 sound-effect library by description, best match first. Ask for
        several sounds in one call. Use a sound_id with add_sound_effect."""
        with fixable():
            found = await in_thread(run_find_sfx, list(queries), k=k, max_duration_s=max_duration_s)
            return SearchResults(
                results=[
                    SearchResult(
                        query=q,
                        sounds=[
                            SoundOut(
                                sound_id=c.sound_id,
                                score=c.score,
                                duration_s=c.duration_s,
                                description=c.description,
                                tags=c.tags,
                            )
                            for c in cands
                        ],
                    )
                    for q, cands in zip(queries, found, strict=True)
                ]
            )

    @tool()
    async def preview_mix(
        film: FilmArg,
        shot_id: Annotated[str, Field(pattern=r"^s[0-9]{2}_sh[0-9]{2}$")],
    ) -> MixResult:
        """Mix a shot's audio (dialogue, sound effects, music dipping under speech) to a WAV
        without rendering the picture, and report its loudness. A quick check before
        render_shot."""
        with fixable():
            f = open_film(film)
            spec = shot_spec.load(f, shot_id)
            errors, warnings = shot_spec.check(f, spec)
            if errors:
                raise ToolError("fix the shot first: " + "; ".join(errors))
            out = f.shot_file(shot_id).parent / "mix.wav"
            mixed = await in_thread(mix_shot, f.root, spec, out)
            loud = ffmpeg.measure(mixed) if mixed else None
            return MixResult(
                shot_id=shot_id,
                mix_path=str(mixed) if mixed else None,
                duration_s=spec["duration_s"],
                integrated_lufs=round(loud.integrated_lufs, 1) if loud else None,
                true_peak_db=round(loud.true_peak_db, 1) if loud else None,
                warnings=warnings,
            )

    return server


def main() -> None:
    create_server().run()  # stdio


if __name__ == "__main__":
    main()
