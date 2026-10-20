"""Environment check for Animation Studio.

Checks every tool, app, service, Python environment and model the pipeline needs, using the
paths in config/studio.toml, and prints one line per check:

    OK       installed and working
    MISSING  not installed / not found
    FAIL     installed but broken (command errors, import fails, wrong architecture...)
    OFF      service installed but not running (start it, then re-run)
    DEFER    missing on purpose, by an owner decision listed in [doctor] deferred
             (an on-demand service from [doctor] on_demand that is not running is also fine)

Run from the repo root:

    uv run scripts/doctor.py              # human-readable report
    uv run scripts/doctor.py --json       # machine-readable, for scripts and (later) the director
    uv run scripts/doctor.py --config path/to/studio.toml

Exit code is 0 only when every check is OK or DEFER. Safe to run any time: it only reads and probes.
Standard library only, so it works before any project dependency is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "studio.toml"
EXAMPLE_CONFIG = REPO_ROOT / "config" / "studio.example.toml"
MODELS_MANIFEST = REPO_ROOT / "config" / "models.toml"

OK, MISSING, FAIL, OFF, DEFER = "OK", "MISSING", "FAIL", "OFF", "DEFER"
GREEN = {OK, DEFER}
COLORS = {OK: "\033[32m", MISSING: "\033[31m", FAIL: "\033[31m", OFF: "\033[33m", DEFER: "\033[36m"}
RESET = "\033[0m"
VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


@dataclass
class Result:
    section: str
    name: str
    status: str
    version: str = ""
    detail: str = ""


# --------------------------------------------------------------------------- helpers


def expand(path: str) -> Path:
    """Expand ~ and resolve relative paths against the repo root."""
    p = Path(os.path.expanduser(path))
    return p if p.is_absolute() else REPO_ROOT / p


def run(cmd: list[str], timeout: float = 30, cwd: Path | None = None) -> tuple[int, str]:
    """Run a command, return (exit code, combined stdout+stderr). Never raises."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except FileNotFoundError:
        return 127, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:.0f}s"
    except OSError as exc:  # e.g. exec format error, Gatekeeper kill
        return 126, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def first_version(text: str) -> str:
    match = VERSION_RE.search(text)
    return match.group(1) if match else ""


