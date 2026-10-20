"""Download model weights listed in config/models.toml (idempotent, sha256-verified).

    uv run scripts/fetch_models.py --list                 # files and presets, with status
    uv run scripts/fetch_models.py sdxl-storybook         # a preset = all of its files
    uv run scripts/fetch_models.py sam2.1-hiera-small depth-anything-v2-small

Files already present with the right size are skipped. Each file is fetched as N parallel HTTP
range requests (default 8): on this network one connection to Hugging Face gets ~30-75 KB/s but
eight together get ~7x that, the same trick `ollama pull` uses. Every range resumes after an
interruption; the pieces are joined and the file is only moved into place after the sha256
matches. Ask the owner before any single download over ~20 GB (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from studio_core.config import load_config
from studio_core.models import Manifest, ModelFile, comfy_models_dir, load_manifest

GB = 1024**3
OWNER_LIMIT = 20 * GB


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_range(url: str, piece: Path, start: int, end: int, progress: list[int]) -> None:
    """Fetch bytes [start, end] into `piece`, appending; resumes from what is already there."""
    attempt = 0
    while True:
        have = piece.stat().st_size if piece.exists() else 0
        if start + have > end:
            return
        req = urllib.request.Request(url, headers={"Range": f"bytes={start + have}-{end}"})
        try:
            # urllib follows the redirect to the CDN and keeps the Range header.
            with urllib.request.urlopen(req, timeout=60) as resp, piece.open("ab") as fh:
                if resp.status != 206:
                    raise RuntimeError(f"server ignored the Range header (HTTP {resp.status})")
                while block := resp.read(1024 * 1024):
                    fh.write(block)
                    progress[0] += len(block)
            attempt = 0
        except (OSError, RuntimeError) as exc:
            attempt += 1
            if attempt > 20:
                raise RuntimeError(f"{piece.name}: giving up after 20 retries: {exc}") from exc
            time.sleep(min(60, 2**attempt))


def fetch(file: ModelFile, models_dir: Path, connections: int) -> str:
    target = file.path(models_dir)
    if file.is_present(models_dir):
        return "present"
    target.parent.mkdir(parents=True, exist_ok=True)
    work = target.with_name(target.name + ".parts")
    work.mkdir(exist_ok=True)
    n = max(1, min(connections, file.size // (8 * 1024 * 1024)))  # no tiny ranges
    bounds = [(i * file.size // n, (i + 1) * file.size // n - 1) for i in range(n)]
    pieces = [work / f"{i:02d}" for i in range(n)]

    progress = [sum(p.stat().st_size for p in pieces if p.exists())]
    start, start_bytes = time.perf_counter(), progress[0]
    done = threading.Event()

    def report() -> None:
        while not done.wait(30):
            pct = 100 * progress[0] / file.size
            rate = (progress[0] - start_bytes) / (time.perf_counter() - start) / 1e6
            print(f"  {file.id}: {pct:5.1f}%  {rate:.2f} MB/s", flush=True)

    threading.Thread(target=report, daemon=True).start()
    try:
        with ThreadPoolExecutor(n) as pool:
            jobs = [
                pool.submit(download_range, file.url, piece, a, b, progress)
                for piece, (a, b) in zip(pieces, bounds, strict=True)
            ]
            for job in jobs:
                job.result()
    finally:
        done.set()

    part = target.with_name(target.name + ".part")
    with part.open("wb") as out:
        for piece in pieces:
            with piece.open("rb") as fh:
                shutil.copyfileobj(fh, out, 8 * 1024 * 1024)
    if part.stat().st_size != file.size:
        raise RuntimeError(f"{file.id}: size {part.stat().st_size} != expected {file.size}")
    actual = sha256_of(part)
    if actual != file.sha256:
        part.unlink()
        shutil.rmtree(work)
        raise RuntimeError(f"{file.id}: sha256 mismatch ({actual}); partial files removed")
    part.rename(target)
    shutil.rmtree(work)
    elapsed = time.perf_counter() - start
    rate = (file.size - start_bytes) / elapsed / 1e6
    return f"downloaded {file.size / GB:.2f} GB in {elapsed:.0f}s ({rate:.2f} MB/s, {n} ranges)"


def show(manifest: Manifest, models_dir: Path, default: str) -> None:
    print(f"models_dir: {models_dir}\n\nfiles")
    for f in manifest.files.values():
        state = "present" if f.is_present(models_dir) else "-"
        size = f"{f.size / GB:6.2f} GB"
        print(f"  {state:<8} {f.id:<30} {size}  commercial={f.commercial:<8} {f.license}")
    print("\nimage-model presets (switcher)")
    for p in manifest.presets.values():
        ready = all(f.is_present(models_dir) for f in manifest.preset_files(p.id))
        mark = "*" if p.id == default else " "
        print(
            f" {mark}{'ready' if ready else '-':<7} {p.id:<30} "
            f"commercial={manifest.preset_commercial(p.id):<8} {p.label}"
        )
    print("\n* = default_image_model in config/studio.toml")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("ids", nargs="*", help="preset ids and/or file ids")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--connections", type=int, default=8, help="parallel ranges per file")
    args = parser.parse_args()

    cfg = load_config()
    manifest = load_manifest()
    models_dir = comfy_models_dir(cfg)
    if args.list or not args.ids:
        show(manifest, models_dir, cfg.get("comfyui", "default_image_model", ""))
        return 0

    files = manifest.expand(args.ids)
    todo = [f for f in files if not f.is_present(models_dir)]
    if any(f.size > OWNER_LIMIT for f in todo):
        sys.exit("A single file is over 20 GB: ask the owner first (CLAUDE.md).")
    for f in files:
        print(f"{f.id}: {fetch(f, models_dir, args.connections)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
