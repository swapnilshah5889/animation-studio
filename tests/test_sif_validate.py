"""The pre-render validator catches what the Synfig CLI handles badly."""

import re
import shutil
from pathlib import Path

import pytest

from studio_core.config import REPO_ROOT
from studio_core.sif.render import RenderError, render_frames
from studio_core.sif.validate import validate_sif

EXAMPLES = REPO_ROOT / "tests" / "fixtures" / "sif_examples"


@pytest.fixture
def arm(tmp_path: Path) -> Path:
    for f in ("bones_arm_minimal.sif", "upper.png", "forearm.png"):
        shutil.copy(EXAMPLES / f, tmp_path / f)
    return tmp_path / "bones_arm_minimal.sif"


def edit(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, count))


def test_valid_file_passes(arm: Path) -> None:
    assert validate_sif(arm) == []


def test_missing_image(arm: Path) -> None:
    (arm.parent / "forearm.png").unlink()
    assert any("image not found: forearm.png" in i for i in validate_sif(arm))


def test_bones_after_layers(arm: Path) -> None:
    text = arm.read_text()
    bones = re.search(r"\s*<bones>.*?</bones>", text, re.S).group(0)
    text = text.replace(bones, "").replace("</canvas>", bones + "\n</canvas>")
    arm.write_text(text)
    assert any("must come before the first <layer>" in i for i in validate_sif(arm))


def test_missing_bone_link_and_unknown_guid(arm: Path) -> None:
    edit(arm, '<scalex><real value="1"/></scalex>', "")
    edit(
        arm,
        'guid="00000000000000000000000000000B02"/>',
        'guid="00000000000000000000000000000BFF"/>',
    )
    issues = validate_sif(arm)
    assert any("is missing ['scalex']" in i for i in issues), issues
    assert any("undefined bone" in i for i in issues), issues


def test_duplicate_guid(arm: Path) -> None:
    edit(
        arm,
        '<bone type="bone_object" guid="00000000000000000000000000000B02">',
        '<bone type="bone_object" guid="00000000000000000000000000000B01">',
    )
    assert any("duplicate bone GUID" in i for i in validate_sif(arm))


def test_render_refuses_an_invalid_file(arm: Path, tmp_path: Path) -> None:
    (arm.parent / "upper.png").unlink()
    with pytest.raises(RenderError, match="image not found"):
        render_frames(arm, tmp_path / "frames")


def test_not_xml(tmp_path: Path) -> None:
    (tmp_path / "x.sif").write_text("<canvas>")
    assert validate_sif(tmp_path / "x.sif")[0].startswith("not well-formed XML")
