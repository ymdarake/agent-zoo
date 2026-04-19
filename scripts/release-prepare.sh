#!/usr/bin/env bash
# scripts/release-prepare.sh — バージョンアップ作業の自動化 (issue #68 補助ツール)
#
# branch-protected main (PR 必須) 運用向けの 2-phase flow。直接 push はしない。
#
# Usage:
#   ./scripts/release-prepare.sh --no-tag <VERSION>       # phase 1: bump + commit (release branch 用)
#   ./scripts/release-prepare.sh --tag-only <VERSION>     # phase 2: HEAD に annotated tag (merge 後 main 用)
#   ./scripts/release-prepare.sh --dry-run --no-tag <V>   # phase 1 の事前検証
#   ./scripts/release-prepare.sh --dry-run --tag-only <V> # phase 2 の事前検証
#
# 運用:
#
#   # phase 1: release branch で bump commit を作る
#   git checkout -b release/v0.1.1b1
#   ./scripts/release-prepare.sh --no-tag 0.1.1b1
#   git push -u origin release/v0.1.1b1
#   # PR を作成 → squash merge
#
#   # phase 2: main で tag 打って push
#   git checkout main && git pull
#   ./scripts/release-prepare.sh --tag-only 0.1.1b1
#   git push origin v0.1.1b1
#
# push は意図的に行わない (destructive action を user 明示確認に委ねる)。

set -euo pipefail

# ---------- 引数 parse ----------

DRY_RUN=false
NO_TAG=false
TAG_ONLY=false
VERSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-tag)
            NO_TAG=true
            shift
            ;;
        --tag-only)
            TAG_ONLY=true
            shift
            ;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# //; s/^#//'
            exit 0
            ;;
        -*)
            echo "::error::unknown flag: $1" >&2
            exit 1
            ;;
        *)
            if [[ -n "$VERSION" ]]; then
                echo "::error::too many positional args (got '$VERSION' and '$1')" >&2
                exit 1
            fi
            VERSION="$1"
            shift
            ;;
    esac
done

if $NO_TAG && $TAG_ONLY; then
    echo "::error::--no-tag and --tag-only are mutually exclusive (排他です)" >&2
    exit 1
fi

if ! $NO_TAG && ! $TAG_ONLY; then
    cat >&2 <<EOF
::error::--no-tag または --tag-only の指定が必要です。

Usage:
  $0 --no-tag <VERSION>      # phase 1: pyproject bump + commit (release branch → PR)
  $0 --tag-only <VERSION>    # phase 2: HEAD に annotated tag (merge 後 main)
  $0 --dry-run [mode] <V>    # 副作用ゼロで事前検証
EOF
    exit 1
fi

if [[ -z "$VERSION" ]]; then
    cat >&2 <<EOF
Usage: $0 --dry-run? {--no-tag | --tag-only} <VERSION>

例:
  $0 --no-tag 0.1.1b1         # phase 1
  $0 --tag-only 0.1.1b1       # phase 2
  $0 --dry-run --no-tag 0.1.1b1

VERSION は PEP 440 native public version:
  stable:       X.Y.Z
  pre-release:  X.Y.Z(a|b|rc)N  (N に leading zero は不可)
EOF
    exit 1
fi

# ---------- 1. VERSION format check ----------
# release.yml の classify step と同じ spec。leading zero reject。
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)(0|[1-9][0-9]*))?$ ]]; then
    cat >&2 <<EOF
::error::VERSION '$VERSION' is not a PEP 440 native public version.
Expected:
  - X.Y.Z           (stable、例: 0.1.0)
  - X.Y.Z(a|b|rc)N  (pre-release、例: 0.1.0b1 / 1.0.0rc1、N に leading zero 不可)
非 native 形 (0.1.0-beta-1 / 0.1.0.post1 / 0.1.0b01 等) は reject します。
EOF
    exit 1
fi

# pre-release / stable 分類 (echo 用)
if [[ "$VERSION" =~ (a|b|rc)[0-9]+$ ]]; then
    KIND="pre-release (TestPyPI only)"
