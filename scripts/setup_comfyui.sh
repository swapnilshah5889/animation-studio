#!/usr/bin/env bash
# Install (or repair) ComfyUI natively on macOS / Apple Silicon. Safe to re-run: every step checks
# what is already there. Decisions: D-016 (own venv), D-017 (version, node packs).
#
#   scripts/setup_comfyui.sh            # install / update to the pinned versions
#
# Model weights are not handled here: use `uv run scripts/fetch_models.py <preset or file id>`.
set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ai-studio/comfyui}"
COMFY_TAG="v0.42.1"
# Custom node packs, pinned to the commits verified in Step 0: "folder repo commit"
NODES=(
  "ComfyUI-segment-anything-2 https://github.com/kijai/ComfyUI-segment-anything-2.git 0c35fff5f382803e2310103357b5e985f5437f32"
  "comfyui_controlnet_aux https://github.com/Fannovel16/comfyui_controlnet_aux.git a587a4c1594524c1d2de5cd1a86cd868ff448e1c"
)
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-600}"   # slow networks: big wheels time out at 30 s

echo "==> ComfyUI $COMFY_TAG in $COMFY_DIR"
if [ ! -d "$COMFY_DIR/.git" ]; then
  git clone https://github.com/Comfy-Org/ComfyUI.git "$COMFY_DIR"
fi
git -C "$COMFY_DIR" fetch --tags --quiet origin
git -C "$COMFY_DIR" checkout --quiet "$COMFY_TAG"

echo "==> Python 3.12 venv (uv)"
if [ ! -x "$COMFY_DIR/.venv/bin/python" ]; then
  uv venv --python 3.12 "$COMFY_DIR/.venv"
fi
export VIRTUAL_ENV="$COMFY_DIR/.venv"
# Stable PyTorch from PyPI: the macOS arm64 wheels include the MPS (Metal) backend.
uv pip install --quiet torch torchvision torchaudio
uv pip install --quiet -r "$COMFY_DIR/requirements.txt" -r "$COMFY_DIR/manager_requirements.txt"

echo "==> Custom node packs"
for entry in "${NODES[@]}"; do
  read -r folder repo commit <<<"$entry"
  dir="$COMFY_DIR/custom_nodes/$folder"
  if [ ! -d "$dir/.git" ]; then
    git clone --quiet "$repo" "$dir"
  fi
  git -C "$dir" fetch --quiet origin "$commit" 2>/dev/null || git -C "$dir" fetch --quiet origin
  git -C "$dir" checkout --quiet "$commit"
  if [ -f "$dir/requirements.txt" ]; then
    uv pip install --quiet -r "$dir/requirements.txt"
  fi
  echo "    $folder @ ${commit:0:7}"
done

echo "==> comfyui_controlnet_aux config (weights under models/annotators, CPU ONNX only)"
cat > "$COMFY_DIR/custom_nodes/comfyui_controlnet_aux/config.yaml" <<EOF
# Written by animation-studio/scripts/setup_comfyui.sh (D-017).
annotator_ckpts_path: "$COMFY_DIR/models/annotators"
custom_temp_path:
USE_SYMLINKS: False
EP_list: ["CPUExecutionProvider"]
EOF

echo "==> Check (from the ComfyUI folder: comfyui_manager imports ComfyUI's own 'comfy' package)"
cd "$COMFY_DIR"
"$COMFY_DIR/.venv/bin/python" -c \
  "import torch, comfyui_manager; print('torch', torch.__version__, 'mps', torch.backends.mps.is_available())"
echo "Done. Start the server with scripts/comfy_server.sh"
