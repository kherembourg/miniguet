#!/bin/sh
# Deploys the pushed main branch: restarts the local service (if installed) and, for each ssh target given,
# pulls and restarts there.   scripts/deploy.sh kevin@100.75.247.49
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
if [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] || [ "$(git -C "$REPO" rev-parse HEAD)" != "$(git -C "$REPO" rev-parse @{u} 2>/dev/null)" ]; then
  echo "commit and push first (remote machines deploy from GitHub)" >&2; exit 1
fi
restart='for s in local.miniguet local.miniguet-failover; do launchctl print "gui/$(id -u)/$s" >/dev/null 2>&1 && launchctl kickstart -k "gui/$(id -u)/$s" && echo "  restarted $s"; done; true'
echo "local:"; sh -c "$restart"
for target in "$@"; do
  echo "$target:"
  ssh -o BatchMode=yes "$target" "cd ~/Development/miniguet && git pull -q --ff-only && git log --oneline -1 && $restart"
done
