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

exec sleep infinity
