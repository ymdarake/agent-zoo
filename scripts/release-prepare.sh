#!/usr/bin/env bash
# scripts/release-prepare.sh — バージョンアップ作業の自動化 (issue #68 補助ツール)
#
# branch-protected main (PR 必須) 運用向けの 2-phase flow。直接 push はしない。
# Python logic は scripts/release_prepare_lib.py に切り出されており、本 script
# は orchestration (flag parse / git ops / precondition check) を担う。
#
# Usage:
#   release-prepare.sh --no-tag <VERSION>       # phase 1: bump + commit
#   release-prepare.sh --tag-only <VERSION>     # phase 2: HEAD に annotated tag
#   release-prepare.sh --dry-run {--no-tag|--tag-only} <V>    # 副作用ゼロ事前検証
#
# 運用:
#   # phase 1: release branch で bump commit を作る
#   git checkout -b release/v0.1.1b1
#   ./scripts/release-prepare.sh --no-tag 0.1.1b1
#   git push -u origin release/v0.1.1b1
#   gh pr create --title ":bookmark: release: v0.1.1b1" --template release.md
#   # PR を squash merge
#
#   # phase 2: main で tag 打って push
#   git checkout main && git pull
#   ./scripts/release-prepare.sh --tag-only 0.1.1b1
#   git push origin v0.1.1b1

# -E (errtrace): `set -e` の ERR trap を関数 / subshell 内でも継承。
# これが無いと関数内の error が outer scope の trap ERR で捕まらず、
# `bump_pyproject` 失敗時の rollback が silent に skip される。
set -Eeuo pipefail

# readonly と同時代入は右辺の exit code を masking する (readonly 自身の 0 で
# 覆われて `set -e` が効かない) ため、宣言と代入を分離する。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
LIB="$SCRIPT_DIR/release_prepare_lib.py"
readonly LIB

# ----------------------------------------------------------------------------
# I/O helpers
# ----------------------------------------------------------------------------

die() {
    # die <headline> [<detail lines>...] — `::error::` prefix に headline、後続は indent
    printf '::error::%s\n' "$1" >&2
    shift
    local line
    for line in "$@"; do
        printf '  %s\n' "$line" >&2
    done
    exit 1
}

note() { printf 'note: %s\n' "$*" >&2; }
warn() { printf 'warning: %s\n' "$*" >&2; }

usage() {
    cat <<EOF
Usage: $0 [--dry-run] {--no-tag | --tag-only} <VERSION>

Modes:
  --no-tag      phase 1: pyproject bump + :bookmark: commit (release branch → PR)
  --tag-only    phase 2: HEAD に annotated tag (merge 後 main で)
  --dry-run     副作用ゼロで事前検証 (どちらの mode でも組み合わせ可)

例:
  $0 --no-tag 0.1.1b1
  $0 --tag-only 0.1.1b1
  $0 --dry-run --no-tag 0.1.1b1
EOF
}

# Python lib CLI wrapper。validate / classify / get-version / bump を呼ぶ。
lib() { python3 "$LIB" "$@"; }

# ----------------------------------------------------------------------------
# 引数 parse — グローバルに $VERSION / $DRY_RUN / $NO_TAG / $TAG_ONLY を set
# ----------------------------------------------------------------------------

DRY_RUN=false
NO_TAG=false
TAG_ONLY=false
VERSION=""

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)  DRY_RUN=true;  shift ;;
            --no-tag)   NO_TAG=true;   shift ;;
            --tag-only) TAG_ONLY=true; shift ;;
            -h|--help)  usage; exit 0 ;;
            -*)         die "unknown flag: $1" ;;
            *)
                [[ -z "$VERSION" ]] || die "too many positional args (got '$VERSION' and '$1')"
                VERSION="$1"; shift ;;
        esac
    done

    if $NO_TAG && $TAG_ONLY; then
        die "--no-tag and --tag-only are mutually exclusive (排他です)"
    fi
    if ! $NO_TAG && ! $TAG_ONLY; then
        { echo "::error::--no-tag または --tag-only の指定が必要です。" >&2; usage >&2; }
        exit 1
    fi
    if [[ -z "$VERSION" ]]; then
        { echo "::error::VERSION 引数が必要です。" >&2; usage >&2; }
        exit 1
    fi
}

