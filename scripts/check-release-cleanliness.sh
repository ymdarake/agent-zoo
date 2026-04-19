#!/usr/bin/env bash
# scripts/check-release-cleanliness.sh
#
# リリース前に「変な混ざりもの」が git track 済ファイルに含まれていないか
# を一括検査する maintainer 向けスクリプト。CI に組み込んでも、手元で
# 単発実行しても OK。
#
# 検査区分:
#   [CRITICAL] 必ず fail させる (秘密情報の流出、個人 PII、credentials)
#   [WARNING]  報告のみ、exit 0 のまま (許容ケースが文脈で判断必要)
#
# 使い方:
#   ./scripts/check-release-cleanliness.sh           # repo 全体を検査
#   ./scripts/check-release-cleanliness.sh --strict  # WARNING も fail 扱い
#   ./scripts/check-release-cleanliness.sh -v        # 各 check の詳細表示
#   ./scripts/check-release-cleanliness.sh --extra-pii 'foo@example.com|alice|/Users/alice'
#                                                    # 追加 PII pattern (regex、| で OR)
#
# env でも渡せる (CI / dotenv 用):
#   EXTRA_PII_PATTERNS='foo@example.com|alice' ./scripts/check-release-cleanliness.sh
#
# 注: 本 script 自体に固有名 (maintainer 名 / email) を hardcode しない。
#     hardcode するとその script ファイル自体が「汚れ」検出対象になる。

set -uo pipefail
# 注: set -e は外す。grep が "no match" で exit 1 を返す場面があり、
#     check 関数内でその exit を意図的に「ヒットなし = OK」として扱う。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

STRICT=0
VERBOSE=0
EXTRA_PII_PATTERNS="${EXTRA_PII_PATTERNS:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --strict) STRICT=1 ;;
    -v|--verbose) VERBOSE=1 ;;
    --extra-pii) shift; EXTRA_PII_PATTERNS="$1" ;;
    --extra-pii=*) EXTRA_PII_PATTERNS="${1#*=}" ;;
    --help|-h)
      sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
  shift
done

if [ -t 1 ]; then
  C_RED='\033[0;31m'; C_YELLOW='\033[0;33m'; C_GREEN='\033[0;32m'
  C_BLUE='\033[0;34m'; C_RESET='\033[0m'
else
  C_RED=; C_YELLOW=; C_GREEN=; C_BLUE=; C_RESET=
fi

# bash 3.2 + TTY で `echo_color` が ANSI escape をリテラル出力する問題回避用 helper
# (macOS default bash 3.2 の builtin echo は -e 解釈が不安定)
echo_color() { printf '%b\n' "$*"; }

# git branch --show-current は git 2.22+ 必要、古い git では空文字 → fallback
current_branch() {
  git symbolic-ref --short HEAD 2>/dev/null || echo "(detached)"
}

CRITICAL=0
WARNING=0

# 各 check の実装パターン:
#   1. matches を変数に集める (改行区切り)
#   2. 件数 0 → ✓ green、件数 >0 → ✗ red (CRITICAL) or ⚠ yellow (WARNING)
#   3. -v で matches 詳細出力

run_critical() {
  local name="$1" matches="$2"
  if [ -z "$matches" ]; then
    echo_color "${C_GREEN}✓${C_RESET} [CRITICAL] $name"
  else
    local count
    count=$(echo "$matches" | wc -l | tr -d ' ')
    echo_color "${C_RED}✗${C_RESET} [CRITICAL] $name ($count files)"
    echo "$matches" | sed 's/^/    /'
    CRITICAL=$((CRITICAL + 1))
  fi
}

run_warning() {
  local name="$1" matches="$2"
  if [ -z "$matches" ]; then
    echo_color "${C_GREEN}✓${C_RESET} [WARNING ] $name"
  else
    local count
    count=$(echo "$matches" | wc -l | tr -d ' ')
    echo_color "${C_YELLOW}⚠${C_RESET} [WARNING ] $name ($count files)"
    [ "$VERBOSE" -eq 1 ] && echo "$matches" | sed 's/^/    /'
    WARNING=$((WARNING + 1))
  fi
}

echo_color "${C_BLUE}=== Release Cleanliness Audit (agent-zoo) ===${C_RESET}"
echo "  repo: $REPO_ROOT"
echo "  branch: $(current_branch)"
echo "  HEAD: $(git rev-parse --short HEAD)"
echo

# =================================================================
# CRITICAL CHECKS
# =================================================================

