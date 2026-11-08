#!/usr/bin/env bash
# Local macOS build (the GitHub workflow does the same for Mac and Windows). Output: .dmg
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/frontend" && npm ci && npm run build)
(cd "$ROOT/backend" && python3 -m pip install -e . pyinstaller)
python3 "$ROOT/scripts/build_backend.py"
(cd "$ROOT/desktop" && npm ci && npx tauri build --bundles dmg)
