#!/usr/bin/env bash
# scripts/dogfood-dashboard.sh
#
# Sprint 007 (ADR 0004) の dashboard を maintainer が手元で smoke するための
# 補助 script。隔離 venv で zoo init → build → up --dashboard-only まで自動、
# CSP / inline asset / CDN 不在の自動検証も実施し、最後に URL を表示して
# user に目視確認を促す。
#
# 使い方:
#   ./scripts/dogfood-dashboard.sh                  # /tmp/zoo-trial で実施
#   ./scripts/dogfood-dashboard.sh /tmp/my-trial    # 場所を指定
#   ./scripts/dogfood-dashboard.sh --no-build       # 既に build 済の image を再利用
#   ./scripts/dogfood-dashboard.sh --cleanup-only   # zoo down + workspace 削除のみ
#
# 前提:
#   - macOS or Linux
#   - Docker Desktop 起動中 (zoo build に必須)
#   - Python 3.11+
#   - 本 script を repo root から実行 (REPO_ROOT 自動検出)
#
# 検証観点 (#31 コメント参照):
#   A. UI 表示 / B. Network CDN 不在 / C. CSP 厳格化 / D. Console error /
#   E. Elements inline 不在 / F. 動作テスト
#   うち B/C/E の一部 (Network 0 件 / CSP value / inline 検出) は curl + grep
#   で自動化、A/D/F は user 目視。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${1:-/tmp/zoo-trial}"
DASHBOARD_URL="http://127.0.0.1:8080"

# ---------- color helpers ----------
if [ -t 1 ]; then
  C_GREEN='\033[0;32m'; C_RED='\033[0;31m'; C_YELLOW='\033[0;33m'
  C_BLUE='\033[0;34m'; C_RESET='\033[0m'
else
  C_GREEN=; C_RED=; C_YELLOW=; C_BLUE=; C_RESET=
fi

ok()    { echo -e "${C_GREEN}✓${C_RESET} $*"; }
fail()  { echo -e "${C_RED}✗${C_RESET} $*"; }
warn()  { echo -e "${C_YELLOW}⚠${C_RESET} $*"; }
info()  { echo -e "${C_BLUE}→${C_RESET} $*"; }

# ---------- arg parse ----------
SKIP_BUILD=0
CLEANUP_ONLY=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --no-build)     SKIP_BUILD=1 ;;
    --cleanup-only) CLEANUP_ONLY=1 ;;
    --help|-h)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *) ARGS+=("$arg") ;;
  esac
done
WORKSPACE="${ARGS[0]:-$WORKSPACE}"

# ---------- preflight ----------
preflight() {
  command -v python3 >/dev/null || { fail "python3 not found"; exit 1; }
  command -v docker  >/dev/null || { fail "docker not found"; exit 1; }
  docker info >/dev/null 2>&1 || { fail "docker daemon not running"; exit 1; }
  ok "python3 + docker daemon OK"
}

# ---------- cleanup ----------
do_cleanup() {
  if [ -d "$WORKSPACE/.zoo" ]; then
    info "stopping containers..."
    if [ -d "$WORKSPACE/.venv" ]; then
      # shellcheck disable=SC1091
      source "$WORKSPACE/.venv/bin/activate"
      (cd "$WORKSPACE" && zoo down 2>/dev/null) || true
      deactivate || true
    else
      (cd "$WORKSPACE/.zoo" && docker compose down 2>/dev/null) || true
    fi
  fi
  if [ "$CLEANUP_ONLY" -eq 1 ]; then
    info "removing workspace $WORKSPACE..."
    rm -rf "$WORKSPACE"
    ok "cleanup done"
  fi
}

if [ "$CLEANUP_ONLY" -eq 1 ]; then
  do_cleanup
  exit 0
fi

# ---------- main ----------
preflight

# Step 1: workspace + venv
info "Step 1: workspace + venv ($WORKSPACE)"
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ok ".venv created"
else
  ok ".venv exists, reuse"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Step 2: install zoo (editable)
info "Step 2: pip install -e $REPO_ROOT"
pip install -q -e "$REPO_ROOT" >/dev/null
ok "zoo CLI installed: $(which zoo)"

# Step 3: zoo init
if [ ! -f ".zoo/docker-compose.yml" ]; then
  info "Step 3: zoo init"
  zoo init
  ok "zoo init done"
else
  ok ".zoo/ already initialized, reuse"
fi

# Step 4: zoo build
if [ "$SKIP_BUILD" -eq 0 ]; then
  info "Step 4: zoo build --agent claude (5〜10 min on first run)"
  zoo build --agent claude
  ok "zoo build done"
else
  warn "skipping build (--no-build)"
fi

# Step 5: zoo up --dashboard-only
info "Step 5: zoo up --dashboard-only"
zoo up --dashboard-only

# wait for dashboard
info "waiting for dashboard at $DASHBOARD_URL ..."
for i in $(seq 1 30); do
  if curl -fsS -o /dev/null "$DASHBOARD_URL/"; then
    ok "dashboard up after ${i}s"
    break
  fi
  if [ "$i" -eq 30 ]; then
    fail "dashboard did not respond in 30s"
    docker compose -f .zoo/docker-compose.yml logs --tail=30 dashboard || true
    exit 1
  fi
  sleep 1
