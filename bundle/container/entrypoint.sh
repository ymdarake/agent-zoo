#!/bin/bash
set -e

TIMEOUT=60
COUNT=0

echo "[entrypoint] Waiting for proxy certificates..."
until [ -f /certs/mitmproxy-ca-cert.pem ]; do
  COUNT=$((COUNT + 1))
  if [ "$COUNT" -ge "$TIMEOUT" ]; then
    echo "[entrypoint] ERROR: Timeout waiting for certificates (${TIMEOUT}s)"
    exit 1
  fi
  sleep 1
done
echo "[entrypoint] Certificates found. Ready."

# B-5: HARNESS_RULES.md を agent ごとの慣習名で /workspace に inject
# #27: unified では 3 つ全て inject（cross-agent 呼び出しのため）
HARNESS_FILE="/harness/HARNESS_RULES.md"
if [ -f "$HARNESS_FILE" ]; then
  case "${AGENT_NAME:-}" in
    claude)
      [ -f /workspace/CLAUDE.md ] || cp "$HARNESS_FILE" /workspace/CLAUDE.md 2>/dev/null || true
      ;;
    codex)
      [ -f /workspace/AGENTS.md ] || cp "$HARNESS_FILE" /workspace/AGENTS.md 2>/dev/null || true
      ;;
    gemini)
      [ -f /workspace/GEMINI.md ] || cp "$HARNESS_FILE" /workspace/GEMINI.md 2>/dev/null || true
      ;;
    unified)
      [ -f /workspace/CLAUDE.md ] || cp "$HARNESS_FILE" /workspace/CLAUDE.md 2>/dev/null || true
      [ -f /workspace/AGENTS.md ] || cp "$HARNESS_FILE" /workspace/AGENTS.md 2>/dev/null || true
      [ -f /workspace/GEMINI.md ] || cp "$HARNESS_FILE" /workspace/GEMINI.md 2>/dev/null || true
      ;;
  esac
fi

exec sleep infinity
