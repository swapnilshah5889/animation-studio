"""The edit spec, timeline math, title cards and the MLT project (no rendering of films)."""

import pytest
from PIL import Image

from studio_core.edit import spec as es
from studio_core.edit.mlt import build_mlt
from studio_core.edit.titles import draw_card
from studio_core.schema import validate


def clip(name: str, seconds: float, transition: dict | None = None) -> dict:
    c = {"kind": "shot", "shot": name, "file": f"shots/{name}/shot.mp4", "duration_s": seconds}
    if transition:
        c["transition_in"] = transition
    return c


XFADE = {"type": "crossfade", "duration_s": 0.5}


def test_frames_round_to_whole_frames() -> None:
    assert es.frames(0.5) == 12
    assert es.frames(7.5) == 180
    assert es.frames(1 / 24) == 1


def test_cuts_add_up() -> None:
    spec = es.build_spec([clip("s01_sh01", 8), clip("s01_sh02", 4, {"type": "cut"})])
    placed = es.layout(spec)
    assert [(p.start, p.length, p.overlap_in) for p in placed] == [(0, 192, 0), (192, 96, 0)]
    assert es.total_frames(spec) == 288
    assert es.total_seconds(spec) == 12.0


def test_crossfade_overlaps_and_shortens_the_film() -> None:
    spec = es.build_spec(
        [clip("s01_sh01", 8), clip("s01_sh02", 4, XFADE), clip("s02_sh01", 6, XFADE)]
    )
    placed = es.layout(spec)
    assert [(p.start, p.overlap_in) for p in placed] == [(0, 0), (180, 12), (264, 12)]
    assert es.total_seconds(spec) == 18 - 1.0  # two half-second overlaps


def test_the_first_clip_has_no_join() -> None:
    spec = es.build_spec([clip("s01_sh01", 2, XFADE), clip("s01_sh02", 2)])
    assert es.layout(spec)[0].overlap_in == 0
    assert es.total_frames(spec) == 96


def test_a_crossfade_longer_than_half_a_clip_is_refused() -> None:
    long_fade = {"type": "crossfade", "duration_s": 1.5}
    with pytest.raises(es.EditError, match="shorter"):
        es.build_spec([clip("s01_sh01", 4), clip("s01_sh02", 2, long_fade)])


def test_spec_is_checked_against_the_schema() -> None:
    bad = {"schema_version": 1, "fps": 24, "width": 1920, "height": 1080, "clips": []}
    assert validate("edit", bad)
    with pytest.raises(es.EditError, match="invalid edit"):
        es.build_spec([{"kind": "shot", "shot": "oops", "file": "x", "duration_s": 1}])


def test_shot_ids_become_paths_only_when_valid(tmp_path) -> None:
    assert es.shot_video(tmp_path, "s01_sh02") == tmp_path / "shots/s01_sh02/shot.mp4"
    with pytest.raises(es.EditError):
        es.shot_video(tmp_path, "../../etc")


def test_spec_round_trips_on_disk(tmp_path) -> None:
    spec = es.build_spec([clip("s01_sh01", 2)])
    es.save(tmp_path, spec)
    assert es.load(tmp_path) == spec
    assert es.load(tmp_path / "other") is None


def test_mlt_for_cuts_is_one_playlist_of_whole_clips(tmp_path) -> None:
    spec = es.build_spec([clip("s01_sh01", 2), clip("s01_sh02", 1)])
    xml = build_mlt(spec, tmp_path)
    assert xml.count("<producer ") == 2
    assert '<entry producer="c0" in="0" out="47"/>' in xml
    assert '<entry producer="c1" in="0" out="23"/>' in xml
    assert "<transition" not in xml
    assert f"{tmp_path.resolve()}/shots/s01_sh01/shot.mp4" in xml


def test_mlt_crossfade_uses_a_two_track_tractor_for_the_overlap(tmp_path) -> None:
    spec = es.build_spec([clip("s01_sh01", 4), clip("s01_sh02", 4, XFADE), clip("s02_sh01", 2)])
    xml = build_mlt(spec, tmp_path)
    # clip 0 plays up to the overlap, the tractor holds both tails/heads, clip 1 continues
    assert '<entry producer="c0" in="0" out="83"/>' in xml
    assert '<track producer="c0" in="84" out="95"/>' in xml
    assert '<track producer="c1" in="0" out="11"/>' in xml
    assert '<entry producer="x1" in="0" out="11"/>' in xml
    assert '<entry producer="c1" in="12" out="95"/>' in xml
    assert 'mlt_service">luma<' in xml and 'mlt_service">mix<' in xml
    # film length in the MLT = the spec's total
    assert f'<tractor id="main" in="0" out="{es.total_frames(spec) - 1}">' in xml


def test_title_card_is_drawn_at_the_requested_size() -> None:
    img = draw_card("The Orchard Day", "a story", (640, 360))
    assert isinstance(img, Image.Image) and img.size == (640, 360)
    assert len(img.getcolors(maxcolors=1 << 20) or []) > 1  # text drawn on the backdrop
