#!/bin/bash
set -e

HARNESS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CERTS_DIR="${HARNESS_DIR}/certs"
DATA_DIR="${HARNESS_DIR}/data"
PID_FILE="${DATA_DIR}/.mitmproxy.pid"

# 既に起動中か確認
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "mitmproxy is already running (PID: ${PID}). Stop with: host/stop.sh"
        exit 1
    fi
    rm -f "$PID_FILE"
fi

# mitmproxyのインストール確認
if ! command -v mitmdump &> /dev/null; then
    echo "mitmproxy not found. Install with: brew install mitmproxy"
    exit 1
fi

mkdir -p "$DATA_DIR"

# 証明書の存在確認（なければ生成）
if [ ! -f "${CERTS_DIR}/mitmproxy-ca-cert.pem" ]; then
    echo "Generating mitmproxy CA certificate..."
    mkdir -p "$CERTS_DIR"
    mitmdump --set confdir="${CERTS_DIR}" &
    MITM_PID=$!
    for i in $(seq 1 10); do [ -f "${CERTS_DIR}/mitmproxy-ca-cert.pem" ] && break; sleep 1; done
    kill "$MITM_PID" 2>/dev/null || true
    wait "$MITM_PID" 2>/dev/null || true
    echo "Certificate generated."
fi

# mitmproxyをバックグラウンドで起動
echo "Starting mitmproxy on localhost:8080..."
POLICY_PATH="${HARNESS_DIR}/policy.toml" mitmdump \
    -s "${HARNESS_DIR}/addons/policy_enforcer.py" \
    --set confdir="${CERTS_DIR}" \
    --listen-port 8080 &
MITM_PID=$!
sleep 1
if ! kill -0 "$MITM_PID" 2>/dev/null; then
    echo "ERROR: mitmproxy failed to start"
    exit 1
fi
echo "$MITM_PID" > "$PID_FILE"

echo ""
echo "=== Host Mode Active ==="
echo "mitmproxy PID: ${MITM_PID}"
echo "Proxy: http://127.0.0.1:8080"
echo "Logs:  ${DATA_DIR}/harness.db"
echo ""
echo "Stop with: make host-stop"
echo ""
echo "Configure Claude Code srt-settings.json:"
echo "  {\"customProxy\": {\"url\": \"http://127.0.0.1:8080\", \"caCertPath\": \"${CERTS_DIR}/mitmproxy-ca-cert.pem\"}}"
