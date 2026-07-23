#!/bin/bash

# Watch outgoing UDP telemetry sendto() calls from a running instrument.py,
# to confirm packets match telem-config.yaml (destination IP/port + payload).
# Usage: ./udp-check.sh [seconds]

DURATION="${1:-15}"

PID=$(pgrep -f 'instrument.py' | head -1)

if [[ -z "$PID" ]]; then
    echo "instrument.py is not running."
    exit 1
fi

echo "Watching UDP sends from instrument.py (PID $PID) for ${DURATION}s..."
sudo timeout "$DURATION" strace -p "$PID" -e trace=sendto -s 300 -tt
