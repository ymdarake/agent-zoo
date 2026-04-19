"""Release preparation helpers (extracted from ``release-prepare.sh`` for testability).

``scripts/release-prepare.sh`` の Python logic を 1 module に切り出し、
bash 側は flag parse / git ops / orchestration のみを担う。本 module は
``python3 -m release_prepare_lib <subcommand>`` の CLI としても、test からの
``import`` としても使える。

### 責務

- :func:`validate_version`  — VERSION が PEP 440 native public version か
- :func:`classify`          — stable / pre-release 分類
- :func:`get_project_version` — ``pyproject.toml`` から ``[project].version`` 取得
  (dynamic version は未対応で :class:`ReleaseError`)
- :func:`bump_project_version` — ``[project].version`` を section-aware に書き換え
  (``[tool.foo].version`` 等への誤爆を防ぐ、``[project.urls]`` subsection が
  先にあっても動く、new_version 内の ``\\1`` 後方参照は lambda で無効化)

### CLI

::

    python3 -m release_prepare_lib validate <VERSION>
    python3 -m release_prepare_lib classify <VERSION>
    python3 -m release_prepare_lib get-version [--pyproject PATH]
    python3 -m release_prepare_lib bump <VERSION> [--pyproject PATH]

各 subcommand は :class:`ReleaseError` を捕まえて ``::error::<msg>`` を stderr
に書き exit 1 する。成功時は subcommand ごとに stdout へ結果を出力 (無い場合は
exit 0 のみ)。

### 設計判断

- ``sed`` ではなく Python で section range を決める: TOML は ``[tool.hatch.version]``
  のように section 内にも ``version = "..."`` が現れる場合があるため、[project]
  section の range を明示的に切ってその中だけで置換する。
- ``tomlkit`` など外部ライブラリには依存せず、stdlib (``tomllib`` + ``re``) で
  完結。依存の増加を避け maintainer install コスト / supply chain 的な attack
  surface を抑える。read-back verify は ``tomllib`` で行うので、書き換え結果の
  structural 整合性は別途保証される。
- encoding を ``utf-8`` 明示 + ``read_bytes`` / ``write_bytes`` ベースで、
  Windows checkout 等による silent な CRLF/LF 変換を避ける。
- ``ReleaseError`` は ``ValueError`` 派生で、CLI entry で catch して exit する。
  test 側は ``pytest.raises`` で assertion するため lib は ``sys.exit`` しない。
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tomllib

# release.yml の classify step と同一 spec (prefix `v` を剥いた形)。
# 末尾の pre-release suffix の N は ``(0|[1-9]\d*)`` で leading zero reject。
# PyPI が正規化 (``0.1.0b01`` → ``0.1.0b1``) すると同名衝突が起きるため。
PEP440_NATIVE_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)(0|[1-9][0-9]*))?$"
)

_PRE_SUFFIX_RE = re.compile(r"(a|b|rc)[0-9]+$")


class ReleaseError(ValueError):
    """release-prepare のユーザー向け error。CLI は str 化して ``::error::`` 出力。"""


# ---------- VERSION validation / classification ----------


def validate_version(version: str) -> None:
    """PEP 440 native public version でないなら :class:`ReleaseError`。"""
    if not PEP440_NATIVE_RE.match(version):
        raise ReleaseError(
            f"VERSION '{version}' is not a PEP 440 native public version. "
            "Expected X.Y.Z or X.Y.Z(a|b|rc)N (no leading zero on N). "
            "非 native 形 (0.1.0-beta-1 / 0.1.0.post1 / 0.1.0b01 等) は reject。"
        )


def classify(version: str) -> str:
    """``stable`` / ``pre-release`` の 2 値で分類。validate もここで行う。"""
    validate_version(version)
    return "pre-release" if _PRE_SUFFIX_RE.search(version) else "stable"


# ---------- pyproject.toml accessors ----------


def _load_pyproject(pyproject: pathlib.Path) -> dict:
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))


def get_project_version(
    pyproject: pathlib.Path = pathlib.Path("pyproject.toml"),
) -> str:
    """``[project].version`` を返す。static でないなら :class:`ReleaseError`。"""
    data = _load_pyproject(pyproject)
    project = data.get("project", {})
    if "version" not in project:
        raise ReleaseError(
            f"{pyproject} has no static project.version "
            "(dynamic version (`dynamic = [\"version\"]`) は未対応)"
        )
    return project["version"]


def bump_project_version(
    new_version: str,
    pyproject: pathlib.Path = pathlib.Path("pyproject.toml"),
) -> None:
    """``[project].version`` の 1 行を ``new_version`` に書き換える。

    section-aware: ``[project]`` section 開始 〜 次の top-level section header
    までの range で、最初の ``^version\\s*=\\s*"..."`` 行を置換する。
    ``[tool.foo].version`` 等は触らない。

    replacement は lambda 化し、``new_version`` に含まれる ``\\1`` 等の後方参照
    syntax を literal として扱う。encoding / newline を保存するため
    ``read_text(encoding="utf-8")`` + ``splitlines(keepends=True)`` で行単位
    編集し、元 file の行末 (LF / CRLF) をそのまま維持する。
    """
    src = pyproject.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)

    section_header = re.compile(r"^\[[^\]]+\]\s*$")
    start: int | None = None
    end = len(lines)
    for i, line in enumerate(lines):
        if line.rstrip("\r\n") == "[project]":
            start = i + 1
        elif start is not None and section_header.match(line):
            end = i
            break
    if start is None:
        raise ReleaseError(f"{pyproject}: [project] section not found")

    version_re = re.compile(r'^(version\s*=\s*")([^"]*)(")')
    for i in range(start, end):
        m = version_re.match(lines[i])
        if m:
            lines[i] = version_re.sub(
                lambda _, nv=new_version: f"{m.group(1)}{nv}{m.group(3)}",
                lines[i],
                count=1,
            )
            break
    else:
        raise ReleaseError(
            f"{pyproject}: [project].version line not found (dynamic version 未対応)"
        )

    pyproject.write_text("".join(lines), encoding="utf-8")


# ---------- CLI ----------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release_prepare_lib",
        description="release-prepare.sh が使う Python logic の CLI entry.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="VERSION を PEP 440 native で validate")
    p_validate.add_argument("version")

    p_classify = sub.add_parser("classify", help="stable / pre-release を stdout")
    p_classify.add_argument("version")

    p_get = sub.add_parser(
        "get-version", help="pyproject.toml の [project].version を stdout"
    )
    p_get.add_argument(
        "--pyproject",
        type=pathlib.Path,
        default=pathlib.Path("pyproject.toml"),
    )

    p_bump = sub.add_parser("bump", help="[project].version を書き換え")
    p_bump.add_argument("version")
    p_bump.add_argument(
        "--pyproject",
        type=pathlib.Path,
        default=pathlib.Path("pyproject.toml"),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "validate":
            validate_version(args.version)
        elif args.cmd == "classify":
            print(classify(args.version))
        elif args.cmd == "get-version":
            print(get_project_version(args.pyproject))
        elif args.cmd == "bump":
            # bump は validate_version もしておく (silent に無効 version を書かない)
            validate_version(args.version)
            bump_project_version(args.version, args.pyproject)
    except ReleaseError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
