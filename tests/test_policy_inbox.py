"""addons/policy_inbox.py のユニットテスト（ADR 0001 D9 実装の検証）。"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest
import tomli_w

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "addons"))
from policy_inbox import (  # noqa: E402
    _atomic_create,
    _content_hash,
    add_request,
    bulk_mark_status,
    cleanup_expired,
    list_requests,
    mark_status,
)


def _make_record(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "agent": "claude",
        "type": "domain",
        "value": "example.com",
        "reason": "test",
        "status": "pending",
    }
    base.update(overrides)
    return base


# === add_request ===


def test_add_request_creates_file(tmp_path: Path) -> None:
    file_id = add_request(tmp_path, _make_record())
    assert file_id is not None
    assert (tmp_path / f"{file_id}.toml").exists()


def test_add_request_creates_inbox_dir_if_missing(tmp_path: Path) -> None:
    inbox = tmp_path / "missing" / "inbox"
    file_id = add_request(inbox, _make_record())
    assert file_id is not None
    assert inbox.exists()


def test_add_request_dedup_returns_none(tmp_path: Path) -> None:
    add_request(tmp_path, _make_record(value="dup.com"))
    result = add_request(tmp_path, _make_record(value="dup.com"))
    assert result is None
    files = list(tmp_path.glob("*.toml"))
    assert len(files) == 1


def test_add_request_allows_after_rejection(tmp_path: Path) -> None:
    rid = add_request(tmp_path, _make_record(value="x.com"))
    mark_status(tmp_path, rid, "rejected")
    rid2 = add_request(tmp_path, _make_record(value="x.com"))
    assert rid2 is not None
    assert rid2 != rid


def test_add_request_dedup_only_in_pending(tmp_path: Path) -> None:
    """rejected/accepted/expired との重複は許容（D6）。"""
    rid = add_request(tmp_path, _make_record(value="y.com"))
    mark_status(tmp_path, rid, "accepted")
    rid2 = add_request(tmp_path, _make_record(value="y.com"))
    assert rid2 is not None


def test_add_request_distinguishes_by_domain(tmp_path: Path) -> None:
    """type=path で domain が違えば別 request（D6）。"""
    add_request(
        tmp_path,
        _make_record(type="path", value="/a", domain="x.com"),
    )
    rid = add_request(
        tmp_path,
        _make_record(type="path", value="/a", domain="y.com"),
    )
    assert rid is not None


def test_add_request_persists_record(tmp_path: Path) -> None:
    rid = add_request(tmp_path, _make_record(value="z.com", reason="why"))
    with (tmp_path / f"{rid}.toml").open("rb") as f:
        data = tomllib.load(f)
    assert data["value"] == "z.com"
    assert data["reason"] == "why"
    assert data["status"] == "pending"
    assert "created_at" in data


# === list_requests ===


def test_list_requests_empty(tmp_path: Path) -> None:
    assert list_requests(tmp_path) == []


def test_list_requests_returns_id(tmp_path: Path) -> None:
    rid = add_request(tmp_path, _make_record())
    items = list_requests(tmp_path)
    assert len(items) == 1
    assert items[0]["_id"] == rid


def test_list_requests_filter_status(tmp_path: Path) -> None:
    r1 = add_request(tmp_path, _make_record(value="a.com"))
    r2 = add_request(tmp_path, _make_record(value="b.com"))
    mark_status(tmp_path, r2, "rejected")
    pendings = list_requests(tmp_path, status="pending")
    rejecteds = list_requests(tmp_path, status="rejected")
    assert {p["_id"] for p in pendings} == {r1}
    assert {p["_id"] for p in rejecteds} == {r2}


def test_list_requests_skips_invalid_toml(tmp_path: Path) -> None:
    add_request(tmp_path, _make_record())
    (tmp_path / "broken.toml").write_text("not = valid = toml")
    items = list_requests(tmp_path)
    assert len(items) == 1


def test_list_requests_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert list_requests(tmp_path / "missing") == []


# === mark_status ===


def test_mark_status_updates_file(tmp_path: Path) -> None:
    rid = add_request(tmp_path, _make_record())
    mark_status(tmp_path, rid, "accepted")
    items = list_requests(tmp_path, status="accepted")
    assert len(items) == 1
    assert items[0]["status_updated_at"] != ""


def test_mark_status_with_reason(tmp_path: Path) -> None:
    rid = add_request(tmp_path, _make_record())
    mark_status(tmp_path, rid, "rejected", reason="not necessary")
    items = list_requests(tmp_path, status="rejected")
    assert items[0]["status_reason"] == "not necessary"


def test_mark_status_unknown_record_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        mark_status(tmp_path, "nonexistent", "accepted")


def test_mark_status_invalid_status_raises(tmp_path: Path) -> None:
    rid = add_request(tmp_path, _make_record())
    with pytest.raises(ValueError, match="invalid status"):
        mark_status(tmp_path, rid, "WRONG")


# === bulk_mark_status ===


def test_bulk_mark_status_all_succeed(tmp_path: Path) -> None:
    r1 = add_request(tmp_path, _make_record(value="a.com"))
    r2 = add_request(tmp_path, _make_record(value="b.com"))
    n = bulk_mark_status(tmp_path, [r1, r2], "accepted")
    assert n == 2


def test_bulk_mark_status_skips_unknown(tmp_path: Path) -> None:
    r1 = add_request(tmp_path, _make_record())
    n = bulk_mark_status(tmp_path, [r1, "ghost"], "accepted")
    assert n == 1


# === cleanup_expired ===


def test_cleanup_expired_marks_old_pending_as_expired(tmp_path: Path) -> None:
    old = _make_record(value="old.com")
    old["created_at"] = "2020-01-01T00:00:00Z"
    fid = "2020-01-01T00-00-00-deadbeef"
    (tmp_path / f"{fid}.toml").write_text(tomli_w.dumps(old))
    n = cleanup_expired(tmp_path, days=30)
    assert n == 1
    items = list_requests(tmp_path, status="expired")
    assert len(items) == 1


def test_cleanup_expired_keeps_recent_pending(tmp_path: Path) -> None:
    add_request(tmp_path, _make_record())
    n = cleanup_expired(tmp_path, days=30)
    assert n == 0


def test_cleanup_expired_deletes_old_terminal(tmp_path: Path) -> None:
    rec = _make_record(value="old.com")
    rec["status"] = "accepted"
    rec["created_at"] = "2020-01-01T00:00:00Z"
    rec["status_updated_at"] = "2020-01-02T00:00:00Z"
    fid = "2020-01-01T00-00-00-cafef00d"
    (tmp_path / f"{fid}.toml").write_text(tomli_w.dumps(rec))
    n = cleanup_expired(tmp_path, days=30)
    assert n == 1
    assert not (tmp_path / f"{fid}.toml").exists()


def test_cleanup_expired_missing_dir(tmp_path: Path) -> None:
    assert cleanup_expired(tmp_path / "missing", days=30) == 0


def test_cleanup_expired_handles_microseconds_iso(tmp_path: Path) -> None:
    """マイクロ秒や TZ オフセット形式の created_at でも比較できる（fromisoformat）。"""
    rec = _make_record(value="micro.com")
    rec["created_at"] = "2020-01-01T00:00:00.123456+00:00"
    fid = "2020-01-01T00-00-00-aaaaaaaaaaaa"
    (tmp_path / f"{fid}.toml").write_text(tomli_w.dumps(rec))
    assert cleanup_expired(tmp_path, days=30) == 1


# === atomicity / dedup primitives ===


def test_content_hash_consistent_for_same_input() -> None:
    a = _content_hash({"type": "domain", "value": "x.com", "domain": ""})
    b = _content_hash({"type": "domain", "value": "x.com", "domain": ""})
    assert a == b


def test_content_hash_distinguishes_domain() -> None:
    a = _content_hash({"type": "path", "value": "/a", "domain": "x.com"})
    b = _content_hash({"type": "path", "value": "/a", "domain": "y.com"})
    assert a != b


def test_atomic_create_returns_false_when_file_exists(tmp_path: Path) -> None:
    p = tmp_path / "f.toml"
    assert _atomic_create(p, "first") is True
    assert _atomic_create(p, "second") is False
    assert p.read_text() == "first"  # 後続書込は無視される


# === observability ===


def test_list_requests_warns_on_broken_toml(tmp_path: Path) -> None:
    add_request(tmp_path, _make_record())
    (tmp_path / "broken.toml").write_text("not = valid = toml")
    with pytest.warns(UserWarning, match="skip broken file"):
        list_requests(tmp_path)