# helper: BSD/GNU 共通で「空入力時に xargs が grep を呼ばない」を保証
# git ls-files は通常非空だが、念のため /dev/null を引数に追加して
# 空入力時の grep ハング (BSD xargs に -r 無し) を回避。
safe_grep_l() {
  local pattern="$1"; shift
  # 引数があれば対象 ls-files、なければ全 ls-files
  if [ "$#" -gt 0 ]; then
    git ls-files "$@" 2>/dev/null
  else
    git ls-files
  fi | xargs grep -lE "$pattern" /dev/null 2>/dev/null || true
}

# C1: 秘密パターン
# - PRIVATE KEY block: 確実な検出 (RFC 4716 / PEM 形式)
# - api/secret/password: quote で囲まれた実値 + length >=8 + placeholder 除外で
#   false positive 抑制 (Plan review High: REPLACE_ME / DUMMY / YOUR_ 等の placeholder
#   は NG)
matches=$(safe_grep_l "BEGIN (RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY" \
  | grep -vE "(test_|/tests/|docs/|CHANGELOG|README|/security-notes)" || true)
matches2=$(safe_grep_l "(api[_-]?key|secret[_-]?key|password|passwd)['\"]?\s*[:=]\s*['\"][^'\"\\\$]{8,}['\"]" \
  | xargs grep -lE "(api[_-]?key|secret[_-]?key|password|passwd)['\"]?\s*[:=]\s*['\"][^'\"\\\$]{8,}['\"]" /dev/null 2>/dev/null \
  | xargs grep -LiE "(REPLACE_?ME|YOUR_|DUMMY|EXAMPLE|PLACEHOLDER|XXXXX|<.*>)" /dev/null 2>/dev/null \
  | grep -vE "(test_|/tests/|docs/|CHANGELOG|README|/security-notes|check-release-cleanliness)" || true)
combined=$(printf '%s\n%s\n' "$matches" "$matches2" | grep -v '^$' | sort -u || true)
run_critical "credential-like strings (private key blocks / hardcoded api/secret/password)" "$combined"

# C2: 認証ファイル拡張子 + 拡張子無し SSH key 名
# - 拡張子: .pem / .key / .env / .p12 / .pfx / .crt / .jks / .p7b
# - basename: id_rsa / id_dsa / id_ecdsa / id_ed25519 / authorized_keys / known_hosts
# 例外: docs/ 配下の説明用は手動許可
matches=$(git ls-files \
  | grep -vE "^docs/" \
  | grep -E "(\.(pem|key|env|p12|pfx|crt|jks|p7b)$|(^|/)(id_(rsa|dsa|ecdsa|ed25519)|authorized_keys|known_hosts)$)" \
  || true)
run_critical "credential file extensions (.pem/.key/.env/.p12/.pfx/.crt/.jks + SSH key names)" "$matches"

# C3: 個人 PII (generic な home dir path + 追加パターンを env / arg で受け取る)
# 本 script は固有名を hardcode しない。CI で env、ローカルで --extra-pii arg で渡す。
# generic pattern: /Users/<user>/(workspace|projects|src|Desktop|Documents|Downloads|.ssh) と /home/<user>/...
PII_PATTERN="(/Users|/home)/[a-z][a-zA-Z0-9._-]*/(workspace|projects|src|Desktop|Documents|Downloads|\.ssh)"
if [ -n "$EXTRA_PII_PATTERNS" ]; then
  PII_PATTERN="${PII_PATTERN}|${EXTRA_PII_PATTERNS}"
fi
matches=$(safe_grep_l "$PII_PATTERN" || true)
run_critical "personal PII (hardcoded user paths; pass --extra-pii to add custom patterns)" "$matches"

# C4: cloud / SaaS / CI token patterns
# - AWS access key / GitHub PAT / OpenAI sk- / Anthropic sk-ant- / Claude OAuth
# - Slack token (xox{b,p,a,s}-) / Stripe live (sk_live_, pk_live_, rk_live_)
# - GitLab PAT (glpat-) / Google API (AIza)
# - JWT (eyJ で始まる 3-part base64)
# - Generic Bearer token (Authorization header sample)
TOKEN_PATTERN="(AKIA[0-9A-Z]{16}"             # AWS
TOKEN_PATTERN="${TOKEN_PATTERN}|gh[ps]_[A-Za-z0-9]{30,}"  # GitHub PAT (length 30+ で false positive 抑制)
TOKEN_PATTERN="${TOKEN_PATTERN}|sk-ant-api03-[A-Za-z0-9_-]{30,}"  # Anthropic real key
TOKEN_PATTERN="${TOKEN_PATTERN}|sk-[A-Za-z0-9]{30,}"      # OpenAI / Anthropic legacy
TOKEN_PATTERN="${TOKEN_PATTERN}|claude_oauth_[A-Za-z0-9]{20,}"  # Claude OAuth (本リポ独自)
TOKEN_PATTERN="${TOKEN_PATTERN}|xox[bpas]-[0-9]{10,}-[A-Za-z0-9]{10,}"  # Slack
TOKEN_PATTERN="${TOKEN_PATTERN}|[rsp]k_live_[0-9A-Za-z]{24,}"  # Stripe
TOKEN_PATTERN="${TOKEN_PATTERN}|glpat-[A-Za-z0-9_-]{20,}"  # GitLab PAT
TOKEN_PATTERN="${TOKEN_PATTERN}|AIza[0-9A-Za-z_-]{35}"     # Google API
TOKEN_PATTERN="${TOKEN_PATTERN}|eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_.+/=-]+)"  # JWT
matches=$(safe_grep_l "$TOKEN_PATTERN" \
  | grep -vE "(check-release-cleanliness|/tests/|test_)" || true)
