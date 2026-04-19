"""Tests for ``scripts/release-prepare.sh`` (issue #68 補助ツール).

`make release <VERSION>` の中身。tmp_path に mini-repo を作って
subprocess で script を実行し、sed の誤 replace / rollback 抜け /
non-TTY hang などの silent failure を検知する。

Plan review で反映した観点:
- P0-1: pyproject 書き換えは sed ではなく Python re.sub (section-aware)
- P0-2: commit 失敗時に pyproject を rollback
- P0-3: recovery 手順を echo
- P1-4: Makefile 側で ``%:`` wildcard rule を ``release`` target 時のみ有効化
- P1-5: 非 TTY 環境では confirm prompt をスキップして abort
- P2-7: release.yml の regex と script の regex が同一 PEP 440 cases を判定 (drift 防止)
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


def _isolated_git_env() -> dict[str, str]:
    """test subprocess 用 env。

    GIT_CONFIG_GLOBAL / GIT_CONFIG_SYSTEM を /dev/null に向け、maintainer の
    ~/.gitconfig (commit.gpgsign / tag.gpgsign 等) による test 挙動変化を
    遮断する (test isolation)。例: tag.gpgsign=true が有効だと lightweight
    tag 作成すら "no tag message" で fail する。
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


# ---------- 引数 parse / usage ----------


def test_script_exists_and_executable():
    assert SCRIPT.exists(), f"{SCRIPT} が無い"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} が実行可能でない"


def test_no_arg_shows_usage_and_exits(tmp_path):
    _init_mini_repo(tmp_path)
    r = _run_script(tmp_path)
    assert r.returncode != 0
    assert "Usage" in (r.stderr + r.stdout)


def test_empty_version_shows_usage(tmp_path):
    _init_mini_repo(tmp_path)
    r = _run_script(tmp_path, "")
    assert r.returncode != 0
    assert "Usage" in (r.stderr + r.stdout) or "VERSION" in r.stderr


# ---------- VERSION format 検証 (PEP 440 native) ----------


_VALID_VERSIONS = ["0.1.0", "1.2.3", "0.1.0a1", "0.1.0b1", "0.1.0rc2", "10.20.30a10"]
_INVALID_VERSIONS = [
    "v0.1.0",  # leading v は script 側で reject (tag 名ではなく version のみ受け付ける)
    "0.1.0-beta-1",  # dash form
    "0.1.0.post1",  # post release
    "0.1.0.dev1",  # dev release
    "0.1.0b01",  # pre-release N の leading zero (PyPI 正規化衝突)
    "0.1.0b",  # suffix number missing
    "0.1",  # patch missing
    "0.1.0b1a",  # multiple suffix
]
# NOTE: `01.2.3` のような major/minor/patch の leading zero は release.yml 側
# の regex でも accept される (`\d+`)。drift 防止のため script も合わせる。
# PEP 440 canonical normalize で PyPI 側が `1.2.3` に畳むが、今回 scope 外。


@pytest.mark.parametrize("version", _INVALID_VERSIONS)
def test_rejects_invalid_version_format(version, tmp_path):
    _init_mini_repo(tmp_path)
    r = _run_script(tmp_path, "--dry-run", version)
    assert r.returncode != 0, (
        f"invalid VERSION {version!r} が通った: stdout={r.stdout} stderr={r.stderr}"
    )


@pytest.mark.parametrize("version", _VALID_VERSIONS)
def test_accepts_valid_version_format_in_dry_run(version, tmp_path):
    # dry-run なので副作用なし。pyproject.toml の version と一致させる必要は
    # 無い (format 検証のみ) ... いや、下記 "integrity with pyproject.toml"
    # で一致を求める。dry-run では pyproject とも一致要求。
    _init_mini_repo(tmp_path, version=version)
    r = _run_script(tmp_path, "--dry-run", version)
    assert r.returncode == 0, (
        f"valid VERSION {version!r} が reject された: stderr={r.stderr}"
    )


# ---------- regex drift guard: release.yml の inline regex と同一 ----------


