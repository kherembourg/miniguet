#!/bin/sh
# fake ffmpeg: copies the input (after -i) to the last argument. FAKE_SLEEP / FAKE_FFMPEG_SLEEP: seconds to wait first.
sleep "${FAKE_FFMPEG_SLEEP:-${FAKE_SLEEP:-0}}"
while [ "$1" != "-i" ]; do shift; done
in="$2"
for last; do :; done
cp "$in" "$last"
