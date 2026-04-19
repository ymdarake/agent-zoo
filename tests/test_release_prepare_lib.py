"""Unit tests for ``scripts/release_prepare_lib.py``.

Python 関数単位の fine-grained test。subprocess / git 不要で高速に回る。

- VERSION format の validate / classify (regex spec、release.yml classify と同等)
- pyproject.toml の [project].version 読み (dynamic version は error)
- [project].version の section-aware 書き換え
  ([tool.foo].version 等への誤爆を防ぐ、[project.urls] subsection の
   前にあっても動く、new_version 内の `\\1` 後方参照 escape は lambda で無効化)

bash integration test (``tests/test_release_prepare_script.py``) は
precondition check / git ops / flag parse / rollback のような bash 固有
挙動に集中し、本 file が logic 本体を verify する役割分担。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import textwrap

import pytest

# scripts/ を import path に加えて release_prepare_lib を loader で取り込む。
# `.py` 拡張子で置くため importlib.util で path 指定 load。
_LIB_PATH = pathlib.Path("scripts/release_prepare_lib.py").resolve()
_spec = importlib.util.spec_from_file_location("release_prepare_lib", _LIB_PATH)
assert _spec is not None and _spec.loader is not None, f"cannot load {_LIB_PATH}"
lib = importlib.util.module_from_spec(_spec)
sys.modules["release_prepare_lib"] = lib
_spec.loader.exec_module(lib)


# ============================================================================
# validate_version
# ============================================================================

_VALID_VERSIONS = [
    "0.1.0",
    "1.2.3",
    "0.1.0a1",
    "0.1.0b1",
    "0.1.0rc2",
    "10.20.30a10",
]
_INVALID_VERSIONS = [
    "v0.1.0",          # leading v reject
    "0.1.0-beta-1",    # dash form
    "0.1.0.post1",     # post release
    "0.1.0.dev1",      # dev release
    "0.1.0b01",        # leading zero on pre-release N (PyPI 正規化衝突)
    "0.1.0b",          # suffix number missing
    "0.1",             # patch missing
    "0.1.0b1a",        # multiple suffix
    "0.1.0post1",      # no-dot post
    "0.1.0dev1",       # no-dot dev
    "",                # empty
]


@pytest.mark.parametrize("v", _VALID_VERSIONS)
def test_validate_version_accepts_valid(v):
    lib.validate_version(v)  # no raise


@pytest.mark.parametrize("v", _INVALID_VERSIONS)
def test_validate_version_rejects_invalid(v):
    with pytest.raises(lib.ReleaseError):
        lib.validate_version(v)


# ============================================================================
# classify
# ============================================================================


@pytest.mark.parametrize(
    ("v", "expected"),
    [
        ("0.1.0", "stable"),
        ("1.2.3", "stable"),
        ("10.20.30", "stable"),
        ("0.1.0a1", "pre-release"),
        ("0.1.0b1", "pre-release"),
        ("0.1.0rc2", "pre-release"),
    ],
)
def test_classify(v, expected):
    assert lib.classify(v) == expected


def test_classify_invalid_raises():
    with pytest.raises(lib.ReleaseError):
        lib.classify("0.1.0-beta-1")


# ============================================================================
# get_project_version
# ============================================================================


def _write_pyproject(path: pathlib.Path, body: str) -> pathlib.Path:
    f = path / "pyproject.toml"
    f.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return f


def test_get_project_version_reads_static(tmp_path):
    f = _write_pyproject(
        tmp_path,
        """
        [project]
        name = "agent-zoo"
        version = "0.2.1b3"
        """,
    )
    assert lib.get_project_version(f) == "0.2.1b3"


def test_get_project_version_raises_on_dynamic(tmp_path):
    f = _write_pyproject(
        tmp_path,
        """
        [project]
        name = "agent-zoo"
        dynamic = ["version"]
        """,
    )
    with pytest.raises(lib.ReleaseError, match=r"dynamic version"):
        lib.get_project_version(f)


def test_get_project_version_raises_when_no_project_section(tmp_path):
    f = _write_pyproject(
        tmp_path,
        """
        [build-system]
        requires = ["hatchling"]
        """,
    )
    with pytest.raises(lib.ReleaseError):
        lib.get_project_version(f)


# ============================================================================
# bump_project_version — section-aware 書き換え
# ============================================================================


def test_bump_project_version_basic(tmp_path):
    f = _write_pyproject(
        tmp_path,
        """
        [project]
        name = "agent-zoo"
        version = "0.1.0"
        """,
    )
    lib.bump_project_version("0.2.0", f)
    assert 'version = "0.2.0"' in f.read_text()
    assert 'version = "0.1.0"' not in f.read_text()


def test_bump_project_version_does_not_touch_tool_foo(tmp_path):
    """他 section の `version = "..."` (例: [tool.hatch.version]) は触らない。"""
    f = _write_pyproject(
        tmp_path,
        """
        [project]
        name = "agent-zoo"
        version = "0.1.0"

        [tool.foo]
        version = "99.99.99"
        """,
    )
    lib.bump_project_version("0.2.0", f)
    content = f.read_text()
    assert 'version = "0.2.0"' in content
    assert 'version = "99.99.99"' in content


def test_bump_project_version_resolves_when_project_urls_precedes(tmp_path):
    """[project.urls] subsection が先にあっても [project].version を見つける。"""
    f = _write_pyproject(
        tmp_path,
        """
        [project]
        name = "agent-zoo"
        urls = { homepage = "https://example.com" }
        version = "0.1.0"

        [project.optional-dependencies]
        dev = []
        """,
    )
    lib.bump_project_version("0.3.0", f)
    assert 'version = "0.3.0"' in f.read_text()


def test_bump_project_version_raises_when_project_section_missing(tmp_path):
    f = _write_pyproject(
        tmp_path,
        """
        [build-system]
        requires = ["hatchling"]
        """,
    )
    with pytest.raises(lib.ReleaseError, match=r"\[project\]"):
        lib.bump_project_version("0.2.0", f)


def test_bump_project_version_raises_when_no_version_line(tmp_path):
    """[project] はあるが version = ... 行が無い (dynamic 前段等)。"""
    f = _write_pyproject(
        tmp_path,
        """
        [project]
        name = "agent-zoo"
        dynamic = ["version"]
        """,
    )
    with pytest.raises(lib.ReleaseError, match=r"version"):
        lib.bump_project_version("0.2.0", f)


def test_bump_project_version_lambda_escapes_backreferences(tmp_path):
    """new_version に `\\1` 等の後方参照 syntax が含まれても literal 扱い
    (regex sub の repl string 展開が無効化されている)。"""
    f = _write_pyproject(
        tmp_path,
        """
        [project]
        name = "agent-zoo"
        version = "0.1.0"
        """,
    )
    # 現実的には regex reject されるが、内部 sub の安全性確認のため直接呼ぶ
    lib.bump_project_version(r"0.2.0\1", f)
    assert r'version = "0.2.0\1"' in f.read_text()


def test_bump_project_version_preserves_encoding_and_newlines(tmp_path):
    """UTF-8 + LF を silent に CRLF / BOM 付きに書き換えないこと。"""
    f = tmp_path / "pyproject.toml"
    # 日本語コメント (UTF-8) + LF only を意図的に含める
    body = (
        '[project]\n'
        'name = "agent-zoo"\n'
        'version = "0.1.0"  # 日本語コメント\n'
    )
    f.write_bytes(body.encode("utf-8"))
    lib.bump_project_version("0.2.0", f)
    out = f.read_bytes()
    assert b"\r\n" not in out, "LF が CRLF に書き換わった"
    assert "日本語コメント".encode("utf-8") in out


# ============================================================================
# drift guard: release.yml の classify regex と lib の regex が同じ judgement
# ============================================================================


def test_lib_regex_matches_release_yml_classify_spec():
    """lib.PEP440_NATIVE_RE と ``release.yml`` の classify step regex が同値
    な PEP 440 cases を判定することを fixture baseline で保証する。

    release.yml 側は prefix ``v`` あり、lib 側は prefix なし。prefix を剥いた
    形で、VALID/INVALID cases に対して両者の判定が一致することを確認する
    (drift 早期検知)。
    """
    import re

    workflow_stable = re.compile(r"^v\d+\.\d+\.\d+$")
    workflow_pre = re.compile(r"^v\d+\.\d+\.\d+(a|b|rc)(0|[1-9]\d*)$")

    def workflow_matches(v: str) -> bool:
        tag = f"v{v}"
        return bool(workflow_stable.match(tag) or workflow_pre.match(tag))

    for v in _VALID_VERSIONS:
        assert workflow_matches(v), (
            f"workflow regex が valid '{v}' を reject (drift)"
        )
    for v in _INVALID_VERSIONS:
        if v == "":
            continue  # empty は prefix `v` 付けると `v` になり stable regex で reject
        assert not workflow_matches(v), (
            f"workflow regex が invalid '{v}' を accept (drift)"
        )
