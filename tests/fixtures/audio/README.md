# Audio fixtures (Step 0)

- `pip_line_01.wav`: Kokoro-82M, voice `af_heart`, 24 kHz mono, 5.6 s. Text in `pip_line_01.txt`.
- `pip_line_01.rhubarb.json`: Rhubarb Lip Sync 1.14.0 mouth cues for it (`-f json --dialogFile`).
  Shapes A–H and X, the set the procedural mouth uses (D-007).

Regenerate: `envs/kokoro/.venv/bin/python scripts/audio/kokoro_say.py --out-dir OUT "<text>"`, then
`~/ai-studio/tools/rhubarb/rhubarb -f json --dialogFile pip_line_01.txt -o OUT.json OUT/line_01.wav`.
