"""The MLT project (edit/film.mlt) for an edit spec; `melt film.mlt` plays or renders it.

Layout: one playlist of entries. A cut is two entries side by side. A crossfade is a small tractor
with two tracks (the tail of one clip and the head of the next) holding a `luma` transition for the
picture and a `mix` transition for the sound, the same shape melt's own `-mix` writes. The clip
videos are referenced by absolute path, so the project opens from anywhere.

Only MLT is written: Kdenlive keeps its own project metadata in the same XML, and a plain MLT
file is not guaranteed to open there (see docs; Kdenlive is not installed on this Mac).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

from studio_core.edit.spec import Placed, layout, total_frames


def _prop(name: str, value: object) -> str:
    return f"    <property name={quoteattr(name)}>{value}</property>"


def build_mlt(spec: dict[str, Any], film_root: Path) -> str:
    fps, w, h = spec["fps"], spec["width"], spec["height"]
    placed = layout(spec)
    out: list[str] = ['<?xml version="1.0" encoding="utf-8"?>', '<mlt LC_NUMERIC="C">']
    out.append(
        f'  <profile description="film" width="{w}" height="{h}" progressive="1" '
        f'sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="{w}" '
        f'display_aspect_den="{h}" frame_rate_num="{fps}" frame_rate_den="1" colorspace="709"/>'
    )
    for p in placed:
        clip = spec["clips"][p.index]
        path = (film_root / clip["file"]).resolve()
        out += [
            f'  <producer id="c{p.index}" in="0" out="{p.length - 1}">',
            _prop("resource", path),
            _prop("length", p.length),
            _prop("eof", "pause"),
            _prop("mlt_service", "avformat"),
            "  </producer>",
        ]

    entries: list[str] = []
    tractors: list[str] = []
    for p in placed:
        nxt = placed[p.index + 1] if p.index + 1 < len(placed) else None
        head = p.overlap_in  # frames at the start already used by the crossfade in
        tail = nxt.overlap_in if nxt else 0
        mid_in, mid_out = head, p.length - tail - 1
        if mid_out >= mid_in:
            entries.append(f'    <entry producer="c{p.index}" in="{mid_in}" out="{mid_out}"/>')
        if nxt and tail:
            n = tail
            tractors += _crossfade(p, nxt, n)
            entries.append(f'    <entry producer="x{nxt.index}" in="0" out="{n - 1}"/>')
    out += tractors
    out += ['  <playlist id="film">', *entries, "  </playlist>"]
    out += [
        f'  <tractor id="main" in="0" out="{total_frames(spec) - 1}">',
        '    <track producer="film"/>',
        "  </tractor>",
        "</mlt>",
        "",
    ]
    return "\n".join(out)


def _crossfade(a: Placed, b: Placed, n: int) -> list[str]:
    return [
        f'  <tractor id="x{b.index}" in="0" out="{n - 1}">',
        f'    <track producer="c{a.index}" in="{a.length - n}" out="{a.length - 1}"/>',
        f'    <track producer="c{b.index}" in="0" out="{n - 1}"/>',
        f'    <transition id="xv{b.index}" out="{n - 1}">',
        '      <property name="a_track">0</property>',
        '      <property name="b_track">1</property>',
        '      <property name="mlt_service">luma</property>',
        "    </transition>",
        f'    <transition id="xa{b.index}" out="{n - 1}">',
        '      <property name="a_track">0</property>',
        '      <property name="b_track">1</property>',
        '      <property name="mlt_service">mix</property>',
        '      <property name="always_active">1</property>',
        '      <property name="sum">1</property>',
        "    </transition>",
        "  </tractor>",
    ]
