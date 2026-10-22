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
