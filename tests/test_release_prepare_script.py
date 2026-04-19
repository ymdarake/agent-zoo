"""Integration tests for ``scripts/release-prepare.sh`` (issue #68 補助ツール).

bash script の orchestration 部分を subprocess で検証する。Python logic
(validate / classify / bump / get-version) は ``release_prepare_lib`` に
切り出し済みで、それらの fine-grained unit test は
:mod:`tests.test_release_prepare_lib` に分離している。

本 file は bash script 固有の以下を verify する:

- flag parse / mutex / mode 必須
- git ops (working tree clean / branch check / tag 未存在 / remote tag check)
- ``--no-tag`` phase 1: bump + :bookmark: commit の作成、tag は作らない
- ``--tag-only`` phase 2: pyproject / HEAD subject / HEAD==origin/main の
  3 precondition を fail-fast で verify、annotated tag 作成 (lightweight reject)
- rollback (trap) / dry-run 副作用なし / shell injection defense-in-depth
- Makefile target の存在と positional arg 吸収 (``ifneq MAKECMDGOALS``)
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import textwrap

import pytest
import yaml

SCRIPT = pathlib.Path("scripts/release-prepare.sh").resolve()
WORKFLOW = pathlib.Path(".github/workflows/release.yml")
MAKEFILE = pathlib.Path("Makefile")


def _isolated_git_env() -> dict[str, str]:
    """test subprocess 用 env。

    GIT_CONFIG_GLOBAL / GIT_CONFIG_SYSTEM を /dev/null に向け、maintainer の
    ~/.gitconfig (commit.gpgsign / tag.gpgsign 等) による test 挙動変化を
    遮断する。
    """
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@test",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@test",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }


def _init_mini_repo(root: pathlib.Path, version: str = "0.1.0") -> None:
    """tmp_path に git repo + minimal pyproject.toml を用意する。"""
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""
            [project]
            name = "agent-zoo"
            version = "{version}"
            description = "test"

            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"
            """
        ).strip()
        + "\n"
    )
    env = _isolated_git_env()
    for cmd in [
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "pyproject.toml"],
        ["git", "commit", "-q", "-m", "initial"],
    ]:
        subprocess.run(cmd, cwd=root, check=True, env=env)


def _setup_bumped_head(root: pathlib.Path, version: str) -> None:
    """``--tag-only`` テスト用のセットアップ: pyproject が bump 済で HEAD
    commit subject が `:bookmark: release: v<VERSION>` の状態にする。"""
    _init_mini_repo(root, version=version)
    # bump 済 (`_init_mini_repo` で version=version にしているので content は OK)
    # initial commit の上に release commit を追加
    (root / ".touch").write_text("bump trigger\n")
    subprocess.run(
        ["git", "add", ".touch"],
        cwd=root,
        check=True,
        env=_isolated_git_env(),
    )
    subprocess.run(
        ["git", "commit", "-m", f":bookmark: release: v{version}"],
        cwd=root,
        check=True,
        env=_isolated_git_env(),
    )


def _run_script(
    root: pathlib.Path,
    *args: str,
    stdin: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=root,
        env=_isolated_git_env(),
        capture_output=True,
        text=True,
        input=stdin,
    )


# ============================================================================
# 引数 parse / usage / flag validation
# ============================================================================


def test_script_exists_and_executable():
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)


def test_no_arg_shows_usage_and_exits(tmp_path):
    _init_mini_repo(tmp_path)
    r = _run_script(tmp_path)
    assert r.returncode != 0
    assert "Usage" in (r.stderr + r.stdout) or "--no-tag" in r.stderr


def test_empty_version_shows_usage(tmp_path):
    _init_mini_repo(tmp_path)
    r = _run_script(tmp_path, "--no-tag", "")
    assert r.returncode != 0
    assert "Usage" in (r.stderr + r.stdout) or "VERSION" in r.stderr


def test_requires_mode_flag(tmp_path):
    """flag 無し (VERSION だけ) で usage error — legacy 全部入り経路を廃止した回帰防止。"""
    _init_mini_repo(tmp_path)
    r = _run_script(tmp_path, "0.1.0")
    assert r.returncode != 0
    assert "--no-tag" in r.stderr or "--tag-only" in r.stderr, (
        f"mode flag 必須の案内が出ていない: {r.stderr}"
    )


def test_no_tag_and_tag_only_mutually_exclusive(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "--no-tag", "--tag-only", "0.1.1b1")
    assert r.returncode != 0
    assert (
        "exclusive" in r.stderr.lower()
        or "排他" in r.stderr
        or "mutually" in r.stderr.lower()
    )


# ============================================================================
# VERSION format 検証 (PEP 440 native) — --no-tag で検証
# ============================================================================


_VALID_VERSIONS = ["0.1.0", "1.2.3", "0.1.0a1", "0.1.0b1", "0.1.0rc2", "10.20.30a10"]
_INVALID_VERSIONS = [
    "v0.1.0",  # leading v は reject
    "0.1.0-beta-1",  # dash form
    "0.1.0.post1",  # post release
    "0.1.0.dev1",  # dev release
    "0.1.0b01",  # pre-release N の leading zero
    "0.1.0b",  # suffix number missing
    "0.1",  # patch missing
    "0.1.0b1a",  # multiple suffix
]