else
    KIND="stable (prd PyPI + GitHub Release)"
fi

# ---------- 2. working tree clean ----------
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "::error::working tree is not clean. Commit or stash changes first." >&2
    git status --short >&2
    exit 1
fi

# ---------- 3. branch check ----------
# --tag-only は main 必須、--no-tag は release branch 前提で main 以外を許可。
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if $TAG_ONLY && [[ "$BRANCH" != "main" ]]; then
    if [[ ! -t 0 ]] || [[ -n "${CI:-}" ]]; then
        echo "::error::--tag-only requires main branch, got '$BRANCH' (non-interactive env abort)." >&2
        exit 1
    fi
    echo "warning: --tag-only on branch '$BRANCH' (typically main after merge)" >&2
    read -r -p "continue anyway? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { echo "aborted by user" >&2; exit 1; }
fi

# ---------- 4. tag 未存在確認 ----------
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null 2>&1; then
    echo "::error::tag 'v$VERSION' already exists locally. Delete it first (git tag -d v$VERSION) or bump VERSION." >&2
    exit 1
fi

# remote tag 既存 check (origin 設定がある場合のみ、test 互換性)
if git remote get-url origin >/dev/null 2>&1; then
    if git ls-remote --tags origin "v$VERSION" 2>/dev/null | grep -q .; then
        echo "::error::tag 'v$VERSION' already exists on origin. Choose a higher VERSION." >&2
        exit 1
    fi
fi

# ============================================================================
# --tag-only: pyproject 触らず、既存 HEAD に annotated tag を打つだけ
# ============================================================================
if $TAG_ONLY; then
    # pyproject.version == VERSION (= bump commit がすでに main に merge 済)
    CURRENT=$(python3 -c 'import tomllib,pathlib; \
print(tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8")).get("project",{}).get("version",""))')
    if [[ -z "$CURRENT" ]]; then
        echo "::error::pyproject.toml has no static project.version (dynamic version は未対応)" >&2
        exit 1
    fi
    if [[ "$CURRENT" != "$VERSION" ]]; then
        cat >&2 <<EOF
::error::--tag-only: pyproject.toml project.version = '$CURRENT' but VERSION='$VERSION'.
bump 済の main に対して tag を打つ運用です。VERSION と pyproject が一致する
commit 上で実行してください (phase 1 の commit が main に merge 済か確認)。
EOF
        exit 1
    fi

    # HEAD commit subject が `release: v<VERSION>` を含むこと (誤 tag 防止、HIGH)
    SUBJECT=$(git log -1 --format=%s HEAD)
    if ! echo "$SUBJECT" | grep -qE "release:[[:space:]]*v?${VERSION//./\\.}([[:space:]]|$)"; then
        cat >&2 <<EOF
::error::--tag-only: HEAD commit subject does not reference 'release: v$VERSION'.
  HEAD subject: $SUBJECT
bump commit を main に merge した直後の HEAD でのみ tag を打ってください。
EOF
        exit 1
    fi

    # HEAD が origin/main と一致 (orphan tag による本番 publish 暴発を防ぐ、HIGH)。
    # origin/main ref が取れない test 環境では skip (warning のみ)。
    if git rev-parse --verify origin/main >/dev/null 2>&1; then
        git fetch -q origin main 2>/dev/null || true
        LOCAL_HEAD=$(git rev-parse HEAD)
        REMOTE_HEAD=$(git rev-parse origin/main)
        if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]]; then
            cat >&2 <<EOF
::error::--tag-only: HEAD ($LOCAL_HEAD) != origin/main ($REMOTE_HEAD).
phase 1 の PR が merge された後、 git checkout main && git pull してから再実行してください。
EOF
            exit 1
        fi
    else
        echo "warning: origin/main ref not found, skipping HEAD == origin/main check (test env?)" >&2
    fi

    if $DRY_RUN; then
        echo "dry-run OK (--tag-only): v$VERSION ($KIND), HEAD subject / pyproject / remote 全整合。"
        exit 0
    fi

    git tag -a "v$VERSION" -m "Release v$VERSION"

    cat <<EOF

