#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [[ -d /mnt/chromeos/MyFiles ]]; then
  export DOWNLOADABLE_HOST="0.0.0.0"
else
  export DOWNLOADABLE_HOST="127.0.0.1"
fi
exec .venv/bin/python helper/helper.py
