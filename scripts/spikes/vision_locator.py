"""Spike: can a local vision model (qwen3-vl:8b-instruct via Ollama) find a cast character's face
parts and joints on a sheet crop, accurately enough to seed the cut's pixel rules?

Per character and view (front = left half of the 1344x768 sheet, three-quarter = right half) it
asks for eye centres, nose or beak tip, mouth centre and the six joint pairs, twice for each of two
prompts: "plain", and "som" (Set-of-Mark: the skeleton's expected positions are drawn as numbered
dots and the model is asked where each part really is). Answers are compared with ground truth
taken from the cut itself, not hand-labelled: the skeleton after `fit_limbs` on the cut's own
silhouette mask, the nose from build/report.json and the eyes and mouth from rig.json's face block.
Distances are divided by the head height so they compare across characters.

Run (Ollama must be up; other models are unloaded first):
    cd studio_core && uv run --no-sync python ../scripts/spikes/vision_locator.py [--only robot]
Writes films/step4-cast/spikes/vision_locator/{results.json,<id>_<view>_<prompt>.png}.
Qwen3-VL answers on a 0..1000 grid relative to the image (not pixels); the script converts.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from studio_core.comfy_runs import free_comfy
from studio_core.ollama import Ollama
from studio_core.puppet.fit import fit_limbs
from studio_core.puppet.locate import (  # the prompts and calls live with the build stage
    HALF,
    KEYS,
    MODEL,
    PARTS,
    PLAIN,
    SOM,
    VIEWS,
    ask_json,
    near_figure,
    som_image,
    to_px,
)
from studio_core.puppet.skeleton import turnaround

ROOT = Path(__file__).resolve().parents[2]
CAST = ROOT / "films" / "step4-cast" / "characters"
OUT = ROOT / "films" / "step4-cast" / "spikes" / "vision_locator"
IDS = ("kit", "bo", "bird", "child", "robot")


def ground_truth(cid: str, view: str) -> tuple[dict[str, tuple[float, float]], float, np.ndarray]:
    """Ground-truth points in crop pixels, the head height, and the figure mask (crop)."""
    char = CAST / cid
    x0 = 0 if view == "front" else HALF
    mask = np.asarray(Image.open(char / "build" / "segment" / f"mask_{view}.png")) > 0
    if mask.ndim == 3:
        mask = mask[..., 0]
    sk = turnaround((1344, 768))[VIEWS.index(view)]
    fitted, _ = fit_limbs(mask, sk)
    truth: dict[str, tuple[float, float]] = {}
    for key, joint in PARTS.items():
        if joint in fitted.joints and joint != "mouth":
            truth[key] = fitted.joints[joint]
    report = json.loads((char / "build" / "report.json").read_text())["views"][view]["face"]
    rig = json.loads((char / "rig.json").read_text())["views"][view]
    if report.get("nose_found"):
        truth["nose_or_beak_tip"] = tuple(report["nose_px"])
    else:
        truth.pop("nose_or_beak_tip", None)  # the skeleton's nose is a guess, not a measurement
    # eyes and mouth are in head-part pixels; the head's pivot is the neck
    face, head = rig["face"], rig["parts"]["head"]
    nx, ny = fitted.joints["neck"]
    px, py = head["pivot_px"]

    def sheet(p: list[float]) -> tuple[float, float]:
        return (nx + p[0] - px, ny + p[1] - py)

    truth["left_eye"] = sheet(face["eyes"]["left_px"])
    truth["right_eye"] = sheet(face["eyes"]["right_px"])
    truth["mouth_centre"] = sheet(face["mouth"]["at_px"])
    truth = {k: (x - x0, y) for k, (x, y) in truth.items()}
    # a view whose eye was inferred (one eye drawn) keeps both: the inferred one is the cut's guess
    return (
        truth,
        float(fitted.joints["neck"][1] - fitted.joints["head_top"][1]),
        mask[:, x0 : x0 + HALF],
    )


class MemSampler:
    """Peak resident memory of all ollama processes, sampled while a call runs."""

    def __init__(self) -> None:
        self.peak_kb = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            out = subprocess.run(["ps", "-axo", "rss=,comm="], capture_output=True, text=True)
            kb = sum(int(r.split(None, 1)[0]) for r in out.stdout.splitlines() if "ollama" in r)
            self.peak_kb = max(self.peak_kb, kb)
            self._stop.wait(0.5)

    def __enter__(self) -> MemSampler:
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._t.join()


def annotate(crop: Image.Image, truth, pred, path: Path) -> None:
    img = crop.copy()
    d = ImageDraw.Draw(img)
    for p in truth.values():
        d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], outline=(0, 160, 0), width=2)
    for k, p in pred.items():
        if p:
            d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=(230, 0, 0))
            d.text((p[0] + 6, p[1] - 5), "".join(w[0] for w in k.split("_")), fill=(200, 0, 0))
    img.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=list(IDS))
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--summarize", action="store_true", help="print tables from results.json")
    args = ap.parse_args()
    if args.summarize:
        summarize()
        return
    OUT.mkdir(parents=True, exist_ok=True)

    client = Ollama()
    for m in client.loaded():  # one large model in memory at a time
        client.unload(m["name"])
    print("comfy freed:", free_comfy())
    t = time.perf_counter()
    print(f"model load {client.load(MODEL, '10m'):.1f}s")
    results = []
    for cid in args.only:
        sheet = Image.open(
            CAST / cid / "design" / _candidate(cid) / "three_quarter" / "sheet.png"
        ).convert("RGB")
        for view in VIEWS:
            x0 = 0 if view == "front" else HALF
            crop = sheet.crop((x0, 0, x0 + HALF, 768))
            truth, head_h, mask = ground_truth(cid, view)
            som_img, legend = som_image(crop, view)
            for variant, img, prompt in (
                ("plain", crop, PLAIN),
                ("som", som_img, SOM.format(legend=legend)),
            ):
                runs = []
                for _ in range(args.runs):
                    with MemSampler() as mem:
                        ans, secs, raw = ask_json(client, img, prompt)
                    runs.append(
                        {"pred": to_px(ans, crop.size), "secs": secs, "mem_gb": mem.peak_kb / 1e6}
                    )
                    if ans is None:
                        runs[-1]["raw"] = raw[:300]
                pred = runs[0]["pred"]
                if variant == "plain" or cid == "robot":
                    annotate(crop, truth, pred, OUT / f"{cid}_{view}_{variant}.png")
                results.append(
                    {
                        "id": cid,
                        "view": view,
                        "variant": variant,
                        "head_h": head_h,
                        "truth": truth,
                        "runs": runs,
                        "outside": {
                            k: bool(p is None or not near_figure(mask, p)) for k, p in pred.items()
                        },
                        "err": {
                            k: (
                                math.dist(pred[k], truth[k]) / head_h
                                if pred[k] and k in truth
                                else None
                            )
                            for k in KEYS
                        },
                    }
                )
                print(cid, view, variant, f"{runs[0]['secs']:.1f}s", f"{runs[0]['mem_gb']:.1f}GB")
                (OUT / "results.json").write_text(json.dumps(results, indent=1, default=float))
    print(f"total {time.perf_counter() - t:.0f}s")
    client.unload(MODEL)


GROUPS = {
    "eyes": ("left_eye", "right_eye"),
    "nose": ("nose_or_beak_tip",),
    "mouth": ("mouth_centre",),
    "shoulders": ("left_shoulder", "right_shoulder"),
    "elbows": ("left_elbow", "right_elbow"),
    "wrists": ("left_wrist", "right_wrist"),
    "hips": ("left_hip", "right_hip"),
    "knees": ("left_knee", "right_knee"),
    "ankles": ("left_ankle", "right_ankle"),
}


def side_agnostic(r: dict, run: int = 0) -> tuple[dict[str, float | None], int, int]:
    """Errors with each left/right pair matched to its nearest truth (the model often takes
    "left" as the image's left, not the character's). Returns the errors, the pairs it swapped
    and the pairs it could judge."""
    pred, truth, err = r["runs"][run]["pred"], r["truth"], {}
    swapped = pairs = 0
    for key in ("nose_or_beak_tip", "mouth_centre"):
        ok = pred[key] and key in truth
        err[key] = math.dist(pred[key], truth[key]) / r["head_h"] if ok else None
    for lk in [k for k in KEYS if k.startswith("left_")]:
        rk = "right_" + lk[5:]
        ok = all(pred[k] and k in truth for k in (lk, rk))
        if not ok:
            err[lk] = err[rk] = None
            continue
        d = math.dist
        straight = d(pred[lk], truth[lk]) + d(pred[rk], truth[rk])
        crossed = d(pred[lk], truth[rk]) + d(pred[rk], truth[lk])
        pairs += 1
        if crossed < straight:
            swapped += 1
            err[lk], err[rk] = (
                d(pred[lk], truth[rk]) / r["head_h"],
                d(pred[rk], truth[lk]) / r["head_h"],
            )
        else:
            err[lk], err[rk] = (
                d(pred[lk], truth[lk]) / r["head_h"],
                d(pred[rk], truth[rk]) / r["head_h"],
            )
    return err, swapped, pairs


def summarize() -> None:
    """Median error (in head heights) per part group, failure rate, time, memory, stability.
    Errors are side-agnostic (see `side_agnostic`); the swap rate is printed per variant."""
    res = json.loads((OUT / "results.json").read_text())
    for r in res:
        r["err"], r["swapped"], r["pairs"] = side_agnostic(r)
    for who, ids in (("passing cast (kit bo bird child)", IDS[:4]), ("robot", ("robot",))):
        print(f"\n### {who}: median error / head height (n points)")
        print("| part | " + " | ".join(("plain", "som")) + " |")
        print("|---|---|---|")
        for g, keys in GROUPS.items():
            cells = []
            for variant in ("plain", "som"):
                e = [
                    r["err"][k]
                    for r in res
                    if r["id"] in ids and r["variant"] == variant
                    for k in keys
                    if r["err"][k] is not None
                ]
                cells.append(f"{np.median(e):.2f} ({len(e)})" if e else "-")
            print(f"| {g} | " + " | ".join(cells) + " |")
    print("\n### failure, time, memory, stability per variant")
    for variant in ("plain", "som"):
        rs = [r for r in res if r["variant"] == variant]
        asked = len(rs) * len(KEYS)
        none = sum(p is None for r in rs for p in r["runs"][0]["pred"].values())
        out = sum(v for r in rs for v in r["outside"].values()) - none
        secs = [run["secs"] for r in rs for run in r["runs"]]
        mem = max(run["mem_gb"] for r in rs for run in r["runs"])
        moved = [
            math.dist(a, b) / r["head_h"]
            for r in rs
            if len(r["runs"]) > 1
            for k in KEYS
            if (a := r["runs"][0]["pred"][k]) and (b := r["runs"][1]["pred"][k])
        ]
        within = [e for r in rs for e in r["err"].values() if e is not None]
        print(
            f"{variant}: points {asked}, no answer {none}, outside figure {out}, "
            f"median {np.median(secs):.1f}s/image, peak ollama RSS {mem:.1f} GB, "
            f"run1 vs run2 moved: median {np.median(moved):.3f}, "
            f"max {max(moved):.3f} head heights; "
            f"within 0.15 head height of truth: {np.mean([e <= 0.15 for e in within]):.0%}; "
            f"left/right swapped in {sum(r['swapped'] for r in rs)} of "
            f"{sum(r['pairs'] for r in rs)} pairs"
        )


def _candidate(cid: str) -> str:
    rep = json.loads((CAST / cid / "build" / "report.json").read_text())
    return rep["candidate"]


if __name__ == "__main__":
    main()
