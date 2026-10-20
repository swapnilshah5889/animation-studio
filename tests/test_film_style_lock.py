from pathlib import Path

import pytest

from studio_core.film import Film, StyleLockedError
from studio_core.models import load_manifest

MANIFEST = load_manifest()


def test_style_can_change_until_the_first_character(tmp_path: Path) -> None:
    film = Film.create(tmp_path / "kite-day", "storybook", MANIFEST)
    film.set_style("animagine", MANIFEST)  # no characters yet: allowed
    assert Film.load(film.root).style == "animagine"

    film.add_character("pip")
    assert film.style_locked
    film.set_style("animagine", MANIFEST)  # same style: fine
    with pytest.raises(StyleLockedError):
        film.set_style("storybook", MANIFEST)
    assert Film.load(film.root).style == "animagine"


def test_character_folder_also_locks_the_style(tmp_path: Path) -> None:
    film = Film.create(tmp_path / "f", "storybook", MANIFEST)
    (film.root / "characters" / "bunny").mkdir(parents=True)
    with pytest.raises(StyleLockedError):
        film.set_style("cutecartoon", MANIFEST)


def test_unknown_style_and_commercial_flag(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        Film.create(tmp_path / "a", "no-such-style", MANIFEST)
    film = Film.create(tmp_path / "b", "dreamshaper-lightning", MANIFEST)
    assert film.data["style_commercial"] == "unclear"
    assert Film.create(tmp_path / "c", "storybook", MANIFEST).data["style_commercial"] == "yes"


def test_characters_need_a_style_first(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Film(tmp_path / "x").add_character("pip")
