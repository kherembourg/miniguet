#!/bin/sh
# Installs Miniguet as a launchd agent (starts at login, restarts if it crashes).
# It listens on 127.0.0.1 and on the Tailscale address only, never on the local network.
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
PORT="${PORT:-8765}"   # PORT=8766 scripts/install-launchd.sh if 8765 is taken
PLIST="$HOME/Library/LaunchAgents/local.miniguet.plist"
sed -e "s#__PYTHON__#$PY#g" -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME#g" -e "s#__PORT__#$PORT#g" \
  "$REPO/launchd/local.miniguet.plist.template" > "$PLIST"
plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/local.miniguet" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Miniguet installed. Logs: /tmp/miniguet.log. Open http://localhost:$PORT"
