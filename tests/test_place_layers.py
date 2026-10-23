"""Splitting a plate into parallax layers (task 4.7): bands, parallax and fills on a synthetic
depth map (sky, far hills, a middle tree line, a receding ground, a post standing up near the
bottom), then the layer images and layers.json."""

from pathlib import Path

import numpy as np
import pytest

from studio_core.place.layers import (
    REACH,
    SKY_PARALLAX,
    compose_layers,
    fill_regions,
    split_bands,
    write_layers,
)
from studio_core.schema import validate_file

H, W = 540, 1440


def nearness(post: bool = True) -> np.ndarray:
    """0 = far, 1 = near: sky on top, hills, trees, then ground getting nearer to the bottom."""
    n = np.zeros((H, W), dtype="float32")
    rows = np.arange(H)[:, None]
    n[:] = 0.02  # sky
    hills = rows >= 160 + 30 * np.sin(np.arange(W) / 120)[None, :]
    n[hills] = 0.3
    n[230:300] = 0.5  # a tree line
    n[300:] = np.linspace(0.6, 1.0, H - 300)[:, None]  # the ground, nearer toward the bottom
    if post:
        n[440:H, 600:640] += 0.3  # something standing up out of the ground
    return n.clip(0, 1.3)


def test_bands_far_to_near_with_parallax() -> None:
    split = split_bands(np.kron(nearness(), np.ones((2, 2), dtype="float32")))  # plate size
    names = [b.name for b in split.bands]
    assert names == ["sky", "far", "middle", "ground", "foreground"]
    sky, far, middle, ground, fg = split.bands
    assert sky.mask[:200].all() and not sky.mask[640:].any()
    assert sky.parallax == SKY_PARALLAX and ground.parallax == 1.0
    assert sky.parallax < far.parallax < middle.parallax < ground.parallax < fg.parallax
    assert fg.parallax <= 0.9 * (2880 / 2 - 960) / 240  # its edge never enters the frame
    assert fg.in_front and fg.mask[960, 1240] and not fg.mask[960, 400]
    every = np.sum([b.mask.astype(int) for b in split.bands], axis=0)
    assert every.min() == 1 and every.max() == 1  # each pixel in exactly one band


def test_ground_pieces_off_the_bottom_join_their_neighbour() -> None:
    """A near tree's canopy is as bright in depth as the lawn, but it isn't ground."""
    near = nearness(post=False)
    near[120:200, 1200:1300] = 0.95  # a canopy high up, as near as the lawn
    near[200:300, 1240:1260] = 0.5  # its trunk, in the tree line
    split = split_bands(np.kron(near, np.ones((2, 2), dtype="float32")))
    ground = next(b for b in split.bands if b.name == "ground")
    assert not ground.mask[300, 2500]  # the canopy is not ground
    assert ground.mask[-1].all()  # the ground still runs along the bottom


def test_no_foreground_without_something_standing_up() -> None:
    names = [b.name for b in split_bands(nearness(post=False)).bands]
    assert "foreground" not in names


def test_fills_cover_what_a_pan_can_reveal() -> None:
    bands = split_bands(nearness()).bands
    regions = fill_regions(bands)
    assert (regions[0] | bands[0].mask).all()  # the sky layer covers the whole frame
    assert not regions[-1].any()  # nothing is behind the nearest layer
    far, far_region = bands[1], regions[1]
    nearer = np.any([b.mask for b in bands[2:]], axis=0)
    assert (far_region <= nearer).all()  # only behind nearer layers
    ys = np.nonzero(far.mask.any(axis=1))[0]
    assert far_region[ys.max() + REACH // 2].any()  # reaches down behind the trees
    assert not far_region[ys.max() + REACH + 40 :].any()  # but no further than a pan reveals


def test_layers_and_layers_json(tmp_path: Path) -> None:
    full = np.kron(nearness(), np.ones((2, 2), dtype="float32"))  # the plate size, 2880x1080
    h, w = full.shape
    plate = np.zeros((h, w, 3), dtype="float32")
    plate[:] = (120, 180, 230)
    split = split_bands(full)
    regions = fill_regions(split.bands)
    fills = [np.full((h, w, 3), (200, 100, 50), dtype="float32") if r.any() else None
             for r in regions]  # fmt: skip
    layers = compose_layers(plate, split.bands, fills, regions)
    sky = layers[0]
    assert sky.shape == (h, w, 4) and (sky[..., 3] == 255).all()  # opaque everywhere
    assert tuple(sky[1000, 400, :3]) == (200, 100, 50)  # filled behind the ground
    assert tuple(sky[100, 400, :3]) == (120, 180, 230)  # its own pixels kept
    ground = layers[3]
    assert ground[100, 400, 3] == 0 and ground[1000, 400, 3] == 255
    path = write_layers(tmp_path, "meadow", "Meadow", split.bands, layers, "#9fd2f2")
    assert validate_file(path) == []
    assert {p.name for p in (tmp_path / "layers").iterdir()} == {
        f"{b.name}.png" for b in split.bands
    }
    data = path.read_text()
    assert '"in_front": true' in data and '"parallax": 1.0' in data


@pytest.mark.parametrize("shift", [0.0, 0.1])
def test_parallax_follows_the_ground_at_the_feet(shift: float) -> None:
    """The ground layer is 1.0 whatever the depth model's scale."""
    split = split_bands(np.clip(nearness() + shift, 0, 1.4))
    assert next(b for b in split.bands if b.name == "ground").parallax == 1.0
