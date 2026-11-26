#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/pyinstaller" ]]; then
  echo "Error: .venv/bin/pyinstaller not found. Install requirements-dev.lock first." >&2
  exit 1
fi

rm -rf build dist

.venv/bin/pyinstaller --noconfirm --clean finora.spec

APP_BUNDLE="dist/Finora.app"
if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Error: Expected bundle at $APP_BUNDLE was not produced." >&2
  exit 1
fi

# Ad-hoc local signing for Apple Silicon execution (not Developer ID notarized).
codesign --force --deep --sign - "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"

echo "Built and ad-hoc signed: $ROOT_DIR/$APP_BUNDLE"
file "$APP_BUNDLE/Contents/MacOS/Finora"
