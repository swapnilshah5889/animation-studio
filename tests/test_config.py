from pathlib import Path

from studio_core.config import REPO_ROOT, expand_path, load_config


def test_expand_path_home_and_relative() -> None:
    assert expand_path("~/ai-studio") == Path.home() / "ai-studio"
    assert expand_path("films") == REPO_ROOT / "films"
    assert expand_path("/opt/homebrew/bin/synfig") == Path("/opt/homebrew/bin/synfig")


def test_example_config_has_every_section() -> None:
    cfg = load_config(REPO_ROOT / "config" / "studio.example.toml")
    for section in ("paths", "tools", "apps", "services", "ollama", "comfyui", "envs"):
        assert section in cfg.data, section
    assert cfg.path("tools", "rhubarb").is_absolute()
