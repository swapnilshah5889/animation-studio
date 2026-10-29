"""Editing: finished shot videos and title cards become one film (Step 5, edit_mcp).

spec.py    the edit spec (edit/edit.json) and all timeline math: frames, overlaps, total length
titles.py  title cards: text on a plain backdrop, rendered with Pillow and encoded by ffmpeg
mlt.py     the MLT project (edit/film.mlt) built from a spec
render.py  melt renders final.mp4; ffprobe and the loudness check verify it
"""
