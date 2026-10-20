import pytest

from studio_core.sif import Space, frame_time, frames


def test_space_maps_pixels_to_centered_y_up_units() -> None:
    s = Space(1920, 1080, ppu=120)
    assert s.view_box() == (-8.0, 4.5, 8.0, -4.5)
    assert s.to_units(960, 540) == (0.0, 0.0)  # centre
    assert s.to_units(0, 0) == (-8.0, 4.5)  # top-left
    assert s.to_units(1920, 1080) == (8.0, -4.5)  # bottom-right: y flips
    assert s.length(60) == 0.5


@pytest.mark.parametrize(
    ("seconds", "fps", "expected"),
    [(0, 24, 0), (1, 24, 24), (0.5, 24, 12), (2.3, 24, 56), (0.1, 30, 3), (1 / 3, 24, 8)],
)
def test_frames_round_up_without_float_drift(seconds: float, fps: int, expected: int) -> None:
    assert frames(seconds, fps) == expected


def test_frame_time_format() -> None:
    assert frame_time(0) == "0f"
    assert frame_time(240) == "240f"
    with pytest.raises(ValueError):
        frame_time(-1)
