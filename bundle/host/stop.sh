#!/bin/bash
set -e

HARNESS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${HARNESS_DIR}/data/.mitmproxy.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found. mitmproxy may not be running."
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    # プロセス終了を待つ（ポート競合防止）
    for i in $(seq 1 10); do
        kill -0 "$PID" 2>/dev/null || break
        sleep 0.5
    done
    echo "mitmproxy stopped (PID: ${PID})"
else
    echo "Process ${PID} not found. Cleaning up PID file."
fi

rm -f "$PID_FILE"
