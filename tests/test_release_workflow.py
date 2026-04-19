"""Tests for `.github/workflows/release.yml` (issue #68).

release workflow の 2 つの回帰を検知する:

1. tag と ``pyproject.toml`` version の不整合が build job で fail するか
2. PEP 440 pre-release tag (``v*.*.*(a|b|rc)*``) を push した時に
   TestPyPI のみ発火し、本番 PyPI / GitHub Release は skip されるか

Plan review (sub-agent + Gemini) を踏まえた方針:

- script file は作らず ``run: | python -c ...`` inline で実装。
  attack surface を最小化しつつ、本 test が workflow yaml から該当 run block
  を抽出して subprocess 実行することで branch 全網羅を保つ。
- verify は ``ref_name.removeprefix("v") == pyproject_version`` の bit-for-bit
  比較 (PEP 440 正規化はしない、strict)。
- pre-release 判定は regex ``^v\\d+\\.\\d+\\.\\d+(a|b|rc)\\d+$`` で strict。
  ``v0.1.0-beta-1`` / ``v0.1.0.post1`` / ``v0.1.0.dev1`` / ``vv0.1.0`` 全 reject。
- ``github-release.if`` は ``needs: publish-pypi`` への依存だけに頼らず
  belt-and-suspenders で ``is_prerelease == 'false'`` を明示。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import textwrap

import pytest
import yaml

WORKFLOW = pathlib.Path(".github/workflows/release.yml")


def _workflow() -> dict:
    loaded = yaml.safe_load(WORKFLOW.read_text())
    # YAML 1.1 の norway-problem: `on:` key は boolean True に coerce される。
    # PyYAML 6.x は YAML 1.1 互換でこの挙動。下流 test の `_workflow()[True]`
    # が意味を維持することを guard で確認。parser が切り替わった場合に fail-fast。
    assert True in loaded, (
        "yaml parser が 'on' を True に coerce しなくなった。 "
        "release.yml parse の前提 (YAML 1.1) が崩れている可能性あり。"
    )
    return loaded


def _build_steps() -> list[dict]:
    return _workflow()["jobs"]["build"]["steps"]


def _find_step(name_substring: str) -> dict:
    for step in _build_steps():
        if name_substring.lower() in step.get("name", "").lower():
            return step
    raise AssertionError(
        f"build job に name に '{name_substring}' を含む step が無い"
    )


# ---------- A) tag / pyproject.toml version 整合チェック ----------


def test_build_has_tag_version_verify_step():
    step = _find_step("Verify tag")
    assert "run" in step, "Verify step に run が無い"
    # tag push 時のみ走る (workflow_dispatch では skip)。exact 一致で
    # `&& false` や `|| always()` のような無効化 injection を検知。
    assert step.get("if", "").strip() == "startsWith(github.ref, 'refs/tags/')", (
        f"Verify step の if が期待と不一致: {step.get('if')!r}"
    )


def test_build_has_classify_prerelease_step_with_id():
    """classify step は id を持ち、後段の outputs で参照される。"""
    step = _find_step("Classify")
    assert step.get("id"), f"Classify step に id が無い: {step}"


def test_build_exposes_is_prerelease_output():
    build = _workflow()["jobs"]["build"]
    outputs = build.get("outputs", {}) or {}
    assert "is_prerelease" in outputs, (
        f"build job の outputs に is_prerelease が無い: {outputs}"
    )
    # classify step の id を参照している
    expr = outputs["is_prerelease"]
    assert "steps." in expr and ".outputs.is_prerelease" in expr, (
        f"is_prerelease output 式が steps.<id>.outputs.is_prerelease を参照していない: {expr!r}"
    )


# ---------- B) on.push.tags は broad (v*.*.*) で分岐は classify に寄せる ----------


def test_on_push_tags_covers_stable_and_prerelease():
    """Plan review で確定: glob を増やさず v*.*.* 単発で broad にし、
    分類は workflow 内 classify step で行う。"""
    on = _workflow()[True]  # yaml で `on:` は boolean True にパースされる
    tags = on["push"]["tags"]
    # v*.*.* は v0.1.0 にも v0.1.0b1 にもマッチ (fnmatch 非 anchor)
    assert "v*.*.*" in tags, f"on.push.tags に v*.*.* が無い: {tags}"


# ---------- C) 各 job の if 条件 (literal string match で typo guard) ----------


def _job_if(name: str) -> str:
    return _workflow()["jobs"][name]["if"]


def test_publish_testpypi_if_covers_prerelease_tag_and_workflow_dispatch():
    expr = _job_if("publish-testpypi")
    # workflow_dispatch 経路 (既存)
    assert "workflow_dispatch" in expr
    assert "inputs.target == 'testpypi'" in expr
    # tag push + is_prerelease == 'true' 経路 (新規)
    assert "needs.build.outputs.is_prerelease == 'true'" in expr, (
        f"testpypi.if に is_prerelease == 'true' literal が無い: {expr!r}"
    )


def test_publish_pypi_if_excludes_prerelease():
    expr = _job_if("publish-pypi")
    assert "startsWith(github.ref, 'refs/tags/')" in expr
    # belt: pre-release は絶対に通さない
    assert "needs.build.outputs.is_prerelease == 'false'" in expr, (
        f"publish-pypi.if に is_prerelease == 'false' literal が無い: {expr!r}"
    )


def test_github_release_if_excludes_prerelease_belt_and_suspenders():
    """``needs: publish-pypi`` の skip 伝播に頼らず、明示的に除外する。"""
    expr = _job_if("github-release")
    assert "startsWith(github.ref, 'refs/tags/')" in expr
    assert "needs.build.outputs.is_prerelease == 'false'" in expr


def test_no_fragile_contains_b_check():
    """``contains(github.ref, 'b')`` のような脆い分岐が入っていないこと。"""
    text = WORKFLOW.read_text()
    assert "contains(github.ref, 'b')" not in text
    assert "contains(github.ref, 'a')" not in text
    assert "contains(github.ref, 'rc')" not in text


# ---------- D) Verify script の subprocess テスト (bit-for-bit 比較) ----------


def _extract_run(step_name_substring: str) -> str:
    return _find_step(step_name_substring)["run"]


def _run_step(
    run_block: str,
    *,
    ref_name: str,
    pyproject_version: str,
    tmp_path: pathlib.Path,
) -> subprocess.CompletedProcess:
    """workflow の run: block を tmp dir で実行。

    GITHUB_REF_NAME / GITHUB_OUTPUT / pyproject.toml を与えて Python が
    $GITHUB_OUTPUT にどう書くか、exit code がどうなるかを確認する。
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent(
            f"""
            [project]
            name = "agent-zoo"
            version = "{pyproject_version}"
            """
        ).strip()
    )
    github_output = tmp_path / "github_output.txt"
    github_output.touch()
    env = {
        **os.environ,
        "GITHUB_REF_NAME": ref_name,
        "GITHUB_OUTPUT": str(github_output),
    }
    # subprocess の shell として /bin/bash を使う (GitHub Actions default)
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", run_block],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("ref_name", "pyproject_version"),
    [
        ("v0.1.0", "0.1.0"),
        ("v0.2.0b1", "0.2.0b1"),
        ("v1.0.0a3", "1.0.0a3"),
        ("v2.3.4rc2", "2.3.4rc2"),
    ],
)
def test_verify_step_passes_when_tag_matches_pyproject(
    ref_name, pyproject_version, tmp_path
):
    result = _run_step(
        _extract_run("Verify tag"),
        ref_name=ref_name,
        pyproject_version=pyproject_version,
        tmp_path=tmp_path,
    )
    assert result.returncode == 0, (
        f"verify がマッチ時に fail した: ref={ref_name} pyproject={pyproject_version}\n"
        f"stderr={result.stderr}\nstdout={result.stdout}"
    )


