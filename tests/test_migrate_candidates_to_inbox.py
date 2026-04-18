"""scripts/migrate_candidates_to_inbox.py のユニットテスト。

ADR 0001 Migration セクションに準拠:
1. policy_candidate.toml の [[candidates]] を 1 件 1 ファイルへ変換
2. agent="unknown", status="pending", schema_version=1 を付与
3. dedup（D6）で重複 skip → 再実行で冪等
4. 元ファイルを .bak rename（既存 .bak があれば skip）
5. 件数を stdout 表示
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest
import tomli_w

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from migrate_candidates_to_inbox import main, migrate  # noqa: E402

# inbox API 利用（dedup 検証）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "addons"))
from policy_inbox import list_requests  # noqa: E402


def _write_candidates(path: Path, records: list[dict]) -> None:
    path.write_text(tomli_w.dumps({"candidates": records}))


# === migrate (関数) ===


def test_migrate_creates_inbox_files(tmp_path: Path) -> None:
    src = tmp_path / "policy_candidate.toml"
    inbox = tmp_path / "inbox"
    _write_candidates(
        src,
        [
            {"type": "domain", "value": "example.com", "reason": "test"},
            {"type": "path", "domain": "x.com", "value": "/a/*", "reason": "y"},
        ],
    )
    n = migrate(src, inbox)
    assert n == 2
    items = list_requests(inbox)
    assert len(items) == 2


def test_migrate_sets_required_fields(tmp_path: Path) -> None:
    src = tmp_path / "policy_candidate.toml"
    inbox = tmp_path / "inbox"
    _write_candidates(
        src,
        [{"type": "domain", "value": "x.com", "reason": "r"}],
    )
    migrate(src, inbox)
    items = list_requests(inbox)
    assert items[0]["agent"] == "unknown"
    assert items[0]["status"] == "pending"
    assert items[0]["schema_version"] == 1
    assert "created_at" in items[0]


def test_migrate_idempotent_on_rerun(tmp_path: Path) -> None:
    """再実行で重複作成しない（D6 dedup）。"""
    src = tmp_path / "policy_candidate.toml"
    inbox = tmp_path / "inbox"
    _write_candidates(
        src,
        [{"type": "domain", "value": "x.com", "reason": "r"}],
    )
    n1 = migrate(src, inbox)
    n2 = migrate(src, inbox)
    assert n1 == 1
    assert n2 == 0
    assert len(list_requests(inbox)) == 1


def test_migrate_skips_partial_duplicates(tmp_path: Path) -> None:
    """既に inbox にある分は skip、新規分は追加。"""
    src = tmp_path / "policy_candidate.toml"
    inbox = tmp_path / "inbox"
    _write_candidates(
        src,
        [{"type": "domain", "value": "old.com", "reason": "r"}],
    )
    migrate(src, inbox)
    _write_candidates(
        src,
        [
            {"type": "domain", "value": "old.com", "reason": "r"},
            {"type": "domain", "value": "new.com", "reason": "r"},
        ],
    )
    n = migrate(src, inbox)
    assert n == 1  # new.com のみ新規
    assert len(list_requests(inbox)) == 2


def test_migrate_handles_missing_source(tmp_path: Path) -> None:
    """元ファイル不存在は 0 件で正常終了。"""
    src = tmp_path / "missing.toml"
    inbox = tmp_path / "inbox"
    n = migrate(src, inbox)
    assert n == 0


def test_migrate_handles_empty_candidates(tmp_path: Path) -> None:
    src = tmp_path / "policy_candidate.toml"
    inbox = tmp_path / "inbox"
    src.write_text("")  # candidates キー無し
    n = migrate(src, inbox)
    assert n == 0


# === main (CLI) ===


def test_main_renames_source_to_bak(tmp_path: Path) -> None:
    src = tmp_path / "policy_candidate.toml"
    inbox = tmp_path / "inbox"
    _write_candidates(
        src,
        [{"type": "domain", "value": "x.com", "reason": "r"}],
    )
    rc = main([
        "--candidates", str(src),
        "--inbox", str(inbox),
    ])
    assert rc == 0
    assert not src.exists()
    assert src.with_suffix(".toml.bak").exists()


def test_main_skips_bak_when_exists(tmp_path: Path) -> None:
    src = tmp_path / "policy_candidate.toml"
    bak = tmp_path / "policy_candidate.toml.bak"
    inbox = tmp_path / "inbox"
    _write_candidates(
        src,
        [{"type": "domain", "value": "x.com", "reason": "r"}],
    )
    bak.write_text("previous backup")  # 既存 .bak
    rc = main([
        "--candidates", str(src),
        "--inbox", str(inbox),
    ])
    assert rc == 0
    assert src.exists()  # rename 失敗 → 元ファイルは残る
    assert bak.read_text() == "previous backup"  # .bak は上書きされない


def test_main_prints_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "policy_candidate.toml"
    inbox = tmp_path / "inbox"
    _write_candidates(
        src,
        [
            {"type": "domain", "value": "a.com", "reason": "r"},
            {"type": "domain", "value": "b.com", "reason": "r"},
        ],
    )
    rc = main(["--candidates", str(src), "--inbox", str(inbox)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "2" in captured.out


def test_main_missing_source_returns_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main([
        "--candidates", str(tmp_path / "nonexistent.toml"),
        "--inbox", str(tmp_path / "inbox"),
    ])
    assert rc == 0