run_critical "cloud / SaaS / CI token patterns (AWS/GitHub/OpenAI/Anthropic/Slack/Stripe/GitLab/GCP/JWT)" "$matches"

# =================================================================
# WARNING CHECKS
# =================================================================

# W1: dev artifacts (本来 .gitignore で除外されるべき残骸)
matches=$(git ls-files | grep -E "(\.DS_Store$|__pycache__|\.pyc$|\.pytest_cache|\.ipynb_checkpoints|\.coverage$|node_modules/)" || true)
run_warning "dev artifacts in tracked files (.DS_Store / __pycache__ / .pyc / etc)" "$matches"

# W2: tmp / backup
matches=$(git ls-files | grep -E "(\.swp$|\.swo$|\.bak$|\.orig$|\.rej$|~$)" || true)
run_warning "tmp / backup files (.swp/.bak/.orig/.rej/~)" "$matches"

# W3: AI tool metadata (Claude / Cursor / Aider 等の作業 dir が誤コミット)
matches=$(git ls-files | grep -E "^(\.claude/|\.cursor/|\.windsurf/|\.aider)" || true)
run_warning "AI tool metadata directories (.claude / .cursor / .windsurf / .aider)" "$matches"

# W4: 大きいファイル (> 500KB)
# docs/images/* は意図的なスクショ等で許容、それ以外を warn
matches=$(git ls-files | while read -r f; do
  [ -f "$f" ] || continue
  sz=$(wc -c < "$f" 2>/dev/null || echo 0)
  if [ "$sz" -gt 500000 ]; then
    echo "$sz $f"
  fi
done | sort -rn | head -20)
# format: "size path" → path のみ抜き出して count
matches_paths=$(echo "$matches" | awk 'NF{print $2}')
run_warning "large files (>500KB) — review each (docs/images may be intentional)" "$matches_paths"
[ -n "$matches" ] && [ "$VERBOSE" -eq 1 ] && {
  echo "    sizes:"
  echo "$matches" | awk 'NF{printf "      %s KB  %s\n", int($1/1024), $2}'
}

# W5: TODO / FIXME / XXX (release 直前に残ってると気になる、件数のみ報告)
# 除外: CHANGELOG/BACKLOG/docs/tests/README/本 script 自体 (説明文に keyword 含む)
# safe_grep_l 経由で BSD xargs ハング回避
matches=$(safe_grep_l "(TODO|FIXME|XXX)\b" '*.py' '*.md' '*.sh' '*.toml' '*.yml' '*.yaml' \
  | grep -vE "(CHANGELOG|BACKLOG|docs/dev/|docs/plans/|test_|/tests/|README|check-release-cleanliness)" || true)
run_warning "TODO/FIXME/XXX in production code (CHANGELOG/BACKLOG/docs/tests/README excluded)" "$matches"

# =================================================================
# SUMMARY
# =================================================================

echo
echo "================================="
if [ "$CRITICAL" -gt 0 ]; then
  echo_color "  ${C_RED}CRITICAL: $CRITICAL${C_RESET} (BLOCKS release)"
fi
if [ "$WARNING" -gt 0 ]; then
  echo_color "  ${C_YELLOW}WARNING:  $WARNING${C_RESET} (review recommended)"
fi
if [ "$CRITICAL" -eq 0 ] && [ "$WARNING" -eq 0 ]; then
  echo_color "  ${C_GREEN}ALL CLEAN${C_RESET}"
fi
echo "================================="

if [ "$CRITICAL" -gt 0 ]; then
  exit 2
fi
if [ "$STRICT" -eq 1 ] && [ "$WARNING" -gt 0 ]; then
  exit 1
fi
exit 0
