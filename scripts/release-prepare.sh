#!/usr/bin/env bash
# scripts/release-prepare.sh — バージョンアップ作業の自動化 (issue #68 補助ツール)
#
# Usage:
#   ./scripts/release-prepare.sh <VERSION>             # 本実行
#   ./scripts/release-prepare.sh --dry-run <VERSION>   # 副作用なしで事前検証
#
# 例: ./scripts/release-prepare.sh 0.1.0b1
#     ./scripts/release-prepare.sh --dry-run 0.2.0
#
# 実施内容 (本実行):
#   1. VERSION が PEP 440 native public version であることを regex で検証
#      (.github/workflows/release.yml の classify step と同一 spec。
#       leading zero / dash 形 / dot 形 は reject)
#   2. working tree clean 確認
#   3. 現 branch が main であることを確認 (非 main は TTY 時のみ confirm、
#      非 TTY は abort — CI / pipe での意図せぬ誤発火を防ぐ)
#   4. tag `v<VERSION>` が未存在であることを確認
#   5. pyproject.toml の [project].version を VERSION に書き換え
#      (Python re.sub で section-aware、他の `version = "..."` は触らない)
#   6. tomllib で read-back verify (書き換え結果が期待値と一致)
#   7. commit (`:bookmark: release: v<VERSION>`) + tag `v<VERSION>`
#      失敗時は pyproject.toml を rollback
#   8. 次に実行すべき push コマンドと recovery 手順を echo
#
# push は意図的に行わない (destructive action を user 明示確認に委ねる)。
# release workflow の実際の発火は tag push (`git push --follow-tags`) 後。

set -euo pipefail

# ---------- 引数 parse ----------

DRY_RUN=false
VERSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            sed -n '2,31p' "$0" | sed 's/^# //; s/^#//'
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

if [[ -z "$VERSION" ]]; then
    cat >&2 <<EOF
Usage: $0 [--dry-run] <VERSION>

例:
  $0 0.1.0           # stable (prd PyPI + GitHub Release)
  $0 0.1.0b1         # pre-release (TestPyPI only)
  $0 --dry-run 0.2.0 # 副作用なしで事前検証

VERSION は PEP 440 native public version:
  stable:       X.Y.Z
  pre-release:  X.Y.Z(a|b|rc)N  (N に leading zero は不可)
EOF
    exit 1
fi

# ---------- 1. VERSION format check ----------
# release.yml の classify step と同じ spec (prefix `v` は script 側で剥く)。
# (0|[1-9][0-9]*) で leading zero を reject (PyPI 正規化衝突対策)。
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

# pre-release / stable 分類 (echo 用、logic には使わない)
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
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" ]]; then
    # 非 TTY + CI env は confirm 無効化 → abort (CI / pipe で誤発火しない belt-and-suspenders)
    if [[ ! -t 0 ]] || [[ -n "${CI:-}" ]]; then
        echo "::error::current branch is '$BRANCH' (not main) and non-interactive environment (stdin=non-TTY or CI=${CI:-unset})." >&2
        echo "非対話環境では main 以外からの release を自動 abort します (事故防止)。" >&2
        exit 1
    fi
    echo "warning: current branch is '$BRANCH' (typically release from 'main')" >&2
    read -r -p "continue anyway? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { echo "aborted by user" >&2; exit 1; }
fi

# ---------- 4. tag 未存在確認 ----------
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null 2>&1; then
    echo "::error::tag 'v$VERSION' already exists. Delete it first (git tag -d v$VERSION) or bump VERSION." >&2
    exit 1
fi