def http_get(url: str, timeout: float = 3) -> tuple[int, str]:
    """GET a URL, return (HTTP status, body). Status 0 means unreachable."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return 0, ""


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def binary_archs(path: Path) -> str:
    """Architectures in a Mach-O binary, e.g. 'arm64' or 'x86_64 arm64'."""
    code, out = run(["lipo", "-archs", str(path)])
    return out if code == 0 else ""


# --------------------------------------------------------------------------- checks


def check_system(cfg: dict[str, Any]) -> list[Result]:
    results = []
    mac_ver = platform.mac_ver()[0] or platform.platform()
    results.append(Result("system", "os", OK, mac_ver, platform.machine()))

    py = sys.version_info
    py_ok = (py.major, py.minor) == (3, 12)
    results.append(
        Result(
            "system",
            "python (doctor)",
            OK if py_ok else FAIL,
            platform.python_version(),
            sys.executable if py_ok else "expected 3.12 via uv (see DECISIONS D-009)",
        )
    )

    code, out = run(["sysctl", "-n", "hw.memsize"])
    if code == 0:
        results.append(Result("system", "memory", OK, human_size(int(out)), "unified"))

    root = expand(cfg["paths"]["studio_root"])
    if root.is_dir():
        free = shutil.disk_usage(root).free
        status = OK if free > 50 * 1024**3 else FAIL
        results.append(
            Result("system", "studio_root", status, f"{human_size(free)} free", str(root))
        )
    else:
        results.append(Result("system", "studio_root", MISSING, "", str(root)))

    # Rosetta 2 is only needed for x86_64-only tools; informational.
    code, _ = run(["pgrep", "-q", "oahd"])
    results.append(Result("system", "rosetta 2", OK, "installed" if code == 0 else "not installed"))
    return results


# Tool name -> extra args that print the version.
VERSION_ARGS = {
    "ffmpeg": ["-version"],
    "ffprobe": ["-version"],
    "synfig": ["--version"],
    "melt": ["-version"],
    "rhubarb": ["--version"],
    "docker": ["--version"],
    "ollama": ["--version"],
}


# Exit codes that still mean success. Quirk: `synfig --version` prints the version, then exits 3.
VERSION_OK_CODES = {"synfig": {0, 3}}


def check_tools(cfg: dict[str, Any]) -> list[Result]:
    results = []
    uv = shutil.which("uv")
    if uv:
        code, out = run([uv, "--version"])
        results.append(Result("tools", "uv", OK if code == 0 else FAIL, first_version(out), uv))
    else:
        results.append(Result("tools", "uv", MISSING))

    for name, raw_path in cfg["tools"].items():
        path = expand(raw_path)
        if not path.exists():
            results.append(Result("tools", name, MISSING, "", str(path)))
            continue
        code, out = run([str(path), *VERSION_ARGS.get(name, ["--version"])])
        detail = str(path)
        archs = binary_archs(path.resolve())
        if archs and "arm64" not in archs:
            detail += f" [{archs}, runs under Rosetta]"
        status = OK if code in VERSION_OK_CODES.get(name, {0}) else FAIL
        if status == FAIL:
            detail += f" -> {out.splitlines()[-1] if out else f'exit {code}'}"
        results.append(Result("tools", name, status, first_version(out), detail))
    return results


def check_apps(cfg: dict[str, Any]) -> list[Result]:
    results = []
    for name, raw_path in cfg["apps"].items():
        app = expand(raw_path)
        plist = app / "Contents" / "Info.plist"
        if not plist.exists():
            results.append(Result("apps", name, MISSING, "", str(app)))
            continue
        with plist.open("rb") as fh:
            info = plistlib.load(fh)
        version = str(info.get("CFBundleShortVersionString", ""))
        # Gatekeeper assessment is read-only: it never changes security settings.
        code, _ = run(["spctl", "--assess", "--type", "execute", str(app)])
        gatekeeper = "gatekeeper ok" if code == 0 else "gatekeeper: needs owner approval"
        results.append(Result("apps", name, OK, version, f"{app} ({gatekeeper})"))
    return results


def check_services(cfg: dict[str, Any]) -> list[Result]:
    svc = cfg["services"]
    results = []

    status, body = http_get(f"{svc['ollama_url']}/api/version")
    if status == 200:
        results.append(
            Result("services", "ollama", OK, json.loads(body).get("version", ""), svc["ollama_url"])
        )
    else:
        results.append(
            Result("services", "ollama", OFF, "", f"{svc['ollama_url']} (start: ollama serve)")
        )

    docker = expand(cfg["tools"]["docker"])
    code, out = run([str(docker), "info", "--format", "{{.ServerVersion}}"], timeout=15)
    if code == 0:
        results.append(Result("services", "docker daemon", OK, out.strip()))
    else:
        results.append(Result("services", "docker daemon", OFF, "", "start Docker Desktop"))

    status, body = http_get(f"{svc['qdrant_url']}/readyz")
    if status == 200:
        _, root = http_get(svc["qdrant_url"])
        version = json.loads(root).get("version", "") if root.startswith("{") else ""
        results.append(Result("services", "qdrant", OK, version, svc["qdrant_url"]))
    else:
        hint = "docker compose -f infra/docker-compose.yml up -d"
        results.append(
            Result("services", "qdrant", OFF, "", f"{svc['qdrant_url']} (start: {hint})")
        )

    status, body = http_get(f"{svc['comfyui_url']}/system_stats")
    if status == 200:
        stats = json.loads(body).get("system", {})
        results.append(
            Result("services", "comfyui", OK, stats.get("comfyui_version", ""), svc["comfyui_url"])
        )
    else:
        hint = "scripts/comfy_server.sh"
        results.append(
            Result("services", "comfyui", OFF, "", f"{svc['comfyui_url']} (start: {hint})")
        )
    return results


def check_ollama_models(cfg: dict[str, Any]) -> list[Result]:
    wanted = [*cfg["ollama"]["director_models"], cfg["ollama"]["vision_model"]]
    status, body = http_get(f"{cfg['services']['ollama_url']}/api/tags")
    if status != 200:
        return [Result("ollama models", m, OFF, "", "ollama not reachable") for m in wanted]
    installed = {m["name"]: m for m in json.loads(body).get("models", [])}
    results = []
    for model in wanted:
        tag = model if ":" in model else f"{model}:latest"
        if tag in installed:
            info = installed[tag]
            quant = info.get("details", {}).get("quantization_level", "")
            results.append(
                Result("ollama models", model, OK, human_size(info.get("size", 0)), quant)
            )
        else:
            results.append(Result("ollama models", model, MISSING, "", f"ollama pull {model}"))
    return results


def check_python_env(
    section: str, name: str, python: Path, module: str, cwd: Path | None = None
) -> Result:
    if not python.exists():
        return Result(section, name, MISSING, "", str(python))
    # Prefer the module's __version__, else the installed distribution's version.
    probe = (
        "import importlib, importlib.metadata as md, platform\n"
        f"m = importlib.import_module({module!r})\n"
        f"dist = (md.packages_distributions().get({module!r}) or [{module!r}])[0]\n"
        "v = getattr(m, '__version__', None)\n"
        "if v is None:\n"
        "    try: v = md.version(dist)\n"
        "    except md.PackageNotFoundError: v = '?'\n"
        "print('DOCTOR', platform.python_version(), v)"
    )
    code, out = run([str(python), "-c", probe], timeout=120, cwd=cwd)
    if code != 0:
        last = out.splitlines()[-1] if out else f"exit {code}"
        return Result(section, name, FAIL, "", f"import {module} failed: {last}")
    # Libraries print warnings on import; only trust our own tagged line.
    line = next((ln for ln in reversed(out.splitlines()) if ln.startswith("DOCTOR ")), "")
    if not line:
        return Result(section, name, FAIL, "", f"no version line from {python}")
    _, py_version, mod_version = line.split(" ", 2)
    status = OK if py_version.startswith("3.12.") else FAIL
    return Result(section, name, status, mod_version, f"{module} on python {py_version}")


def check_envs(cfg: dict[str, Any]) -> list[Result]:
    return [
        check_python_env(
            "python envs",
            name,
            expand(env["python"]),
            env["import"],
            expand(env["cwd"]) if "cwd" in env else None,
        )
        for name, env in cfg.get("envs", {}).items()
    ]


def check_comfyui(cfg: dict[str, Any]) -> list[Result]:
    comfy = cfg["comfyui"]
    root = expand(comfy["root"])
    results = []
    if not (root / "main.py").exists():
        return [Result("comfyui", "checkout", MISSING, "", str(root))]
    code, out = run(["git", "-C", str(root), "describe", "--tags", "--always"])
    results.append(Result("comfyui", "checkout", OK, out if code == 0 else "", str(root)))

    python = expand(comfy["python"])
    if not python.exists():
        results.append(Result("comfyui", "torch + mps", MISSING, "", str(python)))
    else:
        probe = "import torch; print(torch.__version__, torch.backends.mps.is_available())"
        code, out = run([str(python), "-c", probe], timeout=120)
        if code == 0:
            version, mps = out.splitlines()[-1].split()
            status = OK if mps == "True" else FAIL
            results.append(Result("comfyui", "torch + mps", status, version, f"mps={mps}"))
        else:
            results.append(Result("comfyui", "torch + mps", FAIL, "", out.splitlines()[-1]))

    for node in comfy.get("custom_nodes", []):
        node_dir = root / "custom_nodes" / node
        status = OK if node_dir.is_dir() else MISSING
        results.append(Result("comfyui", f"node: {node}", status, "", str(node_dir)))

    # Model files come from config/models.toml: the default image preset + required files.
    with MODELS_MANIFEST.open("rb") as fh:
        manifest = tomllib.load(fh)
    files, presets = manifest["files"], manifest["image_models"]
    models_dir = expand(comfy["models_dir"])
    default = comfy.get("default_image_model", "")
    wanted: list[tuple[str, str]] = []  # (label, file id)
    if default in presets:
        preset = presets[default]
        wanted.append((f"{default}: checkpoint", preset["checkpoint"]))
        if preset.get("vae"):
            wanted.append((f"{default}: vae", preset["vae"]))
        wanted += [(f"{default}: lora", lora["file"]) for lora in preset.get("loras", [])]
        if preset.get("fast", {}).get("lora"):
            wanted.append((f"{default}: speed lora", preset["fast"]["lora"]))
    else:
        results.append(Result("comfyui", "default image model", FAIL, "", f"unknown: {default!r}"))
    wanted += [("required", file_id) for file_id in comfy.get("required_files", [])]
    for label, file_id in wanted:
        entry = files[file_id]
        path = models_dir / entry["dest"]
        name = f"{file_id}"
        if path.is_file() and path.stat().st_size == entry["size"]:
            detail = f"{label}, commercial={entry['commercial']}"
            results.append(Result("comfyui", name, OK, human_size(entry["size"]), detail))
        elif path.exists():
            results.append(Result("comfyui", name, FAIL, "", f"wrong size: {path}"))
        else:
            hint = f"uv run scripts/fetch_models.py {file_id}"
            results.append(Result("comfyui", name, MISSING, "", f"{label} ({hint})"))
    return results


def check_models(cfg: dict[str, Any]) -> list[Result]:
    """Weights outside ComfyUI and Ollama: [models] name = path (file or directory)."""
    results = []
    for name, raw_path in cfg.get("models", {}).items():
        path = expand(raw_path)
        if path.exists() and path_size(path) > 0:
            results.append(Result("models", name, OK, human_size(path_size(path)), str(path)))
        else:
            results.append(Result("models", name, MISSING, "", str(path)))
    return results


CHECKS: list[Callable[[dict[str, Any]], list[Result]]] = [
    check_system,
    check_tools,
    check_apps,
    check_services,
    check_ollama_models,
    check_comfyui,
    check_envs,
    check_models,
]


# --------------------------------------------------------------------------- main


def load_config(path: Path) -> tuple[dict[str, Any], Path]:
    if not path.exists() and path == DEFAULT_CONFIG:
        path = EXAMPLE_CONFIG
    with path.open("rb") as fh:
        return tomllib.load(fh), path


def print_report(results: list[Result], config_path: Path) -> None:
    color = sys.stdout.isatty()
    print(f"Animation Studio doctor  (config: {config_path.relative_to(REPO_ROOT)})")
    section = None
    for r in results:
        if r.section != section:
            section = r.section
            print(f"\n{section}")
        tag = f"{r.status:<7}"
        if color:
            tag = f"{COLORS[r.status]}{tag}{RESET}"
        print(f"  {tag}  {r.name:<28} {r.version:<14} {r.detail}")
    counts = {s: sum(r.status == s for r in results) for s in (OK, DEFER, MISSING, FAIL, OFF)}
    summary = ", ".join(f"{n} {s}" for s, n in counts.items() if n)
    verdict = "ALL GREEN" if all(r.status in GREEN for r in results) else "NOT GREEN"
    print(f"\n{verdict}: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    args = parser.parse_args()

    cfg, config_path = load_config(args.config.resolve())
    results = [r for check in CHECKS for r in check(cfg)]
    deferred = cfg.get("doctor", {}).get("deferred", {})
    on_demand = cfg.get("doctor", {}).get("on_demand", [])
    for r in results:
        if r.name in deferred and r.status == MISSING:
            r.status, r.detail = DEFER, f"{deferred[r.name]} [{r.detail}]"
        elif r.section == "services" and r.name in on_demand and r.status == OFF:
            r.status, r.detail = DEFER, f"on demand, not running: {r.detail}"

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        if config_path == EXAMPLE_CONFIG:
            print("note: config/studio.toml not found, using studio.example.toml\n")
        print_report(results, config_path)
    return 0 if all(r.status in GREEN for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
