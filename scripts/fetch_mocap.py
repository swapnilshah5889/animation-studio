"""Fetch the few CMU motion-capture trials the real-motion clips are built from (mocap spike).

    uv run scripts/fetch_mocap.py            # downloads ~10 small text files, skips what exists

Source: Carnegie Mellon University Motion Capture Database, https://mocap.cs.cmu.edu
Terms (their home page): "This dataset of motions is free for all uses." Their FAQ adds that it can
go into commercial software but must not be resold as data. We keep the raw files outside the repo
(`~/ai-studio/mocap/cmu/`) and commit only the small derived clips (see docs/MODELS.md).
The files are plain text (ASF skeleton + AMC motion); we only ever parse them, never run them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = "https://mocap.cs.cmu.edu/subjects"
DEST = Path.home() / "ai-studio" / "mocap" / "cmu"

# trial id → what we use it for (descriptions are CMU's own)
TRIALS = {
    "35_01": "walk",
    "35_17": "run/jog",
    "141_16": "wave hello",
    "141_21": "shrug",
    "13_39": "jump",
    "13_27": "direct traffic, wave, point",
}


def fetch(url: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # curl, not urllib: the uv-managed Python has no CA bundle, and we never skip verification
    subprocess.run(["curl", "-fsS", "--max-time", "60", "-o", str(path), url], check=True)
    print(f"  {path.name}: {path.stat().st_size / 1024:.0f} KB")


def main() -> int:
    subjects = sorted({t.split("_")[0] for t in TRIALS})
    for subject in subjects:
        fetch(f"{BASE}/{subject}/{subject}.asf", DEST / f"{subject}.asf")
    for trial in TRIALS:
        subject = trial.split("_")[0]
        fetch(f"{BASE}/{subject}/{trial}.amc", DEST / f"{trial}.amc")
    print(f"mocap files in {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