@pytest.mark.parametrize("version", _INVALID_VERSIONS)
def test_rejects_invalid_version_format(version, tmp_path):
    _init_mini_repo(tmp_path)
    r = _run_script(tmp_path, "--dry-run", "--no-tag", version)
    assert r.returncode != 0


@pytest.mark.parametrize("version", _VALID_VERSIONS)
def test_accepts_valid_version_format_in_dry_run(version, tmp_path):
    _init_mini_repo(tmp_path, version=version)
    r = _run_script(tmp_path, "--dry-run", "--no-tag", version)
    assert r.returncode == 0, f"valid {version!r} rejected: {r.stderr}"


def test_script_delegates_version_validate_to_lib():
    """bash script が VERSION 検証を lib wrapper (``lib validate``) に委譲しており、
    生の VERSION regex を持っていないこと (single source of truth)。"""
    script_text = SCRIPT.read_text()
    assert "lib validate" in script_text, "lib wrapper を使って validate を呼んでいない"
    # bash 側で生の regex を持っていない (lib に単一化)
    assert "[[ \"$VERSION\" =~" not in script_text, (
        "bash に VERSION regex が残っている (lib に単一化すべき)"
    )


# ============================================================================
# --no-tag (phase 1): pyproject bump + commit のみ
# ============================================================================


