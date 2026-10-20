"""Coordinate and time conversions between our world (pixels, seconds) and Synfig's (units, frames).

Synfig's canvas space ("units") is centred on (0, 0) with **y pointing up**. A canvas of
`width x height` pixels at `ppu` pixels per unit spans x in [-width/ppu/2, +width/ppu/2] and
y in [-height/ppu/2, +height/ppu/2]; that range is the canvas `view-box`.

Time in the file is written as whole frames (`"36f"`), which is exact; seconds would round.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Space:
    """Pixel ↔ unit conversion for one canvas."""

    width: int
    height: int
    ppu: float = 60.0  # pixels per unit (Synfig's default)

    @property
    def half_width_units(self) -> float:
        return self.width / self.ppu / 2

    @property
    def half_height_units(self) -> float:
        return self.height / self.ppu / 2

    def view_box(self) -> tuple[float, float, float, float]:
        """(left, top, right, bottom) in units, as the canvas `view-box` attribute wants."""
        hw, hh = self.half_width_units, self.half_height_units
        return (-hw, hh, hw, -hh)

    def to_units(self, x_px: float, y_px: float) -> tuple[float, float]:
        """A canvas pixel position (origin top-left, y down) → units (origin centre, y up)."""
        return ((x_px - self.width / 2) / self.ppu, (self.height / 2 - y_px) / self.ppu)

    def length(self, px: float) -> float:
        """A length in pixels → units (no origin shift)."""
        return px / self.ppu


def frames(seconds: float, fps: int) -> int:
    """Seconds → the frame index that starts at or after that time (no drift from float error)."""
    return math.ceil(round(seconds * fps, 6))


def frame_time(frame: int) -> str:
    """How a frame is written in a .sif time attribute."""
    if frame < 0:
        raise ValueError(f"negative frame {frame}")
    return f"{frame}f"
