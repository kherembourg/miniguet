#!/bin/sh
# Prints the pairing address for a remote device (the tablet). Open it once on that device: it remembers the device,
# which can then send text to agents. Anyone with this address can pair a device: keep it private.
set -eu
TOKEN="$(cat "$HOME/.local/state/herdr-board/pair_token")"
NAME="$(scutil --get LocalHostName 2>/dev/null | tr 'A-Z' 'a-z')"
echo "http://${NAME:-localhost}:8765/?pair=${TOKEN}"
