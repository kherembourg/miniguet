#!/bin/sh
# fake hc: waits FAKE_SLEEP seconds, then succeeds.
sleep "${FAKE_SLEEP:-0}"
echo '{"status":"blocked","turn":1}'
