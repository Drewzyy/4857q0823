#!/usr/bin/env bash
# Package the Python backend as a single self-contained executable for the desktop app's sidecar.
# Run on the Mac you build the app on (PyInstaller does not cross-compile).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
python3 -m pip install -q -e ".[dev]" pyinstaller
TRIPLE="$(rustc -vV | sed -n 's/host: //p')"
OUT="$ROOT/desktop/src-tauri/binaries"
mkdir -p "$OUT"
python3 -m PyInstaller --noconfirm --clean --onefile --name clippr-backend \
  --distpath "$ROOT/backend/build/dist" --workpath "$ROOT/backend/build/work" --specpath "$ROOT/backend/build" \
  --add-data "$ROOT/backend/clippr/migrations:clippr/migrations" \
  --collect-submodules clippr --collect-submodules keyring \
  --hidden-import keyring.backends.macOS \
  "$ROOT/backend/clippr/__main__.py"
cp "$ROOT/backend/build/dist/clippr-backend" "$OUT/clippr-backend-$TRIPLE"
echo "sidecar: $OUT/clippr-backend-$TRIPLE"
