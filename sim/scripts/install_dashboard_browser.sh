#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PLAYWRIGHT_BROWSERS_PATH="$PROJECT_DIR/.browser-runtime"
"$PROJECT_DIR/.venv/bin/python" -m playwright install --only-shell chromium
