#!/usr/bin/env bash
# Full macOS build: UI -> sidecar -> .app/.dmg. Requires Xcode CLT, Rust, Node 20+, Python 3.11+.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/frontend" && npm ci && npm run build)
"$ROOT/scripts/build-backend.sh"
(cd "$ROOT/desktop" && npm ci && npx tauri build)
echo "Built: $ROOT/desktop/src-tauri/target/release/bundle/"