done

# ---------- automated checks ----------
echo
info "=== automated checks (#31 観点 B/C/E 自動部分) ==="

PASS=0
FAIL=0
check() {
  local name="$1"; shift
  if "$@"; then
    ok "$name"
    PASS=$((PASS+1))
  else
    fail "$name"
    FAIL=$((FAIL+1))
  fi
}

# tmp file to inspect
TMP_HEADERS=$(mktemp)
TMP_BODY=$(mktemp)
trap 'rm -f "$TMP_HEADERS" "$TMP_BODY"' EXIT

curl -fsS -D "$TMP_HEADERS" -o "$TMP_BODY" "$DASHBOARD_URL/"

# B. Network 確認: HTML body に CDN URL が無い
check "B. body に cdn.jsdelivr.net が含まれない" \
  bash -c "! grep -q 'cdn.jsdelivr.net' '$TMP_BODY'"
check "B. body に unpkg.com が含まれない" \
  bash -c "! grep -q 'unpkg.com' '$TMP_BODY'"
check "B. /static/app.css が 200 で配信される" \
  bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' '$DASHBOARD_URL/static/app.css')\" = '200' ]"
check "B. /static/app.js が 200 で配信される" \
  bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' '$DASHBOARD_URL/static/app.js')\" = '200' ]"

# C. CSP 確認 (Response Headers)
CSP=$(grep -i '^content-security-policy:' "$TMP_HEADERS" | sed 's/^[^:]*: *//')
PERMS=$(grep -i '^permissions-policy:' "$TMP_HEADERS" | sed 's/^[^:]*: *//')
check "C. CSP header が存在" \
  bash -c "[ -n \"\$(grep -i content-security-policy '$TMP_HEADERS')\" ]"
check "C. CSP に 'unsafe-inline' が含まれない" \
  bash -c "! echo '$CSP' | grep -q \"'unsafe-inline'\""
check "C. CSP に cdn.jsdelivr.net が含まれない" \
  bash -c "! echo '$CSP' | grep -q 'cdn.jsdelivr.net'"
check "C. CSP に unpkg.com が含まれない" \
  bash -c "! echo '$CSP' | grep -q 'unpkg.com'"
check "C. CSP に default-src 'self' が含まれる" \
  bash -c "echo \"$CSP\" | grep -q \"default-src 'self'\""
check "C. CSP に form-action 'self' が含まれる" \
  bash -c "echo \"$CSP\" | grep -q \"form-action 'self'\""
check "C. Permissions-Policy が camera/microphone/geolocation/payment を deny" \
  bash -c "echo \"$PERMS\" | grep -q 'camera=()' && echo \"$PERMS\" | grep -q 'microphone=()' && echo \"$PERMS\" | grep -q 'geolocation=()' && echo \"$PERMS\" | grep -q 'payment=()'"
check "C. X-Frame-Options: DENY" \
  bash -c "grep -i 'x-frame-options:' '$TMP_HEADERS' | grep -qi 'deny'"
check "C. X-Content-Type-Options: nosniff" \
  bash -c "grep -i 'x-content-type-options:' '$TMP_HEADERS' | grep -qi 'nosniff'"
check "C. Referrer-Policy: no-referrer" \
  bash -c "grep -i 'referrer-policy:' '$TMP_HEADERS' | grep -qi 'no-referrer'"

# E. inline assets 不在 (簡易、Python+bs4 の方が硬いが grep で十分検出可能)
check "E. body に <style> タグが含まれない" \
  bash -c "! grep -qi '<style' '$TMP_BODY'"
check "E. body に onclick= 属性が含まれない" \
  bash -c "! grep -qi ' onclick=' '$TMP_BODY'"
check "E. body に inline style= 属性が含まれない" \
  bash -c "! grep -qi ' style=' '$TMP_BODY'"
check "E. <meta name=\"csrf-token\"> が存在" \
  bash -c "grep -q 'meta name=\"csrf-token\"' '$TMP_BODY'"
check "E. hx-* 属性が body から完全削除済" \
  bash -c "! grep -qE ' hx-[a-z-]+=' '$TMP_BODY'"

echo
echo -e "================================="
echo -e "  ${C_GREEN}PASS: $PASS${C_RESET}   ${C_RED}FAIL: $FAIL${C_RESET}"
echo -e "================================="

if [ "$FAIL" -gt 0 ]; then
  warn "automated checks に失敗あり、上記詳細を確認してください"
  echo
fi

# ---------- 目視 prompt ----------
echo
info "=== 目視確認をブラウザで実施してください ==="
echo
echo "  Open: ${C_BLUE}$DASHBOARD_URL${C_RESET}"
echo
echo "  チェック項目 (#31 コメント参照):"
echo "    A. UI 表示 (Agent Zoo 見出し / 4 stat card / tab nav 4 個)"
echo "    D. DevTools Console に赤い error が 0 件"
echo "    F. Inbox tab で「未承認のリクエストはありません」/ Whitelist tab で表 / Filter dropdown 動作"
echo
echo "  確認終了後の cleanup:"
echo "    $0 --cleanup-only ${WORKSPACE}"
echo
ok "dogfood ready ($WORKSPACE)"