Created annotated tag locally: v$VERSION ($KIND)

Next step — push the tag to trigger GitHub Actions release workflow:
  git push origin v$VERSION

To undo (local only, push 前なら安全):
  git tag -d v$VERSION
EOF
    exit 0
fi

# ============================================================================
# --no-tag: pyproject bump + commit のみ (release branch → PR 用)
# ============================================================================

# dry-run は format / working tree / tag 未存在だけ確認、pyproject は触らない
if $DRY_RUN; then
    CURRENT=$(python3 -c 'import tomllib,pathlib; \
print(tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8")).get("project",{}).get("version",""))')
    if [[ -z "$CURRENT" ]]; then
        echo "::error::pyproject.toml has no static project.version (dynamic version は未対応)" >&2
        exit 1
    fi
    echo "dry-run OK (--no-tag): v$VERSION ($KIND), working tree clean, tag not yet exists. pyproject will be bumped from '$CURRENT' to '$VERSION'."
    exit 0
fi

# ---------- 5. pyproject.toml の [project].version を書き換え ----------
python3 - "$VERSION" <<'PY'
import pathlib
import re
import sys

new_version = sys.argv[1]
path = pathlib.Path("pyproject.toml")
src = path.read_text(encoding="utf-8")

# [project] section の range を先に見つける
lines = src.splitlines(keepends=True)
start = None
end = len(lines)
section_header = re.compile(r"^\[[^\]]+\]\s*$")
for i, line in enumerate(lines):
    if line.rstrip("\r\n") == "[project]":
        start = i + 1
    elif start is not None and section_header.match(line):
        end = i
        break
if start is None:
    sys.exit("::error::pyproject.toml: [project] section が見つからない")

version_re = re.compile(r'^(version\s*=\s*")([^"]*)(")')
for i in range(start, end):
    m = version_re.match(lines[i])
    if m:
        lines[i] = version_re.sub(
            lambda _, nv=new_version: f'{m.group(1)}{nv}{m.group(3)}',
            lines[i],
            count=1,
        )
        break
else:
    sys.exit(
        "::error::pyproject.toml: [project].version line not found "
        "(dynamic version は未対応)"
    )

path.write_text("".join(lines), encoding="utf-8")
PY

# ---------- 6. read-back verify ----------
ACTUAL=$(python3 -c 'import tomllib,pathlib; \
print(tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])')
if [[ "$ACTUAL" != "$VERSION" ]]; then
    git checkout HEAD -- ./pyproject.toml
    echo "::error::pyproject write did not produce expected version (got '$ACTUAL' expected '$VERSION')" >&2
    exit 1
fi

# ---------- 7. commit (rollback guard) ----------
_rollback() {
    git checkout HEAD -- ./pyproject.toml 2>/dev/null || true
}
trap _rollback ERR INT TERM

git add ./pyproject.toml

if git diff --cached --quiet; then
    echo "note: pyproject.toml already at v$VERSION, creating empty release-anchor commit" >&2
    git commit --allow-empty -q -m ":bookmark: release: v$VERSION"
else
    git commit -q -m ":bookmark: release: v$VERSION"
fi

trap - ERR INT TERM

# ---------- 8. 次手順の案内 ----------
cat <<EOF

Created bump commit locally (no tag): v$VERSION ($KIND)

Next step — release branch フローで main に merge 後、別途 tag を打つ:
  git push -u origin $BRANCH
  gh pr create --title ":bookmark: release: v$VERSION" --template release.md
  # ... PR 上で release checklist (CHANGELOG / pyproject / TestPyPI / PyPI) を確認 → squash merge ...
  git checkout main && git pull
  ./scripts/release-prepare.sh --tag-only $VERSION
  git push origin v$VERSION

To undo (local only, push 前なら安全):
  git reset --hard HEAD^
EOF