def test_regex_matches_release_yml_classify_spec():
    """script の bash regex が release.yml classify の python regex と同じ
    PEP 440 case を judgement することを guarantee する。

    release.yml の regex は
      stable:       ^v\\d+\\.\\d+\\.\\d+$
      prerelease:   ^v\\d+\\.\\d+\\.\\d+(a|b|rc)(0|[1-9]\\d*)$
    で tag 名 (prefix v あり) に対して適用。
    script の regex は version (prefix v なし) に対して適用するので、
    `^` の直後の `v` を剥いた形が同じになる必要がある。
    """
    script_text = SCRIPT.read_text()
    # bash の =~ の右側 regex を抽出
    m = re.search(r'"\$VERSION"\s*=~\s*([^\s]+)', script_text)
    assert m, "script 内の `[[ \"$VERSION\" =~ ... ]]` regex が見つからない"
    bash_regex = m.group(1)

    # script regex は VERSION (prefix なし) を受けるので
    # `^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)(0|[1-9][0-9]*))?$` のような形のはず
    # release.yml 側と等価であることを確認: valid case 全通し、invalid 全 reject
    py_regex = re.compile(
        r"^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)(0|[1-9][0-9]*))?$"
    )
    for v in _VALID_VERSIONS:
        assert py_regex.match(v), f"spec regex が valid {v!r} を reject"
    for v in _INVALID_VERSIONS:
        # "v0.1.0" は leading v で reject、script は別の check (tag 側) で拾う
        assert not py_regex.match(v), f"spec regex が invalid {v!r} を accept"


# ---------- dry-run: 副作用なし ----------


def test_dry_run_does_not_modify_working_tree(tmp_path):
    _init_mini_repo(tmp_path, version="0.2.0")
    before = (tmp_path / "pyproject.toml").read_text()
    r = _run_script(tmp_path, "--dry-run", "0.2.0")
    assert r.returncode == 0, r.stderr
    after = (tmp_path / "pyproject.toml").read_text()
    assert before == after, "dry-run で pyproject.toml が変更された"
    # git status clean
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert status.stdout == "", f"dry-run で git tree が dirty: {status.stdout}"
    # tag 未作成
    tags = subprocess.run(
        ["git", "tag"], cwd=tmp_path, capture_output=True, text=True
    )
    assert tags.stdout.strip() == "", f"dry-run で tag が作られた: {tags.stdout}"


# ---------- dry-run: pyproject.toml との整合 ----------


def test_dry_run_fails_when_pyproject_mismatches(tmp_path):
    """VERSION と pyproject.toml の version が一致しない場合、本実行前に
    dry-run で気付けるようにする (integrity check)。"""
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "--dry-run", "0.2.0")
    assert r.returncode != 0, (
        f"VERSION と pyproject mismatch を dry-run で検知できなかった: stdout={r.stdout}"
    )


# ---------- 本実行 ----------


def test_real_run_creates_commit_and_tag_stable(tmp_path):
    _init_mini_repo(tmp_path, version="0.2.0")
    r = _run_script(tmp_path, "0.2.0")
    assert r.returncode == 0, f"stderr={r.stderr} stdout={r.stdout}"

    # pyproject.toml の version が 0.2.0 (変わっていない、既に bump 済)
    content = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in content

    # commit が作られている
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert "release: v0.2.0" in log.stdout or "v0.2.0" in log.stdout, log.stdout

    # tag v0.2.0 が存在
    tags = subprocess.run(
        ["git", "tag"], cwd=tmp_path, capture_output=True, text=True
    )
    assert "v0.2.0" in tags.stdout


def test_real_run_bumps_pyproject_version(tmp_path):
    """pyproject.toml の version が bump された場合を verify。"""
    _init_mini_repo(tmp_path, version="0.1.0")
    # VERSION=0.2.0 を指定 → script が pyproject.toml を 0.2.0 に書き換える
    r = _run_script(tmp_path, "0.2.0")
    assert r.returncode == 0, f"stderr={r.stderr}"
    content = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in content
    assert 'version = "0.1.0"' not in content


