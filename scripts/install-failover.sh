#!/bin/sh
# Installs the failover relay as a launchd agent on the Mac that runs the Cloudflare Tunnel.
#   scripts/install-failover.sh http://<main-mac>:8766 http://127.0.0.1:8766
# Then point the tunnel's hostname at http://127.0.0.1:${LISTEN:-8767}.
set -eu
[ $# -ge 1 ] || { echo "usage: $0 <miniguet url, preferred first>..." >&2; exit 2; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
LISTEN="${LISTEN:-8767}"
PLIST="$HOME/Library/LaunchAgents/local.miniguet-failover.plist"
ARGS=""
for u in "$@"; do ARGS="$ARGS<string>$u</string>"; done
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>local.miniguet-failover</string>
<key>ProgramArguments</key><array><string>$PY</string><string>$REPO/scripts/failover.py</string><string>--listen</string><string>$LISTEN</string>$ARGS</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>/tmp/miniguet-failover.log</string>
<key>StandardErrorPath</key><string>/tmp/miniguet-failover.log</string>
</dict></plist>
PL
plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/local.miniguet-failover" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Failover relay on http://127.0.0.1:$LISTEN. Logs: /tmp/miniguet-failover.log"