# ----------------------------------------------------------------------------
# 共通 precondition (両 mode で走る)
# ----------------------------------------------------------------------------

ensure_working_tree_clean() {
    if ! git diff --quiet || ! git diff --cached --quiet; then
        git status --short >&2
        die "working tree is not clean. Commit or stash changes first."
    fi
}

ensure_tag_absent() {
    local tag="v$VERSION"
    if git rev-parse -q --verify "refs/tags/$tag" >/dev/null 2>&1; then
        die "tag '$tag' already exists locally." \
            "Delete it (git tag -d $tag) or bump VERSION."
    fi
    # origin が設定されていない workspace (test 等) は skip、それ以外は
    # network error を silent にせず明示的に die する (ls-remote output を
    # capture して exit code を `set -e` 経由で検知)。
    git remote get-url origin >/dev/null 2>&1 || return 0
    local remote_ls
    remote_ls="$(git ls-remote --tags origin "$tag" 2>&1)" \
        || die "git ls-remote failed (network error?)" "$remote_ls"
    if [[ -n "$remote_ls" ]]; then
        die "tag '$tag' already exists on origin. Choose a higher VERSION."
    fi
}

# ----------------------------------------------------------------------------
# --tag-only 固有の precondition (orphan tag による本番 PyPI 暴発を防ぐ)
# ----------------------------------------------------------------------------

ensure_on_main_branch() {
    local branch; branch="$(git rev-parse --abbrev-ref HEAD)"
    [[ "$branch" == "main" ]] && return 0
    if [[ ! -t 0 ]] || [[ -n "${CI:-}" ]]; then
        die "--tag-only requires main branch, got '$branch' (non-interactive env abort)."
    fi
    warn "--tag-only on branch '$branch' (typically main after merge)"
    read -r -p "continue anyway? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || die "aborted by user"
}

ensure_pyproject_matches_version() {
    local current; current="$(lib get-version)"
    [[ "$current" == "$VERSION" ]] && return 0
    die "--tag-only: pyproject.toml project.version = '$current' but VERSION='$VERSION'." \
        "bump 済の main に対して tag を打つ運用です。" \
        "VERSION と pyproject が一致する commit 上で実行してください" \
        "(phase 1 の commit が main に merge 済か確認)。"
}

ensure_head_references_release() {
    local subject; subject="$(git log -1 --format=%s HEAD)"
    local escaped="${VERSION//./\\.}"
    if echo "$subject" | grep -qE "release:[[:space:]]*v?${escaped}([[:space:]]|$)"; then
        return 0
    fi
    die "--tag-only: HEAD commit subject does not reference 'release: v$VERSION'." \
        "HEAD subject: $subject" \
        "bump commit を main に merge した直後の HEAD でのみ tag を打ってください。"
}

ensure_head_matches_origin_main() {
    if ! git rev-parse --verify origin/main >/dev/null 2>&1; then
        warn "origin/main ref not found, skipping HEAD == origin/main check (test env?)"
        return 0
    fi
    # fetch failure を silent にしない: 古い origin/main で比較すると orphan
    # tag を取りこぼす恐れがあるため。ただし offline maintenance で fetch
    # 不能なケースは warn で許容 (local HEAD == cached origin/main が成立
    # していれば後続 check が意味を持つ)。
    # fetch error を stderr 握り潰さず warn に同梱 (network 断 / rejected /
    # remote gone の区別を診断できるように)
    local fetch_err
    if ! fetch_err="$(git fetch -q origin main 2>&1)"; then
        warn "git fetch origin main failed: ${fetch_err:-(no stderr)}. Using cached origin/main for comparison."
    fi
    local local_head remote_head
    local_head="$(git rev-parse HEAD)"
    remote_head="$(git rev-parse origin/main)"
    [[ "$local_head" == "$remote_head" ]] && return 0
    die "--tag-only: HEAD ($local_head) != origin/main ($remote_head)." \
        "phase 1 の PR が merge された後、 git checkout main && git pull してから再実行してください。"
}

# ----------------------------------------------------------------------------
# mode 実装
# ----------------------------------------------------------------------------

