# Models registry

Every model downloaded for this project. **Check the license before downloading.**
"Commercial OK" means films made with it could be published and monetized.
Machine-readable manifest for ComfyUI weights (URLs, sha256, presets): `config/models.toml`.
Background on license families: [`learning/model-licenses.md`](learning/model-licenses.md).

| Model | Role | Source | License | Commercial OK | Size | Location | Added |
|---|---|---|---|---|---|---|---|
| Qwen3 14B (`qwen3:14b`, Q4_K_M) | Director candidate | [ollama.com/library/qwen3](https://ollama.com/library/qwen3) | Apache-2.0 (license layer in the Ollama manifest) | Yes | 9.3 GB | Ollama store | 2026-10-19 |
| gpt-oss 20B (`gpt-oss:20b`, MXFP4) | Director candidate | [ollama.com/library/gpt-oss](https://ollama.com/library/gpt-oss) | Apache-2.0 (license layer) | Yes | 13.8 GB | Ollama store | 2026-10-19 |
| Qwen3-VL 8B Instruct (`qwen3-vl:8b-instruct`) | Vision QA, default (D-018) | [ollama.com/library/qwen3-vl](https://ollama.com/library/qwen3-vl) | Apache-2.0 (license layer) | Yes | 6.2 GB | Ollama store | 2026-10-19 |
| Qwen3-VL 8B Thinking (`qwen3-vl:8b`) | Vision QA, slower thinking variant kept for comparison (`ollama rm qwen3-vl:8b` to free 6 GB) | [ollama.com/library/qwen3-vl](https://ollama.com/library/qwen3-vl) | Apache-2.0 (license layer) | Yes | 6.2 GB | Ollama store | 2026-10-19 |
| SDXL Base 1.0 | Image generation: checkpoint of the default preset (D-019) | [stabilityai/stable-diffusion-xl-base-1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) | CreativeML OpenRAIL++-M (use-based restrictions, e.g. no harm to minors) | Yes | 6.9 GB | `~/ai-studio/comfyui/models/checkpoints/` | 2026-10-19 |
| StoryBookRedmond-V2 LoRA | Flat kids'-book style (default preset) | [artificialguybr/StoryBookRedmond-V2](https://huggingface.co/artificialguybr/StoryBookRedmond-V2) | CreativeML OpenRAIL-M; training data undocumented | Yes | 171 MB | `.../models/loras/` | 2026-10-19 |
| SDXL-Lightning 8-step LoRA | Speed LoRA (fast variant, CFG 1) | [ByteDance/SDXL-Lightning](https://huggingface.co/ByteDance/SDXL-Lightning) | CreativeML OpenRAIL++-M | Yes | 394 MB | `.../models/loras/` | 2026-10-19 |
| sdxl-vae-fp16-fix | SDXL VAE that is safe in fp16 on MPS | [madebyollin/sdxl-vae-fp16-fix](https://huggingface.co/madebyollin/sdxl-vae-fp16-fix) | MIT | Yes | 335 MB | `.../models/vae/` | 2026-10-19 |
| SAM 2.1 hiera-small (safetensors) | Segmentation: cutting puppets into parts | [Kijai/sam2-safetensors](https://huggingface.co/Kijai/sam2-safetensors) (conversion of Meta's [SAM 2](https://github.com/facebookresearch/sam2)) | Apache-2.0 | Yes | 184 MB | `.../models/sam2/` | 2026-10-19 |
| Depth Anything V2 **Small** | Depth for parallax layers | [depth-anything/Depth-Anything-V2-Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small) | Apache-2.0 (**Base/Large are CC-BY-NC-4.0: never use**) | Yes | 99 MB | `.../models/annotators/depth-anything/Depth-Anything-V2-Small/` | 2026-10-19 |
| Kokoro-82M v1.0 + 14 voices (af_heart, af_bella, af_nicole, af_sky, af_aoede, af_kore, am_michael, am_puck, bf_emma, bm_george, and the Hindi hf_alpha, hf_beta, hm_omega, hm_psi; the four casting and four Hindi voices added 2026-10-22, ~0.5 MB each, D-042) | Text-to-speech (D-021, D-036) | [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | Apache-2.0. Training data includes synthetic audio from closed TTS providers (provenance note) | Yes | 317 MB | `~/ai-studio/models/kokoro-82m/` | 2026-10-19 |
| ACE-Step 1.5: turbo DiT, VAE, Qwen3-Embedding-0.6B text encoder, 5Hz LM 1.7B (installed, unused) | Music (D-020) | [ACE-Step/Ace-Step1.5](https://huggingface.co/ACE-Step/Ace-Step1.5) | MIT (Qwen3-Embedding: Apache-2.0) | Yes | 10.1 GB | `~/ai-studio/models/ace-step-1.5/` | 2026-10-19 |
| spaCy `en_core_web_sm` 3.8.0 | English tokenizer/tagger used by Kokoro's G2P (misaki) | [explosion/spacy-models](https://github.com/explosion/spacy-models) | MIT | Yes | 12 MB | `envs/kokoro/.venv` (pinned wheel) | 2026-10-19 |
| Rhubarb's PocketSphinx models | Speech recognition inside Rhubarb Lip Sync | Bundled with [Rhubarb 1.14.0](https://github.com/DanielSWolf/rhubarb-lip-sync/releases/tag/v1.14.0) | BSD-style (CMU Sphinx); Rhubarb itself MIT | Yes | 82 MB | `~/ai-studio/tools/rhubarb/res/` | 2026-10-19 |
| CLAP `laion/larger_clap_general` | Audio-text embeddings for sound-effect search (task 3.5, D-036) | [laion/larger_clap_general](https://huggingface.co/laion/larger_clap_general) | Apache-2.0 (weights); LAION code CC0. Provenance note: trained on LAION-Audio-630K, which includes research-only sources | Yes | 744 MB | `~/ai-studio/models/clap/larger_clap_general/` | 2026-10-22 |
| xinsir ControlNet union SDXL 1.0 **ProMax** | Pose conditioning (skeletons drawn in code) and inpaint/repaint (Step 4, D-047) | [xinsir/controlnet-union-sdxl-1.0](https://huggingface.co/xinsir/controlnet-union-sdxl-1.0) | Apache-2.0 | Yes | 2.34 GB | `.../models/controlnet/` | 2026-10-22 |
| Depth Anything 3 **MONO-LARGE** (ComfyUI repackage) | Depth for parallax layers (D-047) | [Comfy-Org/Depth-Anything-3](https://huggingface.co/Comfy-Org/Depth-Anything-3) ([upstream](https://github.com/ByteDance-Seed/Depth-Anything-3)) | Apache-2.0 (**Giant/Nested are NC**) | Yes | 1.24 GB | `.../models/geometry_estimation/` | 2026-10-22 |
| SAM 2.1 hiera **base+** (fp32 safetensors) | Silhouette refinement for puppets (D-047) | [Kijai/sam2-safetensors](https://huggingface.co/Kijai/sam2-safetensors) | Apache-2.0 | Yes | 0.30 GB | `.../models/sam2/` | 2026-10-22 |
| Real-ESRGAN x4plus_anime_6B + x4plus | Background upscaling (D-047) | [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | BSD-3-Clause | Yes | 18 MB + 64 MB | `.../models/upscale_models/` | 2026-10-22 |
| FLUX.2 [klein] **4B** (distilled, bf16) + Qwen3-4B text encoder + FLUX.2 VAE | Trial: front → three-quarter character edits (task 4.5, owner approved, D-052) | [Comfy-Org/vae-text-encorder-for-flux-klein-4b](https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b) (model file byte-identical to [black-forest-labs/FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)); [Qwen/Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B) | Apache-2.0, all three (**the 9B is non-commercial: never use**). bf16 only: fp8 doesn't run on MPS | Yes | 7.22 GB + 7.49 GB + 0.31 GB | `.../models/diffusion_models/`, `text_encoders/`, `vae/` | 2026-10-22 |
| DreamShaper XL Lightning SFW | Style `dreamshaper-lightning` (owner's option B) | [Lykon/dreamshaper-xl-lightning](https://huggingface.co/Lykon/dreamshaper-xl-lightning) | Card: OpenRAIL++; lineage undocumented (tags include `turbo`, `lcm`; SDXL-Turbo derivatives fall under Stability's revenue-capped community license) | **UNCLEAR: never the default, not for published films until resolved** | 6.9 GB | `.../models/checkpoints/` | 2026-10-19 |
| Animagine XL 4.0 Opt | Style `animagine` (owner's option C, anime look) | [cagliostrolab/animagine-xl-4.0](https://huggingface.co/cagliostrolab/animagine-xl-4.0) | CreativeML OpenRAIL++-M, unmodified (card: commercial use permitted). Note: trained on Danbooru images; can produce NSFW, so the `safe` tag and kid-safe negatives are always applied | Yes (with the OpenRAIL use restrictions) | 6.9 GB | `.../models/checkpoints/` | 2026-10-19 |
| CuteCartoonRedmond-V2 LoRA | Style `cutecartoon` (bonus look on SDXL Base) | [artificialguybr/CuteCartoonRedmond-V2](https://huggingface.co/artificialguybr/CuteCartoonRedmond-V2) | CreativeML OpenRAIL-M; training data undocumented | Yes | 171 MB | `.../models/loras/` | 2026-10-19 |

Styles (the switcher, D-025) combine these files; see `uv run scripts/fetch_models.py --list`.

**Considered and rejected:** DMD2 speed LoRA (CC-BY-NC), Flash-SDXL (CC-BY-NC-ND), Hyper-SD (license
now unclear), Depth Anything V2 Base/Large (CC-BY-NC), community checkpoints with no stated license
or NSFW galleries, and anything named after a real studio or living artist (D-013).

## Storage locations

- **Ollama models:** Ollama's own store (`~/.ollama/models`, see `ollama list`)
- **ComfyUI models** (checkpoints, LoRAs, VAE, SAM 2, depth): `~/ai-studio/comfyui/models/...`
- **Everything else** (TTS, music...): `~/ai-studio/models/<model-name>/`

## License quick reference

- **Apache-2.0 / MIT / BSD:** commercial use OK (keep notices).
- **OpenRAIL / CreativeML OpenRAIL++-M** (many SDXL models): commercial use generally allowed, with
  use-based restrictions. Read each one.
- **CC-BY-NC / "non-commercial" / research-only:** fine for learning, **not for published or monetized
  films**. Mark them clearly and keep them out of the default pipeline.
- **Custom licenses** (e.g. some Llama, Gemma or FLUX variants, the SAM 3 "SAM License"): read the
  terms and summarize them here.

## Sound-effect library (not models; data the studio uses)

CC0 only, a license per file in `~/ai-studio/sfx-library/manifest.json` (D-036, D-043, D-044).
Built by `scripts/fetch_sfx_library.py`.

| Source | License | Sounds | Notes |
|---|---|---|---|
| [Kenney](https://kenney.nl/assets/category:Audio): 8 packs (impact, interface, RPG, UI, jingles, digital, sci-fi, casino) | CC0 | 581 | Direct zips |
| [OpenGameArt](https://opengameart.org): 10 child-friendly packs | CC0 (checked per page) | 174 | 10 s crawl delay respected |
| [FSD50K](https://zenodo.org/records/4060432) eval split: Freesound clips | CC0 clips only (the dataset mixes CC0/BY/NC/Sampling+) | 3,513 | Labels for people's voices and bodies and for violence are excluded, as are clips with unsuitable words. Each clip's URL is its Freesound page |
| **Total** | | **4,268 (9.6 h)** | 6.0 GB with the kept originals (2.9 GB) |

Left out on purpose: BigSoundBank (its robots.txt forbids robots on its audio), Sonniss GDC
(not CC0; its license forbids AI training), BBC Sound Effects (non-commercial), bulk Freesound
(API terms).

## Motion-capture data (not a model; data the animation is retargeted from)

Fetched by `scripts/fetch_mocap.py` into `~/ai-studio/mocap/cmu/` (outside the repo, ~4 MB), turned
into small clips by `scripts/build_real_clips.py`. The derived clips (a few KB of joint angles
each) are committed under `studio_core/src/studio_core/motions/real_clips/`.

| Source | Terms (quoted from the site, checked 2026-10-30) | Trials used |
|---|---|---|
| [CMU Graphics Lab Motion Capture Database](https://mocap.cs.cmu.edu) (ASF skeleton + AMC motion, plain text) | Home page: "This dataset of motions is free for all uses." FAQ: "The motion capture data may be copied, modified, or redistributed without permission." No warranty. Not CC0 or an OSI licence: it is the lab's own permissive statement, so keep this note and the credit line. | 35_01 walk, 35_17 run/jog, 141_16 wave hello, 141_21 shrug, 13_39 jump (+ 13_27 point, fetched, not used yet) |

Credit line for the film's credits file: "Motion data from the CMU Graphics Lab Motion Capture
Database (mocap.cs.cmu.edu), created with funding from NSF EIA-0196217."

**Considered and not used:** 100STYLE (CC-BY 4.0, but ~gigabytes and style-labelled locomotion only),
AMASS and LAFAN1 (non-commercial / no-derivatives), Mixamo (Adobe terms, account needed), pose
estimation from video (MediaPipe is Apache-2.0, but there is no licence-clean clip of a person
walking, waving and jumping to run it on; see docs/spikes/real-motion.md).

## Character art (not a model; ready-made art the rig is built from)

| Asset | Source | License | Commercial use | Size | Location | Date |
|---|---|---|---|---|---|---|
| Kenney "Toon Characters 1": 6 characters (girl, boy, zombie, man, woman, robot), 45 poses each, separate parts (head with expression variants, back views, arm, hand, leg, bent leg, body), SVG source | [OpenGameArt](https://opengameart.org/content/toon-characters-1) (zip `kenney_toonCharacters1.zip`), also kenney.nl | CC0 (`License.txt` in the zip; credit optional) | Yes | 5.5 MB zip, 6.9 MB unpacked | `~/ai-studio/assets/kenney-toon-characters-1/src/` | 2026-10-31 |

Chosen after the owner rejected Mia (D-100). Raster parts are small, so rebuild at full size from the SVG sources.
