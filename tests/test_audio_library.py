"""The sound-effect library manifest: loading, validation, id → file (task 3.1)."""

import json
import shutil
from pathlib import Path

import pytest

from studio_core.audio.library import LibraryError, load_library

MANIFEST = Path(__file__).parent / "fixtures" / "schemas" / "sfx_library.json"


def test_no_manifest_is_an_empty_library(tmp_path: Path) -> None:
    library = load_library(tmp_path)
    assert library.sounds == {} and library.manifest == tmp_path / "manifest.json"


def test_ids_resolve_to_files(tmp_path: Path) -> None:
    shutil.copy(MANIFEST, tmp_path / "manifest.json")
    library = load_library(tmp_path)
    assert sorted(library.sounds) == ["bsb_toy_squeak_0427", "kenney_impact_footstep_wood_000"]
    assert library.path("bsb_toy_squeak_0427") == tmp_path / "bsb" / "toy_squeak_0427.wav"
    with pytest.raises(LibraryError, match="no sound 'boing' in the library"):
        library.path("boing")


def test_an_invalid_manifest_is_refused(tmp_path: Path) -> None:
    data = json.loads(MANIFEST.read_text())
    data["sounds"][0]["license"] = "CC-BY-NC-4.0"
    (tmp_path / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(LibraryError, match=r"sounds\[0\]\.license"):
        load_library(tmp_path)
