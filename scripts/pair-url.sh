#!/bin/sh
# Prints the pairing address for a remote device (the tablet). Open it once on that device: it remembers the device,
# which can then send text to agents. Anyone with this address can pair a device: keep it private.
set -eu
STATE="$HOME/.local/state/herdr-board"
TOKEN="$(cat "$STATE/pair_token")"
HOST="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("host",""))' "$STATE/cloudflare.json" 2>/dev/null || true)"
if [ -n "$HOST" ]; then
  echo "https://${HOST}/?pair=${TOKEN}"
else
  NAME="$(scutil --get LocalHostName 2>/dev/null | tr 'A-Z' 'a-z')"
  echo "http://${NAME:-localhost}:${PORT:-8765}/?pair=${TOKEN}"
fi
