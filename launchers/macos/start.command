#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h}/../.."
PROJECT_DIR="${PROJECT_DIR:A}"
cd "$PROJECT_DIR"
exec .venv/bin/python helper/helper.py
