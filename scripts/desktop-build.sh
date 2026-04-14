#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_TRIPLE="${HERMES_STUDIO_TARGET_TRIPLE:-$(rustc -vV | awk '/^host:/ { print $2 }')}"
PYTHON="${PYTHON:-python3}"
BACKEND_BIN_DIR="$ROOT/src-tauri/bin"
PYINSTALLER_WORK="$ROOT/backend/build/pyinstaller"
SIDECAR_NAME="hermes-studio-backend-$TARGET_TRIPLE"
BUNDLE_PYTHON_VOICE="${HERMES_STUDIO_BUNDLE_PYTHON_VOICE:-0}"

echo "Building frontend..."
(
  cd "$ROOT/frontend"
  npm run build
)

echo "Building backend sidecar for $TARGET_TRIPLE..."
if ! "$PYTHON" -c 'import PyInstaller' >/dev/null 2>&1; then
  cat >&2 <<EOF
PyInstaller is required to build the standalone backend sidecar.
Install it with:
  python3 -m pip install pyinstaller
EOF
  exit 1
fi

mkdir -p "$BACKEND_BIN_DIR" "$PYINSTALLER_WORK/spec"

export PYINSTALLER_CONFIG_DIR="$PYINSTALLER_WORK/cache"
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

VOICE_EXCLUDES=()
if [[ "$BUNDLE_PYTHON_VOICE" != "1" ]]; then
  echo "Skipping optional Python voice engines in the sidecar."
  echo "Set HERMES_STUDIO_BUNDLE_PYTHON_VOICE=1 to bundle mlx/faster-whisper dependencies."
  VOICE_EXCLUDES=(
    --exclude-module faster_whisper
    --exclude-module mlx_whisper
    --exclude-module mlx_audio
    --exclude-module torch
    --exclude-module torchaudio
    --exclude-module torchvision
    --exclude-module tensorflow
    --exclude-module transformers
    --exclude-module scipy
    --exclude-module sklearn
    --exclude-module pandas
    --exclude-module pyarrow
    --exclude-module cv2
    --exclude-module onnxruntime
  )
fi

"$PYTHON" -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name "$SIDECAR_NAME" \
  --paths "$ROOT/backend" \
  --collect-submodules app \
  --collect-submodules uvicorn \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  "${VOICE_EXCLUDES[@]}" \
  --distpath "$BACKEND_BIN_DIR" \
  --workpath "$PYINSTALLER_WORK/work" \
  --specpath "$PYINSTALLER_WORK/spec" \
  "$ROOT/backend/app/desktop_server.py"

chmod +x "$BACKEND_BIN_DIR/$SIDECAR_NAME"
echo "Backend sidecar ready: $BACKEND_BIN_DIR/$SIDECAR_NAME"