run_tag_only() {
    ensure_on_main_branch
    ensure_pyproject_matches_version
    ensure_head_references_release
    ensure_head_matches_origin_main

    if $DRY_RUN; then
        echo "dry-run OK (--tag-only): v$VERSION ($KIND_LABEL), HEAD subject / pyproject / remote 全整合。"
        return 0
    fi

    git tag -a "v$VERSION" -m "Release v$VERSION"
    print_next_steps_tag_only
}

run_no_tag() {
    if $DRY_RUN; then
        local current; current="$(lib get-version)"
        echo "dry-run OK (--no-tag): v$VERSION ($KIND_LABEL), working tree clean, tag not yet exists. pyproject will be bumped from '$current' to '$VERSION'."
        return 0
    fi

    # rollback guard は phase 全体で一括管理 (bump / commit 双方を守る)。
    # EXIT を含めて trap する理由: `die` は `exit 1` で抜けるため ERR trap
    # では発火せず (ERR は未 trap の非 0 で発火、exit は EXIT trap のみ発火)、
    # EXIT を張らないと bump 後の mismatch die で silent に pyproject が
    # 汚染されたまま残る。rollback は idempotent で safe。
    # commit 成功後は明示的に解除して正常 exit 時の無駄な checkout を避ける。
    trap _rollback_pyproject EXIT ERR INT TERM

    bump_pyproject
    commit_release_anchor

    # commit が成立した時点で rollback 対象は reset --hard が必要な state に
    # 進む。以降の失敗 (print_next_steps 内の git 呼び出し等) は rollback
    # 対象外とし、user には echo 済の "To undo" 手順に委ねる。
    trap - EXIT ERR INT TERM

    print_next_steps_no_tag
}

# rollback guard 用 (run_no_tag の trap target)。冪等なので複数回呼んでも safe。
_rollback_pyproject() { git checkout HEAD -- ./pyproject.toml 2>/dev/null || true; }

bump_pyproject() {
    lib bump "$VERSION"
    local actual; actual="$(lib get-version)"
    [[ "$actual" == "$VERSION" ]] && return 0
    die "pyproject write did not produce expected version" \
        "got '$actual' expected '$VERSION'"
}

commit_release_anchor() {
    git add ./pyproject.toml
    if git diff --cached --quiet; then
        note "pyproject.toml already at v$VERSION, creating empty release-anchor commit"
        git commit --allow-empty -q -m ":bookmark: release: v$VERSION"
    else
        git commit -q -m ":bookmark: release: v$VERSION"
    fi
}

print_next_steps_tag_only() {
    cat <<EOF

Created annotated tag locally: v$VERSION ($KIND_LABEL)

Next step — push the tag to trigger GitHub Actions release workflow:
  git push origin v$VERSION

To undo (local only, push 前なら安全):
  git tag -d v$VERSION
EOF
}

print_next_steps_no_tag() {
    local branch; branch="$(git rev-parse --abbrev-ref HEAD)"
    # user が cd 先から叩いても解決できるよう絶対 path で echo ($0 は相対の
    # まま出ることがある)
    cat <<EOF

Created bump commit locally (no tag): v$VERSION ($KIND_LABEL)

Next step — release branch フローで main に merge 後、別途 tag を打つ:
  git push -u origin $branch
  gh pr create --title ":bookmark: release: v$VERSION" --template release.md
  # ... PR 上で release checklist を確認 → squash merge ...
  git checkout main && git pull
  $SCRIPT_DIR/release-prepare.sh --tag-only $VERSION
  git push origin v$VERSION

To undo (local only, push 前なら安全):
  git reset --hard HEAD^
EOF
}

# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

main() {
    parse_args "$@"
    # parse 後の設定値は変更不可 (誤代入・副作用防止)
    readonly DRY_RUN NO_TAG TAG_ONLY VERSION

    lib validate "$VERSION"

    local kind; kind="$(lib classify "$VERSION")"
    if [[ "$kind" == "pre-release" ]]; then
        KIND_LABEL="pre-release (TestPyPI only)"
    else
        KIND_LABEL="stable (prd PyPI + GitHub Release)"
    fi
    readonly KIND_LABEL

    ensure_working_tree_clean
    ensure_tag_absent

    if $TAG_ONLY; then
        run_tag_only
    else
        run_no_tag
    fi
}

main "$@"
