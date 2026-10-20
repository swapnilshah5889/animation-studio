# Model licenses, and what they mean for publishing films

Code licenses and model licenses are different animals. This note explains the families we meet,
and the rule we follow (D-012): **check the license before downloading, record it in
[`../MODELS.md`](../MODELS.md), prefer permissive, flag non-commercial.**

> Not legal advice. When a film is about to be monetized, re-read the actual license texts.

## The families

| Family | Examples here | Commercial use | Strings attached |
|---|---|---|---|
| **Apache-2.0** | Qwen3, gpt-oss, Kokoro-82M, SAM 2, Depth Anything V2 *Small*, ACE-Step | Yes | Keep the license and NOTICE files; patent grant included. |
| **MIT / BSD** | Rhubarb, vtracer, Chatterbox, sdxl-vae-fp16-fix | Yes | Keep the copyright notice. |
| **OpenRAIL (CreativeML OpenRAIL-M / OpenRAIL++-M)** | SDXL 1.0, SDXL-Lightning, many SDXL fine-tunes and LoRAs | Yes | **Use-based restrictions**: a list of forbidden uses (harming minors, disinformation, harassment, impersonation...). They pass downstream: anyone you give the model to must accept them too. Outputs belong to you. |
| **Custom "community" licenses** | Stability Community License (SDXL-Turbo, SD3.5), Llama, Gemma, FLUX.1-dev | Depends | Read each: revenue caps (e.g. free under US$1M/year), attribution, acceptable-use policies, or "non-commercial" outright. |
| **Non-commercial (CC-BY-NC, research-only)** | DMD2 speed LoRA, Depth Anything V2 *Base/Large*, Flash-SDXL | **No** | Fine for learning and experiments. **Never in the default pipeline for a published film.** |
| **No license stated** | Many community LoRAs/checkpoints | **Assume no** | No license means all rights reserved. Skip. |

## Things that trip people up

- **Size variants can have different licenses.** Depth Anything V2 Small is Apache-2.0; Base and
  Large are CC-BY-NC-4.0. Always check the exact file, not the project name.
- **Derivatives inherit restrictions.** A fine-tuned checkpoint or a merge of several models is
  bound by the most restrictive license in its lineage. A "mix" with an undocumented recipe has an
  unknowable license; that is why we prefer models with a clear chain.
- **Mirrors relabel.** Re-uploads on Hugging Face sometimes show a different (more permissive)
  license than the original. Trust the original author's card.
- **Model weights vs. code.** ComfyUI is GPL-3 (code); the SDXL weights it loads are OpenRAIL++.
  Wrapping GPL apps through files, CLIs and HTTP keeps our code separate (see ARCHITECTURE).
- **Outputs.** Most permissive and OpenRAIL licenses claim no rights over generated images or
  audio. Some music/voice models restrict how outputs may be used. Check the output clause, not
  just the weights clause.
- **Voices and likeness.** Even with a permissive TTS model, cloning a real person's voice raises
  separate consent and right-of-publicity issues. We only use the models' built-in synthetic
  voices.
- **Children's content.** OpenRAIL's use restrictions explicitly forbid content that exploits or
  harms minors. Our own policy (D-013) is stricter anyway: age-appropriate only, checked by
  `qa_mcp`, and no real studio or living-artist names in prompts or presets.

## How we record it

Every model gets a row in `MODELS.md`: source URL, license, **Commercial OK (yes / no / unclear)**,
size and location. "Unclear" counts as "no" until resolved.
