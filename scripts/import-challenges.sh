#!/bin/bash
# Generic challenge import entrypoint.
# Usage:
#   ./scripts/import-challenges.sh [path-to-challenge-root]

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$ROOT_DIR/scripts/import-challenges.py" "${1:-}"
