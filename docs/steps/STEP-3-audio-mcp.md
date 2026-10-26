# Step 3: `audio_mcp`: voices, lip-sync, music, sound effects and the mix

> **Status: done (2026-10-22).** Approved as written (D-036). Every done-when item is met. One
> addition, task 3.2b (Indian voices with Indic Parler-TTS, D-042), is built but its gated
> download is deferred by the owner. Changes during the build are in D-037 to D-046.

**Goal:** an MCP server that turns the director's intent into the sound of a shot. Each
character speaks with their own voice and the mouth follows automatically. A music cue fits the
mood, sound effects are found by describing them, and everything is mixed so the dialogue stays
clear and the loudness is right for the web. Along the way, this step builds the project's first
**vector search** (sound effects by meaning, with CLAP embeddings in Qdrant): the owner's
RAG/embeddings learning goal.

**Out of scope:**
- Film-level music and the final film mix (Step 5, `edit_mcp`): here, music and sound effects
  belong to one shot.
- The director agent (Step 5). Scripted MCP clients and the Inspector are the clients here.
- Voice cloning of real people. Any reference voice must be our own generated or licensed audio.
- Languages other than English (the lip-sync recognizer and the voices are English-first).
- The Windows render node (Step 5): everything runs on the Mac for now.

## What Steps 0–2 established (build on it, don't relitigate)

- **TTS (D-021):** Kokoro-82M in `envs/kokoro` (torch 2.14, transformers 5.20), weights in
  `~/ai-studio/models/kokoro-82m`, 6 voices downloaded, CPU by default, ~10x faster than real
  time. `scripts/audio/kokoro_say.py` is the working entry point.
- **Lip-sync (D-022):** Rhubarb 1.14.0 (x86_64, under Rosetta) with the dialogue text passed in
  (`--dialogFile`). ~6.8 s per 10 s of audio. Its JSON cues already drive the procedural mouth
  (shapes A–H and X, D-007) through `apply_lipsync` → `audio/lipsync/<line>.json`.
- **Music (D-020):** ACE-Step 1.5 turbo in `~/ai-studio/ace-step` (own env), 10.1 GB of weights.
  **Open problem: one 30 s cue peaks at ~30 GB footprint and swaps.** This step must fix that
  before music runs in the pipeline.
- **Qdrant** v1.19.2 runs in Docker (`infra/docker-compose.yml`), data in
  `~/ai-studio/qdrant-data`, telemetry off. Healthy, and empty so far.
- **Shot specs (D-028, D-034):** `shot.json` already has `dialogue` lines (by `line_id`), `sfx`
  (`query`, `start_s`, `volume`) and `music_cue`. `render_shot` mixes dialogue only. The spec
  editor (`studio_core/shot_spec.py`) checks every edit against the film's assets.
- **Machine rules:** one large model in memory at a time; models run natively, never in Docker;
  large files under `~/ai-studio/`.
- **ffmpeg 9.0.2** has `loudnorm`, `ebur128` and `sidechaincompress`, but **no `rubberband`**
  (no high-quality pitch shifting without another install).

## Owner checkpoints

1. **Approve this brief.**
2. **Voice casting (task 3.2):** a listening page with each candidate voice saying the same two
   lines, plus the child-voice variants. The owner picks Pip's voice and a second character's.
3. **Music taste (task 3.4):** three moods, two takes each, at the fixed memory budget.
4. **Final shot (task 3.8):** the done-when shot, with the voice, mouth, music and a sound effect.

## Design decisions proposed here (owner may overrule)