@pytest.mark.parametrize(
    ("ref_name", "pyproject_version"),
    [
        # 典型的な unbump ミス: tag bump 済 / pyproject 未 bump
        ("v0.2.0", "0.1.0"),
        # 逆: pyproject が pre-release なのに stable tag
        ("v0.1.0", "0.1.0b1"),
        # 逆: pyproject stable + pre-release tag
        ("v0.1.0b1", "0.1.0"),
        # vv prefix を lstrip で誤 strip しない
        ("vv0.1.0", "0.1.0"),
        # dash 形 (非 PEP 440 native)
        ("v0.1.0-beta-1", "0.1.0b1"),
    ],
)
def test_verify_step_fails_on_mismatch(ref_name, pyproject_version, tmp_path):
    result = _run_step(
        _extract_run("Verify tag"),
        ref_name=ref_name,
        pyproject_version=pyproject_version,
        tmp_path=tmp_path,
    )
    assert result.returncode != 0, (
        f"verify が不一致を検知できなかった: ref={ref_name} pyproject={pyproject_version}\n"
        f"stdout={result.stdout}"
    )


def test_verify_step_rejects_dynamic_version_explicitly(tmp_path):
    """dynamic version (hatch-vcs 等) は未対応。cryptic KeyError ではなく
    明示 error で fail-fast することを保証する (Gemini レビュー反映)。"""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "agent-zoo"
            dynamic = ["version"]
            """
        ).strip()
    )
    github_output = tmp_path / "github_output.txt"
    github_output.touch()
    result = subprocess.run(
        [
            "bash",
            "-euo",
            "pipefail",
            "-c",
            _extract_run("Verify tag"),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "GITHUB_REF_NAME": "v0.1.0",
            "GITHUB_OUTPUT": str(github_output),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        f"dynamic version を検知できなかった\nstdout={result.stdout}"
    )
    # 明示 error message (cryptic KeyError ではない)
    assert "Dynamic version" in result.stderr or "dynamic" in result.stderr.lower(), (
        f"明示 error message が stderr に出ていない: {result.stderr!r}"
    )


# ---------- E) Classify script の subprocess テスト (regex 厳密) ----------


def _read_github_output(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@pytest.mark.parametrize(
    ("ref_name", "expected"),
    [
        ("v0.1.0", "false"),
        ("v1.2.3", "false"),
        ("v10.20.30", "false"),
        ("v0.1.0a1", "true"),
        ("v0.1.0b2", "true"),
        ("v0.1.0rc1", "true"),
        ("v1.2.3a10", "true"),
    ],
)
def test_classify_step_emits_is_prerelease(ref_name, expected, tmp_path):
    result = _run_step(
        _extract_run("Classify"),
        ref_name=ref_name,
        pyproject_version="0.0.0",  # classify は pyproject を見ない
        tmp_path=tmp_path,
    )
    assert result.returncode == 0, (
        f"classify が fail: ref={ref_name}\nstderr={result.stderr}"
    )
    out = _read_github_output(tmp_path / "github_output.txt")
    assert out.get("is_prerelease") == expected, (
        f"ref={ref_name}: expected is_prerelease={expected}, got {out}"
    )


@pytest.mark.parametrize(
    "ref_name",
    [
        # 非 PEP 440 public version → reject (script 側で fail or 明示 false)
        "v0.1.0-beta-1",
        "v0.1.0.post1",
        "v0.1.0.dev1",
        "v0.1.0-rc.1",
        "vv0.1.0",
        "v0.1",  # missing patch
        "v0.1.0b",  # missing number after suffix
        "v0.1.0post1",  # PEP 440 post but no-dot form (regex gap guard)
        "v0.1.0dev1",  # PEP 440 dev but no-dot form (regex gap guard)
        "v0.1.0b01",  # leading zero, PyPI 正規化衝突リスク
        "v0.1.0b1a",  # 複合 suffix
        "v1.0.0rc",  # suffix number missing
    ],
)
def test_classify_step_rejects_non_pep440_native(ref_name, tmp_path):
    """厳格な PEP 440 native 形のみ accept。ambiguous な tag は fail させる。

    failure mode: exit 1 (classify 時点で build job を止める)。
    silent に is_prerelease=false にして本番 PyPI に行く事故を防ぐ。
    """
    result = _run_step(
        _extract_run("Classify"),
        ref_name=ref_name,
        pyproject_version="0.0.0",
        tmp_path=tmp_path,
    )
    assert result.returncode != 0, (
        f"classify が非 PEP 440 native tag を reject しなかった: ref={ref_name}\n"
        f"stdout={result.stdout}"
    )
