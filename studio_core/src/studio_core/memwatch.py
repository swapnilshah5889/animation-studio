"""Sample system memory while something heavy runs (macOS).

Used by the benchmarks to answer "how close did that stage get to swapping?". It samples, in a
background thread:

- used memory: wired + active + compressed pages (roughly Activity Monitor's "Memory Used")
- memorystatus_level: the percentage of memory the kernel considers free (pressure indicator)
- swap used

    with MemoryWatch() as mem:
        run_heavy_thing()
    print(mem.summary())
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from types import TracebackType

GB = 1024**3


def _sysctl(name: str) -> str:
    return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True).stdout.strip()


def used_bytes() -> int:
    """Wired + active + compressed memory, from vm_stat."""
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page = int(re.search(r"page size of (\d+)", out).group(1))  # type: ignore[union-attr]

    def pages(label: str) -> int:
        match = re.search(rf"{label}:\s+(\d+)", out)
        return int(match.group(1)) if match else 0

    return page * (
        pages("Pages wired down") + pages("Pages active") + pages("Pages occupied by compressor")
    )


def swap_used_bytes() -> int:
    match = re.search(r"used = ([\d.]+)M", _sysctl("vm.swapusage"))
    return int(float(match.group(1)) * 1024**2) if match else 0


@dataclass
class MemoryWatch:
    interval_s: float = 0.25
    peak_used: int = 0
    min_free_pct: int = 100
    swap_start: int = 0
    swap_peak: int = 0
    samples: int = 0
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def _sample(self) -> None:
        self.peak_used = max(self.peak_used, used_bytes())
        level = _sysctl("kern.memorystatus_level")
        if level.isdigit():
            self.min_free_pct = min(self.min_free_pct, int(level))
        self.swap_peak = max(self.swap_peak, swap_used_bytes())
        self.samples += 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample()
            time.sleep(self.interval_s)

    def __enter__(self) -> MemoryWatch:
        self.swap_start = swap_used_bytes()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        self._sample()

    @property
    def swap_grew_gb(self) -> float:
        return max(0, self.swap_peak - self.swap_start) / GB

    def summary(self) -> str:
        return (
            f"peak used {self.peak_used / GB:.1f} GB, min free {self.min_free_pct}%, "
            f"swap +{self.swap_grew_gb:.2f} GB"
        )
