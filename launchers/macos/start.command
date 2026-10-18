#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${0:A:h}/../.."
PROJECT_DIR="${PROJECT_DIR:A}"
LABEL="com.downloadable.helper"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ ! -f "$PLIST" ]]; then
  echo "Downloadable is not installed yet. Running setup…"
  exec zsh "$PROJECT_DIR/launchers/macos/setup.command"
fi

launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "Downloadable helper started in the background. This window can be closed."