| Topic | Proposal | Why |
|---|---|---|
| Server split | `audio_mcp` **makes audio assets** (lines, cues, music, sound search). Shot specs keep referencing them by id, through new shot-editing tools on the animation server (`add_sound_effect`, `set_music`) over `shot_spec` | One place edits shots; audio stays engine-neutral (D-030) and reusable by the director and `edit_mcp` |
| Process model | `mcp/audio_mcp/` is a workspace member that runs each model in **its own env as a subprocess** (D-016): Kokoro and CLAP in their envs, ACE-Step in its env. Tools take **batches** (`speak` many lines at once) so model load time is paid once | Pins can't collide; the MCP process stays light; no daemon to babysit yet (Temporal workers come in Step 8) |
| Voice per character | `characters/<id>/voice.json` (new `voice.schema.json`): TTS engine, voice id or a blend of voices, speed, a pitch step (semitones), a loudness target. The director never names raw voices in a line; the character's voice is used | Consistent voices across a film; casting is a one-time decision (checkpoint 2) |
| Child-like voices | Kokoro has no child voices and no pitch control. So: audition youthful-sounding voices (`af_heart`, `af_bella`, `af_nicole`, `af_sky`; `am_puck` for a boy), **blend** them (the `kokoro` package averages voice packs, e.g. `"af_heart,af_sky"`), and adjust speed. If that isn't enough, a **small pitch step** with ffmpeg (`asetrate` + `atempo` + `aresample`), which raises pitch *and* formants together, like a shorter vocal tract | Children's voices differ in formants as well as pitch; formant-preserving shifts (rubberband) would need another install |
| Dialogue files | `audio/dialogue/<line>.wav` + `.txt` + **`.json`** (character, text, voice settings, model, duration, a content hash). Same text + same voice = same hash = no re-synthesis | Reproducible, cacheable, and the director can regenerate a line on purpose |
| Lip-sync format | Keep **Rhubarb's JSON** (`mouthCues`: start, end, shape) as our format, formalized as `lipsync.schema.json`, always computed from the **final processed** line audio | It already drives the mouth; computing after pitch/speed changes keeps timing exact |
| Music | **Intent in, caption out:** `compose(mood, duration_s, energy, instruments?)`. Code builds the ACE-Step caption from a small, tested table of moods and instruments, so the director never writes model-specific prompts. Fixed seeds, recorded in `audio/music/<cue>.json` | Rules in code; reproducible; safe for children (no lyrics in v1) |
| Music memory | Fix it before anything else in 3.4. Options, measured in order: (a) the reference repo with its own memory switches (`--offload_to_cpu`, `ACESTEP_VAE_ON_CPU=1`, half precision where it allows, `PYTORCH_MPS_HIGH_WATERMARK_RATIO`); (b) ComfyUI's native ACE-Step 1.5 nodes with the bf16 turbo DiT (ComfyUI manages precision and unloading). **Budget: peak footprint ≤ 14 GB, no swap**, with Ollama unloaded first | The ~30 GB peak matches fp32 weights (~2x the ~8.8 GB bf16 set), so half precision alone should roughly halve it; the budget leaves room for the OS and the app |
| Sound effects | A **CC0-only** starter library (sources below) under `~/ai-studio/sfx-library`, with a manifest recording each file's source and license. Indexed with **CLAP** (`laion/larger_clap_general`, 512-dim) audio embeddings in Qdrant (collection `sfx`, cosine). Text queries use CLAP's text embedding; descriptions and tags are stored as payload for filtering and a keyword fallback (hybrid search) | Search by meaning ("a soft cartoon pop") without hand tagging; CC0 removes attribution bookkeeping |
| Sound resolution | `find_sfx` returns candidates, and the chosen **sound id is stored in the shot spec** (an additive `sound` field next to `query`) | Renders stay deterministic even if the library or the index changes |
| The mix | Per shot: dialogue + sound effects + music. Music is **ducked under dialogue with a volume envelope computed from the line times** (e.g. −10 dB with 150 ms ramps), not a compressor; `sidechaincompress` stays as a fallback. Then two-pass **`loudnorm`** (`linear=true`, 48 kHz) to **−14 LUFS integrated, −1.5 dBTP** for the web, with an EBU R128 (−23 LUFS) export option later. The numbers live in config | Dialogue clarity is the first rule of children's audio. We know exactly when each line plays, so the envelope is deterministic and testable (rules in code). Two-pass loudnorm is accurate |
| Safety | Text to speak is checked before synthesis (length, characters, and a small blocklist; the Step 5 safety classifier replaces it). Music has no lyrics in v1 | D-013: everything generated must be age-appropriate |