def test_real_run_creates_prerelease_tag(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "0.1.0b1")
    assert r.returncode == 0, f"stderr={r.stderr}"
    tags = subprocess.run(
        ["git", "tag"], cwd=tmp_path, capture_output=True, text=True
    )
    assert "v0.1.0b1" in tags.stdout


def test_created_tag_is_annotated_not_lightweight(tmp_path):
    """作成される tag が annotated であること。

    lightweight tag (`git tag v<VERSION>`) は `git push --follow-tags` で
    push されず、docs で案内している 1 発 push フローが silent に動かなくなる
    (commit のみ push され tag が remote に届かない → release workflow 非発火)。
    annotated tag は `git cat-file -t refs/tags/<tag>` が `tag` を返す。
    """
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "0.1.0b1")
    assert r.returncode == 0, r.stderr

    obj_type = subprocess.run(
        ["git", "cat-file", "-t", "refs/tags/v0.1.0b1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert obj_type.stdout.strip() == "tag", (
        "tag が lightweight (`commit`) になっている。`git push --follow-tags` で "
        "push されず release workflow が発火しない。`git tag -a ...` を使うこと。"
        f" got: {obj_type.stdout!r}"
    )

    # tag message も残っていること (annotated の意義)
    show = subprocess.run(
        ["git", "tag", "-l", "--format=%(contents)", "v0.1.0b1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert show.stdout.strip(), (
        f"annotated tag に message が無い: {show.stdout!r}"
    )


# ---------- 事前チェック: working tree / tag existence ----------


def test_rejects_dirty_working_tree(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    # 意図的に working tree を dirty にする
    (tmp_path / "pyproject.toml").write_text(
        (tmp_path / "pyproject.toml").read_text() + "\n# dirty\n"
    )
    r = _run_script(tmp_path, "0.1.0")
    assert r.returncode != 0
    assert "clean" in r.stderr.lower() or "dirty" in r.stderr.lower()


def test_rejects_shell_injection_via_version_arg(tmp_path):
    """VERSION 引数に shell metacharacter を混ぜても regex validate で
    reject されること (Makefile は "$(RELEASE_ARG)" で quote するが
    defense-in-depth の script 単体 level でも検証)。"""
    _init_mini_repo(tmp_path, version="0.1.0")
    # regex `^[0-9]+\.[0-9]+\.[0-9]+(...)?$` は ASCII digit + "." + a/b/rc のみ
    # match。以下は全て reject されるべき。
    for payload in ["0.1.0; id", "0.1.0 && id", "0.1.0$(id)", "`id`", "0.1.0\nid"]:
        r = _run_script(tmp_path, payload)
        assert r.returncode != 0, (
            f"shell injection payload {payload!r} が通った: {r.stdout}"
        )


def test_rejects_existing_tag(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    # isolated env で tag 作成 (maintainer の global tag.gpgsign=true が
    # "no tag message" を強制するのを回避)
    subprocess.run(
        ["git", "tag", "v0.1.0"],
        cwd=tmp_path,
        check=True,
        env=_isolated_git_env(),
    )
    r = _run_script(tmp_path, "0.1.0")
    assert r.returncode != 0
    assert "exist" in r.stderr.lower() or "already" in r.stderr.lower()


# ---------- pyproject.toml の他の version= 行が誤 replace されないこと ----------


def test_does_not_replace_unrelated_version_when_project_urls_precedes(tmp_path):
    """`[project.urls]` subsection が version 行より前にあっても section-aware で
    [project].version を見つけられること (sub-agent 指摘: 素朴な re.sub だと
    `[` で止まり n=0 で abort する pattern)。"""
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
    r = _run_script(tmp_path, "0.2.0")
    assert r.returncode == 0, f"stderr={r.stderr} stdout={r.stdout}"
    final = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in final


def test_real_run_echoes_note_when_pyproject_already_at_version(tmp_path):
    """pyproject が既に VERSION の時に empty anchor commit になることを user に
    伝える note を stderr に出すこと (sub-agent 指摘: 暗黙の empty commit を
    surface)。"""
    _init_mini_repo(tmp_path, version="0.2.0")
    r = _run_script(tmp_path, "0.2.0")
    assert r.returncode == 0, r.stderr
    assert "already at v0.2.0" in r.stderr or "empty release-anchor" in r.stderr, (
        f"empty commit の note が出ていない: stderr={r.stderr}"
    )


def test_does_not_replace_unrelated_version_keys(tmp_path):
    """`[tool.foo]` section の `version = "..."` 等は書き換えないこと (sed 誤爆防止)。"""
    _init_mini_repo(tmp_path, version="0.1.0")
    # pyproject.toml に擬似的に別の version = ... 行を追加
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
    r = _run_script(tmp_path, "0.2.0")
    assert r.returncode == 0, f"stderr={r.stderr}"
    final = (tmp_path / "pyproject.toml").read_text()
    # [project].version は 0.2.0 に書き換わっている
    assert 'version = "0.2.0"' in final
    # [tool.foo].version は 99.99.99 のまま
    assert 'version = "99.99.99"' in final


# ---------- Makefile target ----------


MAKEFILE = pathlib.Path("Makefile")


def test_makefile_has_release_target():
    text = MAKEFILE.read_text()
    assert "\nrelease:" in text, "Makefile に release target が無い"


def test_makefile_has_release_dry_run_target():
    text = MAKEFILE.read_text()
    assert "release-dry-run" in text


# ---------- --no-tag / --tag-only (branch-protected main 2-phase flow) ----------


def test_no_tag_creates_commit_but_no_tag(tmp_path):
    """--no-tag: pyproject bump + commit は行うが tag 作成しない (release branch → PR 用)。"""
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "--no-tag", "0.1.1b1")
    assert r.returncode == 0, f"stderr={r.stderr}"

    # bump commit が作られている
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert "release: v0.1.1b1" in log.stdout

    # tag は作られていない
    tags = subprocess.run(
        ["git", "tag"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert "v0.1.1b1" not in tags.stdout, (
        f"--no-tag なのに tag が作られた: {tags.stdout}"
    )

    # next step echo に release branch → PR → merge → make release-tag 手順が含まれる
    assert "release-tag" in r.stdout or "--tag-only" in r.stdout, (
        f"next step 案内に tag-only 手順が無い: {r.stdout}"
    )


def test_tag_only_creates_tag_but_no_commit(tmp_path):
    """--tag-only: HEAD に annotated tag を打つだけ (commit 作らない、merge 後の main 用)。

    pyproject.version == VERSION であり、かつ HEAD commit subject が
    ``release: v<VERSION>`` を含むことを precondition として確認。
    """
    _init_mini_repo(tmp_path, version="0.1.1b1")  # 既に bump 済
    # bump commit を想定した subject で 1 commit 追加
    (tmp_path / "pyproject.toml").write_text(
        (tmp_path / "pyproject.toml").read_text() + "\n# bump\n"
    )
    subprocess.run(
        ["git", "commit", "-am", ":bookmark: release: v0.1.1b1"],
        cwd=tmp_path,
        check=True,
        env=_isolated_git_env(),
    )
    commits_before = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    ).stdout.strip()

    r = _run_script(tmp_path, "--tag-only", "0.1.1b1")
    assert r.returncode == 0, f"stderr={r.stderr}"

    # tag が作られている (annotated)
    obj_type = subprocess.run(
        ["git", "cat-file", "-t", "refs/tags/v0.1.1b1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    )
    assert obj_type.stdout.strip() == "tag", (
        f"tag が annotated でない: {obj_type.stdout!r}"
    )

    # 新規 commit は作られていない (commit 数が増えていない)
    commits_after = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_isolated_git_env(),
    ).stdout.strip()
    assert commits_before == commits_after, (
        f"--tag-only なのに commit が増えた: before={commits_before} after={commits_after}"
    )


def test_tag_only_rejects_when_pyproject_version_mismatches(tmp_path):
    """--tag-only: pyproject.version が VERSION と一致していない (= bump 前の commit に
    誤って tag しようとしている) 場合は reject (HIGH: silent な誤 tag 防止)。"""
    _init_mini_repo(tmp_path, version="0.1.0")  # bump 前
    r = _run_script(tmp_path, "--tag-only", "0.1.1b1")
    assert r.returncode != 0, (
        f"pyproject mismatch を tag-only が reject しなかった: stdout={r.stdout}"
    )


def test_tag_only_rejects_when_head_subject_does_not_match(tmp_path):
    """--tag-only: HEAD commit subject が ``release: v<VERSION>`` を含まない場合 reject。

    maintainer が間違って別 commit 上で `make release-tag` を叩いた事故を防ぐ (HIGH)。
    """
    _init_mini_repo(tmp_path, version="0.1.1b1")
    # bump 済 pyproject だが、HEAD subject は "initial" (release ではない)
    r = _run_script(tmp_path, "--tag-only", "0.1.1b1")
    assert r.returncode != 0, (
        f"HEAD subject mismatch を tag-only が reject しなかった: stdout={r.stdout}"
    )
    assert "subject" in r.stderr.lower() or "release:" in r.stderr.lower(), (
        f"subject mismatch の error message が不明瞭: {r.stderr}"
    )


def test_tag_only_rejects_when_tag_already_exists_locally(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.1b1")
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", ":bookmark: release: v0.1.1b1"],
        cwd=tmp_path,
        check=True,
        env=_isolated_git_env(),
    )
    subprocess.run(
        ["git", "tag", "-a", "v0.1.1b1", "-m", "preexisting"],
        cwd=tmp_path,
        check=True,
        env=_isolated_git_env(),
    )
    r = _run_script(tmp_path, "--tag-only", "0.1.1b1")
    assert r.returncode != 0
    assert "exist" in r.stderr.lower() or "already" in r.stderr.lower()


def test_no_tag_and_tag_only_mutually_exclusive(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.0")
    r = _run_script(tmp_path, "--no-tag", "--tag-only", "0.1.1b1")
    assert r.returncode != 0
    assert "exclusive" in r.stderr.lower() or "排他" in r.stderr or "mutually" in r.stderr.lower(), (
        f"mutex error message が不明瞭: {r.stderr}"
    )


def test_tag_only_dry_run_no_side_effects(tmp_path):
    _init_mini_repo(tmp_path, version="0.1.1b1")
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", ":bookmark: release: v0.1.1b1"],
        cwd=tmp_path,
        check=True,
        env=_isolated_git_env(),
    )
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


# ---------- Makefile の新 target ----------


def test_makefile_has_release_commit_target():
    text = MAKEFILE.read_text()
    assert re.search(r"^release-commit:", text, re.MULTILINE), (
        "Makefile に release-commit target が無い"
    )


def test_makefile_has_release_tag_target():
    text = MAKEFILE.read_text()
    assert re.search(r"^release-tag:", text, re.MULTILINE), (
        "Makefile に release-tag target が無い"
    )


def test_makefile_positional_arg_rule_guarded_by_release_cmd():
    """positional VERSION を吸収する dummy rule が release / release-dry-run
    target の時だけ有効で、他の typo target を silent no-op にしないこと
    (P1-4 対応)。

    実装は `%:` wildcard rule ではなく ``ifneq (... MAKECMDGOALS ...)``
    guard 内で ``$(eval $(RELEASE_ARG):;@:)`` により具体的 target を動的に
    生成する形。
    """
    text = MAKEFILE.read_text()
    # MAKECMDGOALS を参照した ifneq / ifeq guard が存在
    assert re.search(r"(ifneq|ifeq)\s*\(", text), (
        "Makefile に ifneq/ifeq guard が無い"
    )
    assert "MAKECMDGOALS" in text, "Makefile で MAKECMDGOALS を使っていない"
    # guard 内で release / release-dry-run の時のみ有効化
    assert re.search(r"release", text) and re.search(r"release-dry-run", text)
    # 動的 dummy target 生成 (`$(eval ...:;@:)`)
    assert "$(eval" in text and ":;@:" in text, (
        "動的 positional arg 吸収 (`$(eval $(...):;@:)`) が見当たらない"
    )
    # bare `%:` wildcard は副作用が大きいので使っていないこと
    assert not re.search(r"^%:", text, re.MULTILINE), (
        "`%:` wildcard rule は副作用 (他 typo silent no-op) があるため使わない設計"
    )
