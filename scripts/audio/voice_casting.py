"""Voice casting page (Step 3 checkpoint 2): candidate voices saying the same two lines.

    uv run scripts/audio/voice_casting.py      # → renders/voice-casting/index.html (+ WAVs)

Every candidate goes through exactly the pipeline `speak` uses (studio_core.audio.voices:
Kokoro worker, trim, pitch step, speech loudness), so what the owner hears is what a film gets.
One worker call synthesizes everything. The page is self-contained (audio embedded as AAC), so
it can be opened anywhere. renders/ is git-ignored. Safe to re-run.

Candidates: the best-graded and youngest-sounding Kokoro voices (VOICES.md grades in the
labels), two blends, and child-like variants with a small pitch step and a slightly faster pace.
Kokoro has no child voices; the variants are how we approach one (D-036).
"""

from __future__ import annotations

import base64
import html
import shutil
import sys
import time

from studio_core.audio import ffmpeg
from studio_core.audio.voices import synthesize
from studio_core.config import REPO_ROOT

OUT = REPO_ROOT / "renders" / "voice-casting"
LINES = [
    "Hi Bunny! Look what I found in the tall grass. It's a red kite with a long yellow tail!",
    "Wow! Is that for me?",  # short on purpose: Kokoro is weaker on very short inputs
]


def v(*ids: tuple[str, float], speed: float = 1.0, pitch: float = 0.0) -> dict:
    return {
        "schema_version": 1,
        "character": "casting",
        "engine": "kokoro",
        "voices": [{"id": i, "weight": w} for i, w in ids],
        "speed": speed,
        "pitch_semitones": pitch,
        "loudness_lufs": -20,
    }


CANDIDATES = [  # (code, label, voice)
    ("c01", "af_heart (grade A, the flagship voice)", v(("af_heart", 1))),
    ("c02", "af_bella (A-)", v(("af_bella", 1))),
    ("c03", "af_nicole (B-, soft and close)", v(("af_nicole", 1))),
    ("c04", "af_sky (C-)", v(("af_sky", 1))),
    ("c05", "af_aoede (C+)", v(("af_aoede", 1))),
    ("c06", "af_kore (C+)", v(("af_kore", 1))),
    ("c07", "am_puck (C+, a young-sounding male voice)", v(("am_puck", 1))),
    ("c08", "am_michael (C+)", v(("am_michael", 1))),
    ("c09", "bf_emma (B-, British)", v(("bf_emma", 1))),
    ("c10", "blend: af_heart 50% + af_sky 50%", v(("af_heart", 0.5), ("af_sky", 0.5))),
    ("c11", "blend: af_bella 50% + af_nicole 50%", v(("af_bella", 0.5), ("af_nicole", 0.5))),
    (
        "c12",
        "child-like: af_heart, +2 semitones, 8% faster",
        v(("af_heart", 1), speed=1.08, pitch=2),
    ),
    (
        "c13",
        "child-like: af_bella, +1.5 semitones, 5% faster",
        v(("af_bella", 1), speed=1.05, pitch=1.5),
    ),
    ("c14", "child-like: am_puck, +2 semitones, 5% faster", v(("am_puck", 1), speed=1.05, pitch=2)),
]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voice Casting</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1b18; --muted:#6b665e; --line:#e4e0d8; --card:#ffffff;
  --accent:#2f6f5e; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#171614; --fg:#ece8e1; --muted:#a39d93; --line:#2c2a26; --card:#1f1d1a;
    --accent:#7cc4ad; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ max-width:980px; margin:0 auto; padding:28px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 6px; }}
p.lede {{ color:var(--muted); margin:0 0 20px; max-width:70ch; }}
.lines {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:0 0 18px; }}
.lines div {{ border:1px solid var(--line); border-radius:10px; padding:10px 12px;
  background:var(--card); }}
.lines b {{ color:var(--accent); }}
.row {{ display:grid; grid-template-columns:minmax(200px, 1.1fr) 1fr 1fr; gap:12px;
  align-items:center; padding:12px; border-bottom:1px solid var(--line); }}
.row:nth-child(even) {{ background:var(--card); }}
.code {{ font-weight:650; color:var(--accent); margin-right:6px; }}
.meta {{ color:var(--muted); font-size:13px; }}
audio {{ width:100%; }}
@media (max-width:700px) {{ .row, .lines {{ grid-template-columns:1fr; }} }}
</style></head>
<body><main>
<h1>Voice casting</h1>
<p class="lede">Pick a voice for <b>Pip</b> and one for <b>Bunny</b> (by code, e.g. "Pip c12,
Bunny c03"), or describe what you'd change. Every take went through the same pipeline a film uses:
Kokoro, silence trim, pitch step, speech loudness -20 LUFS. Line 2 is short on purpose: Kokoro is
weaker on very short inputs. Made {made}.</p>
<div class="lines"><div><b>Line 1</b><br>{line1}</div><div><b>Line 2</b><br>{line2}</div></div>
{rows}
</main></body></html>
"""


def embedded(wav) -> str:
    m4a = wav.with_suffix(".m4a")
    ffmpeg.run(["-i", str(wav), "-c:a", "aac", "-b:a", "96k", str(m4a)])
    return "data:audio/mp4;base64," + base64.b64encode(m4a.read_bytes()).decode()


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    t0 = time.monotonic()
    items = [
        {"key": f"{code}_line{n}", "text": text, "voice": voice}
        for code, _, voice in CANDIDATES
        for n, text in enumerate(LINES, 1)
    ]
    wavs, models = synthesize(items, OUT)
    model = ", ".join(models.values())
    rows = []
    for code, label, _ in CANDIDATES:
        players = "".join(
            f'<audio controls preload="none" src="{embedded(wavs[f"{code}_line{n}"])}"></audio>'
            for n in range(1, len(LINES) + 1)
        )
        secs = ", ".join(f"{ffmpeg.duration(wavs[f'{code}_line{n}']):.1f} s" for n in (1, 2))
        rows.append(
            f'<div class="row"><div><span class="code">{code}</span>{html.escape(label)}'
            f'<div class="meta">{secs}</div></div>{players}</div>'
        )
    page = PAGE.format(
        made=f"with {html.escape(model)} on {time.strftime('%Y-%m-%d')}",
        line1=html.escape(LINES[0]),
        line2=html.escape(LINES[1]),
        rows="\n".join(rows),
    )
    (OUT / "index.html").write_text(page)
    for m4a in OUT.glob("*.m4a"):
        m4a.unlink()
    size = (OUT / "index.html").stat().st_size / 1e6
    print(
        f"{len(items)} takes in {time.monotonic() - t0:.0f} s → "
        f"{(OUT / 'index.html').relative_to(REPO_ROOT)} ({size:.1f} MB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