## Installs this step needs (approve with the brief)

Everything runs locally; no API keys. Each download is under the ~20 GB ask-first limit.
Sources and dates are in "Research notes" at the end.

| Install | License | Size | Where |
|---|---|---|---|
| CLAP `laion/larger_clap_general` (fallback: `laion/clap-htsat-unfused`, 615 MB) | Apache-2.0 weights; LAION code CC0. **Provenance note:** trained on LAION-Audio-630K, which includes research-only sources | 776 MB | `~/ai-studio/models/clap/`, run from a new `envs/clap` (torch + transformers; uv's cache makes a second torch env nearly free on disk). CPU (MPS unverified; CPU is fine for a few thousand clips) |
| `qdrant-client` | Apache-2.0 | small | workspace |
| 4–5 more Kokoro voice packs for casting (`af_nicole`, `af_sky`, ...) | Apache-2.0 | ~0.5 MB each | `~/ai-studio/models/kokoro-82m/voices/` |
| Kenney audio packs (Impact, Interface, RPG, UI, ...) | **CC0**, per pack | under 100 MB | `~/ai-studio/sfx-library/kenney/` (direct zips, no account; OGG, file names only) |
| OpenGameArt CC0 packs (e.g. "512 Sound Effects (8-bit style)") | **CC0**, checked per pack | ~20–100 MB | `~/ai-studio/sfx-library/oga/` |
| BigSoundBank: 300–500 hand-picked sounds (toys, animals, water, wind, doors) | **CC0** per sound (some by other contributors: checked per page) | ~0.2–0.5 GB | `~/ai-studio/sfx-library/bsb/`. No bulk download: a curated list fetched politely, after checking the site's terms |
| *Optional:* the CC0 clips of FSD50K's eval split, with a child-safe label filter | per clip: keep **CC0 only** (~4.9k clips) | 6.2 GB download | `~/ai-studio/sfx-library/fsd50k/`. Owner decides after the spot-check |
| *Only if option (a) misses the memory budget:* ComfyUI ACE-Step 1.5 files (turbo DiT, Qwen 0.6B encoder, VAE) | Apache-2.0 repackage of MIT weights | ~6.3 GB | ComfyUI models folder |
| *Optional, decided at checkpoint 2:* Chatterbox TTS 0.1.7 (Turbo, 350M, English, tags like `[laugh]`) | MIT (code and weights) | ~1–2 GB (to confirm) | own env `envs/chatterbox`: it pins torch 2.6.0, numpy<2 and transformers 5.2.0 |

**Not used, and why:** Sonniss GDC bundles (not CC0; its license now forbids AI training), BBC
Sound Effects (non-commercial licence), bulk Freesound (originals need OAuth2, and the API
terms forbid copying the database).

## Tasks

### 3.1 Audio schemas and file layout
- `schemas/voice.schema.json` (`characters/<id>/voice.json`), `schemas/line.schema.json`
  (`audio/dialogue/<line>.json`), `schemas/lipsync.schema.json` (Rhubarb's cue JSON),
  `schemas/music.schema.json` (`audio/music/<cue>.json`), and the sound library's manifest.
- Shot schema, additive: `sfx[].sound` (the chosen library id), and `music_volume`.
- Semantic checks: line audio, cues and sounds exist; cues end within the audio's length.
- Same rules as Step 2: no engine-specific fields (D-030), valid and invalid fixtures tested.

### 3.2 Voices: `speak` (owner checkpoint 2)
- `speak(film, character_id, lines: [{line_id?, text}])` → WAV + TXT + JSON per line, 24 kHz mono,
  trimmed of leading and trailing silence, each line loudness-normalized for speech.
- Voice from `voice.json`: Kokoro voice or blend, speed, optional pitch step.
- Kokoro gets weaker on very short inputs (under 10–20 tokens), and children's lines are often
  short ("Hi!"). Measure it, and pad or batch short lines if needed.
- If Chatterbox is approved at checkpoint 2: its built-in Perth watermark **stays on**, and its
  reference voice is its default voice or one of our own Kokoro clips, **never a real person**.
- Cache by content hash; `regenerate=true` forces a new take.
- `scripts/audio/voice_casting.py`: a page of candidate voices for checkpoint 2.

### 3.3 Lip-sync: `lipsync`
- `lipsync(film, line_ids)` runs Rhubarb with the line text on the final WAV and writes
  `audio/lipsync/<line>.json`. `speak` calls it by default, so a spoken line is always ready for
  `apply_lipsync`.
- Recognizer: `pocketSphinx` for English (the default), `phonetic` for anything else. Extended
  shapes G, H, X stay on (Rhubarb's default), matching our mouth set.
- Tests: cue timing covers the audio, and the shapes are within our set.

### 3.4 Music: `compose` (owner checkpoint 3)
- First, the memory fix, measured with `memwatch` against the 14 GB budget (decision table).
- `compose(film, cue_id, mood, duration_s, energy, instruments?)`: the caption is built in code,
  fixed seed, 48 kHz stereo WAV trimmed or looped to length with fade-out, plus metadata JSON.
- Before composing, unload Ollama models (`keep_alive: 0`) and refuse to run if ComfyUI holds
  memory.

### 3.5 Sound-effect library and search: `find_sfx`
- `scripts/fetch_sfx_library.py`: download the approved CC0 sources, convert to WAV, write the
  manifest (id, source, license, original name, tags, duration). Idempotent.
- `scripts/index_sfx.py`: CLAP audio embeddings → Qdrant collection `sfx`, with the manifest as
  payload. Re-indexing is idempotent (point ids from file hashes).
- `find_sfx(query, k=5, max_duration_s?)` → candidates with id, score, duration and a short
  description.
- A small retrieval spot-check: ~15 cartoon queries with the sound categories they should find.
  This is a test, not the Step 7 eval harness.
- Note: `docs/learning/embeddings-and-vector-search.md`.

### 3.6 The mix
- `studio_core/audio/mix.py` (engine-neutral): dialogue bus, sound-effect bus (each at its
  `start_s` and `volume`), and a music bus whose volume envelope dips under every line (computed
  from the line times), then two-pass loudnorm and a true-peak limit.
- `render_shot` uses it in place of today's dialogue-only mix.
- Tests measure the result: the music is ducked by the configured amount while a line plays,
  integrated loudness is within ±1 LU of the target, and each sound effect starts within 10 ms
  of its time.

### 3.7 `audio_mcp` server, and shot tools for sound
- `mcp/audio_mcp/` (stdio, same SDK and conventions as `synfig_mcp`, D-034): `describe_audio`,
  `set_voice`, `speak`, `lipsync`, `compose`, `find_sfx`, `preview_mix`.
- On the animation server: `add_sound_effect(shot, sound_id, start_s, volume)` and
  `set_music(shot, cue_id, volume)`, over `shot_spec`.
- Tested through a real MCP client in-process and over stdio, plus `scripts/inspector_check.py`
  extended to the new server.

### 3.8 Prove it (owner checkpoint 4)
- A scripted MCP client builds the done-when shot through both servers
  (`scripts/run_step3_shot.py`).
- The owner watches and listens.

### 3.9 Docs
- Learning notes: TTS and voices; lip-sync (phonemes → visemes); embeddings and vector search
  (CLAP, cosine similarity, Qdrant collections, payload filters); loudness and ducking.
- DECISIONS, PROGRESS, MODELS (every model and the sound library, with licenses), and the Step 4
  brief (`comfy_mcp`).

## Proposed addition: Indian voices (task 3.2b), not yet approved

> **Status: approved (D-042); part 1 built; the rest deferred by the owner (2026-10-22).** The
> Parler engine, env, worker and tests are in, and Kokoro's Hindi voices work. The gated Parler
> download, its measurements and the Indian-voices casting page wait until the owner plans the
> Hugging Face login. Research is summarized below; sources are in "Research notes: Indian
> voices".

**What we have today (probed 2026-10-22):**
- Kokoro speaks **Hindi** with 4 voices (`hf_alpha`, `hf_beta`, `hm_omega`, `hm_psi`). Its Hindi
  pronunciation component (espeak-ng, bundled via pip) is already in `envs/kokoro`.
- One Hindi voice (`hf_alpha`, 0.5 MB) was fetched for the probe: a Hindi line took 1.3 s.
  Rhubarb's language-independent recognizer gave 46 mouth cues over 8 shapes.
- A Hindi voice reading English through Kokoro's English rules is a free, zero-install way to an
  Indian accent. It is in `renders/indian-voices-probe/` for the owner to judge.
- Kokoro has **no Indian-English voice**. That needs another model.

**Proposal: Indic Parler-TTS (AI4Bharat) as a second TTS engine.**

| | Indic Parler-TTS |
|---|---|
| License | **Apache-2.0** weights. Training data: IndicTTS, LIMMITS, Rasa (CC-BY-4.0) + GLOBE. Commercial use OK |
| Access | **Gated:** the owner accepts the terms on Hugging Face once and logs in (a free token, allowed by AGENTS.md). Fully offline after the download |
| Size | 0.94B params, ~3.7 GB fp32 download (under the 20 GB ask-first limit) |
| Languages | **Indian English, stated explicitly by its card**, Hindi and ~19 more Indian languages, in one model |
| Voices | 21 named English speakers (Thoma and Mary recommended) and 4 Hindi speakers (Rohit and Divya recommended). A character = a speaker + a fixed description, so the voice stays the same |
| Control | Description text: pitch, pace, expressivity, recording quality. No emotion control for English or Hindi. **No child voices** (only "young" or "high-pitched") |
| Mac | Small enough to sit beside nothing else (one large model at a time). Reported MPS quirks have a CPU fallback. Speed on Mac is unpublished: we measure it |
| Runtime | `parler-tts` from git, which pins `transformers==4.46.1`, so it gets its own env `envs/parler` (D-016) |
| Quality | Paper (Interspeech 2025): NORESQA-MOS 4.14, MUSHRA 81.7 vs 89.7 for humans. No English-only score |

**How it fits what we built (est. ~1 day):**
1. `voice.json`, additive:
   - `engine: "parler"`
   - a `language` (`en-in`, `hi`, ...)
   - Parler voices are a named `speaker` plus structured pitch, pace and expressivity fields.
     Code writes Parler's description from those fields; the LLM never writes it (rules in
     code).
   - Kokoro voices stay as they are.
2. `scripts/audio/parler_batch.py` in `envs/parler`, with the same JSON-in/JSON-out protocol as
   the Kokoro worker. A **fixed seed per line**: Parler samples randomly, and the seed goes into
   the line hash, so takes stay reproducible.
3. Everything after synthesis is unchanged:
   - the trim, pitch step and loudness pass (the pitch step is also our route to child-like
     Indian voices)
   - the cache by hash and the line files
   - lip-sync: Rhubarb with the text, the English recognizer for Indian English, the phonetic
     one for Hindi
4. The text check learns Devanagari (vowel signs and the danda are refused today). The
   blocklist stays English-only until the Step 5 safety classifier.
5. Measure: speed, memory peak and MPS stability on the M4. A test like `speak`'s.
6. **Casting page:**
   - Parler's English speakers (Indian English), with and without the pitch step
   - its Hindi speakers, plus Kokoro's 4 Hindi voices (3 more packs, 1.5 MB)
   - the probe's "Hindi voice reading English"
   - The owner picks; that becomes D-0xx.

**Alternatives considered:**
- **Indic-Speak** (Bodhan AI, Sept 2026, now recommended by AI4Bharat):
  - better measured quality (MOS 4.46), 44 Indian English voices
  - but a custom license (Indic Open Model License + Llama 3.2: share-alike derivatives,
    hosting as an API needs approval, a revenue cap, prohibited uses), gated
  - 3.8B params (7.6 GB), and slower than real time on a Mac through a community MLX port
  - Worth a listening comparison only if Parler disappoints, and only after the owner reads its
    license.
- **svara-TTS v1** (Apache tag on a Llama 3.2 base): 3B params, explicit Indian English, emotion
  tags. Untested on a Mac. Second fallback.
- **Chatterbox Multilingual** (MIT): Hindi yes. Indian English only by cloning a reference
  clip, and we don't clone real people.
- **IIT Madras FastSpeech2** (CC-BY-4.0 / IITM EULA): one Indian English voice per gender,
  robotic, CUDA-oriented.
- **Not usable:**
  - Piper has no Indian English, and 2 of its 3 Hindi voices are non-commercial.
  - MMS-TTS, XTTS-v2 and OmniVoice weights are non-commercial.
  - A Kokoro fine-tune with Indian English voices (goonj) was trained on audio generated by
    commercial TTS services: doubtful provenance.
  - Sarvam's voices are API-only.

**What the owner would approve:**
1. Task 3.2b, as above.
2. `envs/parler` and the Indic Parler-TTS download (~3.7 GB).
3. 3 more Kokoro Hindi voice packs (1.5 MB).
4. The owner's own step: accept the model's terms on its Hugging Face page and run
   `hf auth login` in a terminal. Agents never handle tokens.

## Research notes: Indian voices

Web research, 2026-10-22 (nothing downloaded except the 0.5 MB probe voice):
- [ai4bharat/indic-parler-tts](https://huggingface.co/ai4bharat/indic-parler-tts) (card:
  "officially supports Indian English accents"; Apache-2.0; gated)
- Paper: [arXiv 2505.18609](https://arxiv.org/abs/2505.18609)
- Runtime: [huggingface/parler-tts](https://github.com/huggingface/parler-tts) (0.2.2, pins
  transformers 4.46.1)
- Indic-Speak: [bodhan-ai/indic-speak](https://huggingface.co/bodhan-ai/indic-speak); its MLX
  port: [iniquitous/indic-speak-mlx-bf16](https://huggingface.co/iniquitous/indic-speak-mlx-bf16)
  (~28 tok/s on an M3 Max)
- svara-TTS: [kenpath/svara-tts-v1](https://huggingface.co/kenpath/svara-tts-v1)
- Chatterbox: [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox)
- IITM: [smtiitm/Fastspeech2_HS](https://huggingface.co/smtiitm/Fastspeech2_HS)
- Piper English voices:
  [rhasspy/piper-voices/en](https://huggingface.co/rhasspy/piper-voices/tree/main/en)
- Unclear until tried: Parler's speed and MPS stability on the M4; exact download sizes behind
  the gate.

## Done when

- [x] Audio schemas approved with this brief's decisions; valid and invalid fixtures tested
- [x] The owner cast two voices (Pip c12, Bunny c03, D-039); `speak` + `lipsync` produce a line,
      its text, metadata and cues in one call, cached by hash
- [x] `compose` makes a 10 s cue within the memory budget: 9.6 GB peak, no swap (D-041)
- [x] The CC0 library is downloaded (4,268 sounds), licensed in its manifest, and indexed;
      `find_sfx` passes the retrieval spot-check (24/24)
- [x] Mix tests pass (ducking depth, loudness ±1 LU, sound timing ±10 ms)
- [x] **A line of dialogue is voiced, lip-synced onto the Step 2 puppet automatically, and mixed
      with music and one sound effect into a playable shot, all through MCP tools** (ROADMAP
      Step 3): `scripts/run_step3_shot.py`, approved by the owner (checkpoint 4)
- [x] Learning notes, DECISIONS, PROGRESS, MODELS updated; Step 4 brief drafted; work committed
      and pushed

## Risks

- **ACE-Step memory:** if neither option fits the budget, music falls back to shorter cues
  looped, or to the ComfyUI path with a smaller model. The owner decides at checkpoint 3.
- **Rhubarb under Rosetta:** the 1.14.0 macOS build is x86_64 only, and Apple supports Rosetta
  fully only through macOS 27 (from macOS 28, games only). A native arm64 build from source is a
  follow-up to schedule before that upgrade (D-022). It needs build tools, so it's not in this
  step unless the owner asks.
- **Training-data provenance:** CLAP's and Kokoro's weights are permissively licensed, but their
  training data includes research-only or synthetic sources. Recorded in MODELS.md, as for
  every model (D-012).
- **CC0 coverage:** cartoon-specific sounds (boings, slide whistles) are rarer in CC0 sets than
  ambience. If the spot-check shows gaps, the owner chooses whether to accept CC-BY sources with
  an attribution file.
- **CLAP quality on short cartoon sounds** is unknown until measured. File names and tags as a
  keyword fallback are cheap insurance.

## Research notes

Web research, 2026-10-22 (nothing downloaded). The facts the decisions above rely on:

- **Kenney** audio: CC0 for every pack, direct zips, no account (kenney.nl/support,
  kenney.nl/assets/category:Audio).
- **BigSoundBank:** ~3,500 sounds marked CC0, with WAV at 44.1 kHz/16-bit, descriptions,
  keywords and UCS categories, but no bulk download (bigsoundbank.com/droit.html).
- **OpenGameArt:** mixed licenses; the CC0 + sound effect filter shows ~900 entries
  (opengameart.org/node/55379 for the 8-bit pack).
- **FSD50K** (zenodo.org/records/4060432): 51k clips, 24.7 GB. Licenses are per clip (CC0, CC-BY,
  CC-BY-NC, Sampling+), listed in the metadata. The eval split is 6.2 GB with ~4.9k CC0 clips.
  The full splits must be downloaded to filter.
- **Sonniss** GDC license v2.0 (27 Aug 2026) prohibits AI training; **BBC** RemArc is
  non-commercial; **Freesound** API: OAuth2 for originals, commercial use "case by case", no full
  copies.
- **CLAP:**
  - `laion/larger_clap_general`: Apache-2.0, 776 MB `.bin`, 512-dim. It loads with
    `transformers` `ClapModel`, still documented in v5.20; `.bin` weights need torch ≥ 2.6.
  - Microsoft's `msclap` was archived on 15 Sep 2026, so it's not used.
- **Chatterbox** 0.1.7 (26 Mar 2026), MIT. Variants: original 500M, multilingual, Turbo 350M,
  Nano 110M.
  - It pins torch 2.6.0, numpy<2 and transformers 5.2.0.
  - The Perth watermark is applied on every `generate()`.
  - `exaggeration` ≥ 0.7 with `cfg_weight` ≈ 0.3 gives expressive speech.
- **Kokoro** v1.0 voices (huggingface.co/hexgrad/Kokoro-82M, VOICES.md): best graded are
  `af_heart`, `af_bella` (A-), `af_nicole` and `bf_emma` (B-). There are no age descriptors and
  no child voices. Blending: a comma-separated voice list, averaged. `speed` exists; pitch doesn't.
- **Loudness:**
  - EBU R128: −23 LUFS, ≤ −1 dBTP.
  - AES TD1004: −16 to −20 LUFS for streaming.
  - YouTube: no official spec; practice is −14 LUFS, ≤ −1 dBTP, and loud uploads are turned
    down.
  - ffmpeg `loudnorm` defaults to I=−24, TP=−2. Use two passes (measure, then apply with
    `linear=true`), and `-ar 48000` because dynamic mode upsamples.
- **ACE-Step 1.5:** the bf16 turbo DiT is ~4.7 GB. The repo has `--offload_to_cpu` (automatic
  under 20 GB) and `ACESTEP_VAE_ON_CPU=1`. A community MLX fp16 conversion peaks at ~7 GB
  (decoder only). ComfyUI core has native ACE-Step 1.5 nodes (`comfy_extras/nodes_ace.py`); our
  ComfyUI version must be checked for them.
- **Rhubarb 1.14.0:** `--dialogFile`, `-r pocketSphinx|phonetic`, `--extendedShapes` (default
  GHX), `-f json` → `{metadata, mouthCues: [{start, end, value}]}`. The macOS build comes from an
  Intel CI runner (x86_64).
