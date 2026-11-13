#!/bin/sh
# fake whisper-cli: prints a fixed sentence. FAKE_SLEEP / FAKE_WHISPER_SLEEP: seconds to wait first; FAKE_PIDFILE: where to write its pid.
[ -n "$FAKE_PIDFILE" ] && echo $$ > "$FAKE_PIDFILE"
sleep "${FAKE_WHISPER_SLEEP:-${FAKE_SLEEP:-0}}"
echo "bonjour le monde"
