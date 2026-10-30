#!/usr/bin/env bash
# Evidence for the animation-review skill: contact sheet, per-frame change, loudness. Safe to re-run.
set -euo pipefail
in="${1:?usage: make_evidence.sh <video-or-image> <out-dir> [start-seconds] [end-seconds]}"
out="${2:?out-dir}"; start="${3:-0}"; end="${4:-}"
mkdir -p "$out"
case "${in##*.}" in
  png|jpg|jpeg|webp) cp "$in" "$out/sheet.png"; echo "image copied to $out/sheet.png"; exit 0;;
esac
dur_args=(); [ -n "$end" ] && dur_args=(-t "$(python3 -c "print(max(0.1,$end-$start))")")
len="$(python3 -c "print(max(0.1,(${end:-0} or $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$in"))-$start))")"
fps="$(python3 -c "print(12/$len)")"
ffmpeg -loglevel error -y -ss "$start" "${dur_args[@]}" -i "$in" \
  -vf "fps=$fps,scale=480:-1,tile=4x3" \
  -frames:v 1 "$out/sheet.png"
ffmpeg -loglevel error -y -ss "$start" "${dur_args[@]}" -i "$in" -vf "scale=320:-1,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=$out/_raw.txt" -an -f null -
python3 -c "import sys;s=float(sys.argv[1]);l=float(sys.argv[2]);print(chr(10).join('frame %d: %.2fs'%(i+1,s+(i+0.5)*l/12) for i in range(12)))" "$start" "$len" > "$out/sheet_times.txt"
python3 - "$out" <<'PY'
import re,sys,statistics,pathlib
o=pathlib.Path(sys.argv[1]); rows=[]
for l in (o/"_raw.txt").read_text().splitlines():
    m=re.search(r"pts_time:([\d.]+)",l)
    if m: t=float(m.group(1))
    m=re.search(r"YAVG=([\d.]+)",l)
    if m: rows.append((t,float(m.group(1))))
(o/"_raw.txt").unlink()
(o/"motion.csv").write_text("time,change\n"+"\n".join(f"{t:.3f},{v:.3f}" for t,v in rows)+"\n")
if rows:
    med=statistics.median(v for _,v in rows) or 1e-6
    spikes=[(t,v) for t,v in rows if v>8*med and v>1.0]
    print(f"frames={len(rows)} median_change={med:.3f} max={max(v for _,v in rows):.2f} spikes(>8x median)={len(spikes)}")
    for t,v in spikes[:10]: print(f"  spike at {t:.2f}s change={v:.2f}")
PY
ffmpeg -hide_banner -ss "$start" "${dur_args[@]}" -i "$in" -af ebur128=peak=true -f null - 2>&1 | grep -E "I:|Peak:" | tail -2 > "$out/audio.txt" || true
echo "wrote $out/sheet.png $out/motion.csv $out/audio.txt"