# ---------- (dry-run 限定) pyproject との整合 ----------
# 本実行は後段で pyproject を書き換えるので事前整合は不要だが、dry-run は
# 書き換えない前提で「現 pyproject == VERSION」か確認して整合を知らせる。
if $DRY_RUN; then
    CURRENT=$(python3 -c 'import tomllib,pathlib,sys; \
data=tomllib.loads(pathlib.Path("pyproject.toml").read_text()); \
print(data.get("project",{}).get("version",""))')
    if [[ -z "$CURRENT" ]]; then
        echo "::error::pyproject.toml has no static project.version (dynamic version は未対応)" >&2
        exit 1
    fi
    if [[ "$CURRENT" != "$VERSION" ]]; then
        cat >&2 <<EOF
::error::dry-run: pyproject.toml project.version = '$CURRENT' but VERSION='$VERSION'.
本実行 ($0 $VERSION) では pyproject.toml を $VERSION に書き換えて commit します。
先に pyproject.toml を手動 bump したい場合は dry-run 通過のため一致させてから実行してください。
EOF
        exit 1
    fi
    echo "dry-run OK: v$VERSION ($KIND) matches pyproject.toml, working tree clean, tag not yet exists."
    exit 0
fi

# ---------- 5. pyproject.toml の [project].version を書き換え ----------
# sed は TOML の section-aware 書き換えに弱い ([tool.foo] section 内の
# `version = "..."` を誤爆する恐れ) ので Python で [project] section の
# 範囲を明示的に切り出し、その中の最初の `^version = "..."` を置換する。
# encoding を明示し CRLF→LF 等の silent 書き換えを避ける。
python3 - "$VERSION" <<'PY'
import pathlib
import re
import sys

new_version = sys.argv[1]
path = pathlib.Path("pyproject.toml")
# UTF-8 + newline="" で改行そのまま保持 (CRLF repo で LF 強制書換を避ける)
src = path.read_text(encoding="utf-8")

# [project] section の range を先に見つける:
#   開始: ^\[project\]\s*$
#   終了: 次の ^\[...\] section header の直前、または EOF
lines = src.splitlines(keepends=True)
start = None
end = len(lines)
section_header = re.compile(r"^\[[^\]]+\]\s*$")
for i, line in enumerate(lines):
    if line.rstrip("\r\n") == "[project]":
        start = i + 1  # [project] の次行から
    elif start is not None and section_header.match(line):
        end = i
        break
if start is None:
    sys.exit("::error::pyproject.toml: [project] section が見つからない")

# [project] section 内の最初の `version = "..."` を置換。
# lambda 化して new_version 内の `\1` 等の後方参照 escape を無効化。
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

# ---------- 7. commit + tag (rollback guard) ----------
# commit 失敗 (pre-commit hook 等) や SIGINT / SIGTERM で pyproject.toml /
# index を HEAD に戻して半端な state を残さない。
# `git checkout HEAD -- ./` で index + worktree 両方を復元、
# `./` prefix で branch 名との曖昧さ回避。
_rollback() {
    git checkout HEAD -- ./pyproject.toml 2>/dev/null || true
}
trap _rollback ERR INT TERM

git add ./pyproject.toml

# pyproject.toml が既に VERSION だった場合 (本実行 VERSION と pyproject 初期値が
# 一致しているケース) は staged diff が空になる → 通常 commit は失敗する。
# --allow-empty で「release アンカー」commit として扱う (maintainer 意図:
# pyproject が既に bump 済 + tag だけ打ちたい / 再現可能な release 点)。
if git diff --cached --quiet; then
    echo "note: pyproject.toml already at v$VERSION, creating empty release-anchor commit" >&2
    git commit --allow-empty -q -m ":bookmark: release: v$VERSION"
else
    git commit -q -m ":bookmark: release: v$VERSION"
fi

git tag "v$VERSION"

trap - ERR INT TERM

# ---------- 8. 次手順の案内 ----------
cat <<EOF

Created commit + tag locally: v$VERSION ($KIND)

Next step — push to trigger GitHub Actions release workflow:
  git push origin $BRANCH --follow-tags

To undo (local only, push 前なら安全):
  git tag -d v$VERSION && git reset --hard HEAD^
EOF
