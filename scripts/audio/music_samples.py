"""Music samples page (Step 3 checkpoint 3): three moods, two takes each.

    uv run scripts/audio/music_samples.py     # → renders/music-samples/index.html (+ WAVs)

Every take is made by `compose` (studio_core.audio.music), exactly as a film gets it: the
caption written from the mood table, bf16, the memory guard, trimming, fades and loudness.
Two takes = two cue ids = two seeds. The page shows each take's caption, seed and measured peak
memory against the 14 GB budget. renders/ is git-ignored. Safe to re-run: takes are cached by
their request hash.
"""

from __future__ import annotations

import base64
import html
import sys
import time

from studio_core.audio import ffmpeg
from studio_core.audio.music import BUDGET_GB, compose
from studio_core.config import REPO_ROOT

OUT = REPO_ROOT / "renders" / "music-samples"
DURATION_S = 15.0
SAMPLES = [  # (mood, energy, what a shot would use it for)
    ("playful", 0.6, "Pip finds the kite"),
    ("calm", 0.3, "a quiet morning in the meadow"),
    ("adventurous", 0.7, "chasing the kite across the hills"),
]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Music Samples</title>
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
h2 {{ font-size:18px; margin:26px 0 4px; }}
p.lede, .use {{ color:var(--muted); }}
p.lede {{ margin:0 0 8px; max-width:72ch; }}
.take {{ border:1px solid var(--line); border-radius:10px; background:var(--card);
  padding:12px; margin:10px 0; }}
.code {{ font-weight:650; color:var(--accent); }}
.meta {{ color:var(--muted); font-size:13px; margin:4px 0 8px; }}
audio {{ width:100%; }}
</style></head>
<body><main>
<h1>Music samples</h1>
<p class="lede">Three moods, two takes each, {secs:g} s per take. Tell me which takes fit (by
code, e.g. "m1b, m2a") and what to change: the mood words, the instruments, the pace. Every take
went through the real pipeline: the caption is written by code from the mood, bf16, normalized
to -20 LUFS, faded out. Made {made}.</p>
{sections}
</main></body></html>
"""


def embedded(wav) -> str:
    m4a = wav.with_suffix(".m4a")
    ffmpeg.run(["-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(m4a)])
    data = base64.b64encode(m4a.read_bytes()).decode()
    m4a.unlink()
    return "data:audio/mp4;base64," + data


def main() -> int:
    t0 = time.monotonic()
    sections = []
    for n, (mood, energy, use) in enumerate(SAMPLES, 1):
        takes = []
        for take in "ab":
            code = f"m{n}{take}"
            cue = compose(OUT, f"sample_{code}", mood, DURATION_S, energy=energy)
            peak = "cached" if cue.peak_gb is None else f"peak {cue.peak_gb:.1f} GB"
            print(f"{code}: {mood}, seed {cue.seed}, {peak}", flush=True)
            takes.append(
                f'<div class="take"><span class="code">{code}</span>'
                f'<div class="meta">seed {cue.seed} · {peak} (budget {BUDGET_GB:g} GB) · '
                f"{html.escape(cue.caption)}</div>"
                f'<audio controls preload="none" src="{embedded(cue.wav)}"></audio></div>'
            )
        sections.append(
            f"<h2>{n}. {mood} (energy {energy})</h2>"
            f'<div class="use">For example: {html.escape(use)}</div>{"".join(takes)}'
        )
    page = PAGE.format(
        secs=DURATION_S, made=time.strftime("%Y-%m-%d"), sections="\n".join(sections)
    )
    (OUT / "index.html").write_text(page)
    size = (OUT / "index.html").stat().st_size / 1e6
    print(
        f"done in {time.monotonic() - t0:.0f} s → renders/music-samples/index.html ({size:.1f} MB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
