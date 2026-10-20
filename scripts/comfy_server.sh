#!/usr/bin/env bash
# Start ComfyUI headless on 127.0.0.1:8188 (native, Metal/MPS). Safe to re-run: if a server already
# answers on the port, it does nothing.
#
#   scripts/comfy_server.sh              # start in the background, log to ~/ai-studio/comfyui/user/server.log
#   scripts/comfy_server.sh --manager    # also enable ComfyUI-Manager (it contacts the internet)
#   scripts/comfy_server.sh --stop
#
# Mac memory rule: unload Ollama models before heavy ComfyUI work (CLAUDE.md).
set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ai-studio/comfyui}"
PORT="${COMFY_PORT:-8188}"
LOG="$COMFY_DIR/user/server.log"
PIDFILE="$COMFY_DIR/user/server.pid"

if [ "${1:-}" = "--stop" ]; then
  if [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "stopped ComfyUI (pid $(cat "$PIDFILE"))"
  else
    echo "no ComfyUI started by this script is running"
  fi
  rm -f "$PIDFILE"
  exit 0
fi

if curl -sf "http://127.0.0.1:$PORT/system_stats" >/dev/null; then
  echo "ComfyUI already running on 127.0.0.1:$PORT"
  exit 0
fi

EXTRA=()
if [ "${1:-}" = "--manager" ]; then
  EXTRA+=(--enable-manager)
fi

mkdir -p "$COMFY_DIR/user"
cd "$COMFY_DIR"
# MPS lacks a few ops some custom nodes use; fall back to CPU for those instead of erroring.
export PYTORCH_ENABLE_MPS_FALLBACK=1
# Offline at runtime: never fetch models implicitly (fetch them with scripts/fetch_models.py).
export HF_HUB_OFFLINE=1
nohup .venv/bin/python main.py --listen 127.0.0.1 --port "$PORT" --disable-auto-launch \
  ${EXTRA[@]+"${EXTRA[@]}"} >"$LOG" 2>&1 &
echo $! >"$PIDFILE"

for _ in $(seq 1 120); do
  if curl -sf "http://127.0.0.1:$PORT/system_stats" >/dev/null; then
    echo "ComfyUI up on http://127.0.0.1:$PORT (pid $(cat "$PIDFILE"), log $LOG)"
    exit 0
  fi
  sleep 1
done
echo "ComfyUI did not come up within 120 s; see $LOG" >&2
exit 1
