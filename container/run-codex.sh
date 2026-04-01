#!/bin/bash
set -euo pipefail

MODE="${1:-interactive}"
HARNESS_FILE="${CODEX_HARNESS_FILE:-/harness/CODEX.harness.md}"
USER_PROMPT="${USER_PROMPT:-}"

HARNESS_PROMPT=""
if [ -f "$HARNESS_FILE" ]; then
  HARNESS_PROMPT="$(cat "$HARNESS_FILE")"
fi

PROMPT="$HARNESS_PROMPT"
if [ -n "$USER_PROMPT" ]; then
  if [ -n "$PROMPT" ]; then
    PROMPT="${PROMPT}

User task:
${USER_PROMPT}"
  else
    PROMPT="$USER_PROMPT"
  fi
fi

case "$MODE" in
  interactive)
    if [ -n "$PROMPT" ]; then
      exec codex "$PROMPT"
    fi
    exec codex
    ;;
  interactive-dangerous)
    if [ -n "$PROMPT" ]; then
      exec codex --dangerously-bypass-approvals-and-sandbox "$PROMPT"
    fi
    exec codex --dangerously-bypass-approvals-and-sandbox
    ;;
  task)
    if [ -z "$USER_PROMPT" ]; then
      echo "USER_PROMPT is required in task mode" >&2
      exit 1
    fi
    exec codex exec --dangerously-bypass-approvals-and-sandbox "$PROMPT"
    ;;
  *)
    echo "Usage: run-codex.sh [interactive|interactive-dangerous|task]" >&2
    exit 2
    ;;
esac