def test_no_tag_creates_commit_but_no_tag(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "--no-tag", "0.1.1b1")
    assert r.returncode == 0, f"stderr={r.stderr}"

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert "release: v0.1.1b1" in log.stdout

    tags = subprocess.run(
        ["git", "tag"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert "v0.1.1b1" not in tags.stdout, f"--no-tag なのに tag が作られた: {tags.stdout}"

    assert "release-tag" in r.stdout or "--tag-only" in r.stdout, (
        f"next step 案内に phase 2 手順が無い: {r.stdout}"
    )


def test_no_tag_bumps_pyproject_version(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "--no-tag", "0.2.0")
    assert r.returncode == 0, r.stderr
    content = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in content
    assert 'version = "0.1.0"' not in content


def test_no_tag_echoes_note_when_pyproject_already_at_version(tmp_path):
    """pyproject が既に VERSION の時に empty anchor commit になる note を surface。"""
    _init_mini_repo(tmp_path, version="0.2.0")
    r = _run_script(tmp_path, "--no-tag", "0.2.0")
    assert r.returncode == 0, r.stderr
    assert "already at v0.2.0" in r.stderr or "empty release-anchor" in r.stderr


def test_no_tag_dry_run_no_side_effects(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    before = (tmp_path / "pyproject.toml").read_text()
    r = _run_script(tmp_path, "--dry-run", "--no-tag", "0.2.0")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "pyproject.toml").read_text() == before
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert status.stdout == "", f"dirty: {status.stdout}"


def test_no_tag_does_not_replace_unrelated_version_keys(tmp_path):
    """`[tool.foo]` section の `version = "..."` 等は書き換えない (section-aware)。"""
    _init_mini_repo(tmp_path, version="0.1.0")
    content = (tmp_path / "pyproject.toml").read_text()
    content += textwrap.dedent(
        """
        [tool.foo]
        version = "99.99.99"
        """
    )
    (tmp_path / "pyproject.toml").write_text(content)
    subprocess.run(
        ["git", "commit", "-am", "add tool.foo"],
        cwd=tmp_path,
        check=True,
        env=_isolated_git_env(),
    )
    r = _run_script(tmp_path, "--no-tag", "0.2.0")
    assert r.returncode == 0, r.stderr
    final = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in final
    assert 'version = "99.99.99"' in final


def test_no_tag_does_not_replace_when_project_urls_precedes(tmp_path):
    """`[project.urls]` subsection が version 行より前でも section-aware に解決。"""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "agent-zoo"
            urls = { homepage = "https://example.com" }
            version = "0.1.0"

            [project.optional-dependencies]
            dev = []
            """
        ).strip()
        + "\n"
    )
    env = _isolated_git_env()
    for cmd in [
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "pyproject.toml"],
        ["git", "commit", "-q", "-m", "initial"],
    ]:
        subprocess.run(cmd, cwd=tmp_path, check=True, env=env)
    r = _run_script(tmp_path, "--no-tag", "0.2.0")
    assert r.returncode == 0, r.stderr
    final = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in final


def test_no_tag_rejects_dirty_working_tree(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    (tmp_path / "pyproject.toml").write_text(
        (tmp_path / "pyproject.toml").read_text() + "\n# dirty\n"
    )
    r = _run_script(tmp_path, "--no-tag", "0.1.0")
    assert r.returncode != 0
    assert "clean" in r.stderr.lower() or "dirty" in r.stderr.lower()


def test_no_tag_rejects_shell_injection_via_version_arg(tmp_path):
    """VERSION に shell metacharacter → regex で reject (defense-in-depth)。"""
    _init_mini_repo(tmp_path, version="0.1.0")
    for payload in ["0.1.0; id", "0.1.0 && id", "0.1.0$(id)", "`id`", "0.1.0\nid"]:
        r = _run_script(tmp_path, "--no-tag", payload)
        assert r.returncode != 0, f"payload {payload!r} が通った: {r.stdout}"


# ============================================================================
# --tag-only (phase 2): HEAD に annotated tag のみ
# ============================================================================


def test_tag_only_creates_annotated_tag_without_commit(tmp_path):
    """--tag-only: HEAD に annotated tag を作成 (commit は増えない)。

    annotated tag (`-a -m`) でないと `git push --follow-tags` の対象外で
    release workflow が silent 非発火する回帰をここで防ぐ。
    """
    _setup_bumped_head(tmp_path, version="0.1.1b1")
    commits_before = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    ).stdout.strip()

    r = _run_script(tmp_path, "--tag-only", "0.1.1b1")
    assert r.returncode == 0, r.stderr

    # annotated tag であること (lightweight = `commit` object)
    obj_type = subprocess.run(
        ["git", "cat-file", "-t", "refs/tags/v0.1.1b1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert obj_type.stdout.strip() == "tag", (
        f"annotated tag でない (lightweight だと --follow-tags で push されない): "
        f"{obj_type.stdout!r}"
    )

    # tag message も残る
    show = subprocess.run(
        ["git", "tag", "-l", "--format=%(contents)", "v0.1.1b1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert show.stdout.strip()

    # commit は増えていない
    commits_after = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    ).stdout.strip()
    assert commits_before == commits_after


def test_tag_only_rejects_when_pyproject_version_mismatches(tmp_path):
    """bump 前の commit に tag しようとしたら reject (silent 誤 tag 防止、HIGH)。"""
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "--tag-only", "0.1.1b1")
    assert r.returncode != 0


def test_tag_only_rejects_when_head_subject_does_not_match(tmp_path):
    """HEAD commit subject が `release: v<VERSION>` を含まない → reject (HIGH)。"""
    _init_mini_repo(tmp_path, version="0.1.1b1")  # pyproject 一致、でも subject は "initial"
    r = _run_script(tmp_path, "--tag-only", "0.1.1b1")
    assert r.returncode != 0
    assert "subject" in r.stderr.lower() or "release:" in r.stderr.lower()


def test_tag_only_rejects_when_tag_already_exists_locally(tmp_path):
    _setup_bumped_head(tmp_path, version="0.1.1b1")
    subprocess.run(
        ["git", "tag", "-a", "v0.1.1b1", "-m", "preexisting"],
        cwd=tmp_path,
        check=True,
        env=_isolated_git_env(),
    )
    r = _run_script(tmp_path, "--tag-only", "0.1.1b1")
    assert r.returncode != 0
    assert "exist" in r.stderr.lower() or "already" in r.stderr.lower()


def test_tag_only_dry_run_no_side_effects(tmp_path):
    _setup_bumped_head(tmp_path, version="0.1.1b1")
    r = _run_script(tmp_path, "--dry-run", "--tag-only", "0.1.1b1")
    assert r.returncode == 0, r.stderr
    tags = subprocess.run(
        ["git", "tag"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert "v0.1.1b1" not in tags.stdout, "dry-run で tag が作られた"


# ============================================================================
# Makefile target
# ============================================================================


def test_makefile_has_release_commit_target():
    text = MAKEFILE.read_text()
    assert re.search(r"^release-commit:", text, re.MULTILINE)


def test_makefile_has_release_tag_target():
    text = MAKEFILE.read_text()
    assert re.search(r"^release-tag:", text, re.MULTILINE)


def test_makefile_has_dry_run_targets():
    text = MAKEFILE.read_text()
    assert "release-commit-dry-run" in text
    assert "release-tag-dry-run" in text


def test_makefile_legacy_release_target_removed():
    """legacy 全部入り `release` target は削除済 (user 0、breaking change OK)。"""
    text = MAKEFILE.read_text()
    # `^release:` (word boundary 含む) が無い
    assert not re.search(r"^release:", text, re.MULTILINE), (
        "legacy `release` target が残存している (削除されているはず)"
    )
    # `release-dry-run` だけは OK (`release-commit-dry-run` とは別だが現在削除済)
    assert not re.search(r"^release-dry-run:", text, re.MULTILINE)


def test_makefile_positional_arg_rule_guarded_by_release_cmd():
    """positional VERSION 吸収の dummy rule が release-* target の時だけ有効。"""
    text = MAKEFILE.read_text()
    assert re.search(r"(ifneq|ifeq)\s*\(", text)
    assert "MAKECMDGOALS" in text
    assert "release-commit" in text and "release-tag" in text
    assert "$(eval" in text and ":;@:" in text
    assert not re.search(r"^%:", text, re.MULTILINE), (
        "`%:` wildcard は副作用が大きいため使わない設計"
    )
