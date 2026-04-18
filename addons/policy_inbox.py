"""Policy inbox storage layer (pure logic, no mitmproxy/Flask deps).

ADR 0001 (docs/adr/0001-policy-inbox.md) D9 を実装する。

inbox = ディレクトリに 1 リクエスト 1 TOML ファイル。
公開関数:
    add_request(inbox_dir, record) -> str | None
    list_requests(inbox_dir, status=None) -> list[dict]
    mark_status(inbox_dir, record_id, new_status, reason="") -> None
    bulk_mark_status(inbox_dir, record_ids, new_status) -> int
    cleanup_expired(inbox_dir, days) -> int
"""

from __future__ import annotations

import hashlib
import os
import secrets
import tomllib
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import tomli_w

VALID_STATUSES: tuple[str, ...] = ("pending", "accepted", "rejected", "expired")
TERMINAL_STATUSES: tuple[str, ...] = ("accepted", "rejected", "expired")
_CONTENT_HASH_LEN = 12  # 48-bit, ~10^14 衝突確率
_SHORTID_BYTES = 2  # 4 文字 hex（同秒・同 content race 回避用）


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_hash(record: dict[str, Any]) -> str:
    """type + value + domain を SHA256 した先頭 12 文字。

    同一内容の race を file 名で uniqueness 保証するため使用（ADR D6）。
    """
    key = f"{record.get('type')}|{record.get('value')}|{record.get('domain', '')}"
    return hashlib.sha256(key.encode()).hexdigest()[:_CONTENT_HASH_LEN]


def _new_file_id(record: dict[str, Any]) -> str:
    """ADR D2: `{ISO8601-dashes}-{shortid}-{contenthash}.toml` のうち拡張子を除く部分。

    - ISO8601: 秒精度
    - shortid: 4 文字 hex（同秒・同 content の race 回避）
    - contenthash: 12 文字 hex（dedup glob match に使用）
    """
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    short = secrets.token_hex(_SHORTID_BYTES)
    return f"{ts}-{short}-{_content_hash(record)}"


def _ensure_dir(inbox_dir: str | Path) -> Path:
    p = Path(inbox_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _atomic_create(path: Path, content: str) -> bool:
    """O_CREAT|O_EXCL で原子的にファイル作成。既存なら False。

    ADR D5: write は POSIX レベルでアトミック。
    """
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except Exception:
        try:
            os.unlink(str(path))
        except OSError:
            pass
        raise
    return True


def _atomic_overwrite(path: Path, content: str) -> None:
    """既存ファイルの atomic 書き換え（tempfile + rename）。

    ADR D5: status 遷移用。
    """
    import tempfile

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _parse_iso(s: str) -> datetime | None:
    """ISO8601 文字列を datetime に変換（失敗時 None）。

    `Z` サフィックスを `+00:00` に置換して fromisoformat に渡す。
    """
    if not s:
        return None
    try:
        normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _has_pending_with_hash(inbox: Path, content_hash: str) -> bool:
    """同一 content hash の pending が存在するか。"""
    for p in inbox.glob(f"*-{content_hash}.toml"):
        try:
            with p.open("rb") as f:
                d = tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError):
            continue
        if d.get("status") == "pending":
            return True
    return False


def add_request(
    inbox_dir: str | Path, record: dict[str, Any]
) -> str | None:
    """新規 request を inbox に追加し、record_id（ファイル stem）を返す。

    `record` は ADR Schema 準拠の dict。
    `schema_version` / `created_at` / `status` は未指定なら自動付与。
    同一内容（type+value+domain）の pending が既存なら作成 skip → `None`（ADR D6）。
    """
    inbox = _ensure_dir(inbox_dir)
    ch = _content_hash(record)
    if _has_pending_with_hash(inbox, ch):
        return None

    payload = dict(record)
    payload.setdefault("schema_version", 1)
    payload.setdefault("created_at", _now_iso())
    payload.setdefault("status", "pending")

    file_id = _new_file_id(record)
    path = inbox / f"{file_id}.toml"
    # 同一秒・同一 content の race は O_EXCL で構造的に防止
    if not _atomic_create(path, tomli_w.dumps(payload)):
        return None
    return file_id


def list_requests(
    inbox_dir: str | Path, status: str | None = None
) -> list[dict[str, Any]]:
    """inbox 内の request を列挙する。

    各 dict には `_id` (= ファイル stem) を付与。
    `status` 指定時はフィルタ、created_at 昇順で返す。
    破損 TOML は warning を出して skip。
    """
    inbox = Path(inbox_dir)
    if not inbox.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(inbox.glob("*.toml")):
        try:
            with p.open("rb") as f:
                data = tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError) as e:
            warnings.warn(
                f"policy_inbox: skip broken file {p.name}: {e}",
                stacklevel=2,
            )
            continue
        if status is not None and data.get("status") != status:
            continue
        data["_id"] = p.stem
        out.append(data)
    out.sort(key=lambda d: str(d.get("created_at", "")))
    return out


def mark_status(
    inbox_dir: str | Path,
    record_id: str,
    new_status: str,
    reason: str = "",
) -> None:
    """指定 record の status を更新する（ADR D5: atomic overwrite）。

    NOTE: cleanup_expired と並行実行された場合、後勝ちで更新ロストの可能性あり。
    現状は serialize 運用前提（dashboard / cron 経由）。
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {new_status}")
    path = Path(inbox_dir) / f"{record_id}.toml"
    if not path.exists():
        raise FileNotFoundError(f"record not found: {record_id}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    data["status"] = new_status
    data["status_updated_at"] = _now_iso()
    if reason:
        data["status_reason"] = reason
    _atomic_overwrite(path, tomli_w.dumps(data))


def bulk_mark_status(
    inbox_dir: str | Path,
    record_ids: list[str],
    new_status: str,
) -> int:
    """複数 ID で status を一括更新（dashboard の bulk 操作用）。

    成功件数を返す。存在しない ID / invalid status の record は skip。
    """
    count = 0
    for rid in record_ids:
        try:
            mark_status(inbox_dir, rid, new_status)
        except (FileNotFoundError, ValueError):
            continue
        count += 1
    return count


def cleanup_expired(inbox_dir: str | Path, days: int) -> int:
    """N 日経過の `pending` を `expired` 化し、古い終端状態を削除する。

    処理件数（expired 化 + 削除の合計）を返す。
    時刻比較は `datetime.fromisoformat` ベースで TZ / micros 揺らぎに強い。
    """
    inbox = Path(inbox_dir)
    if not inbox.exists():
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    count = 0
    for r in list_requests(inbox):
        rid = r["_id"]
        path = inbox / f"{rid}.toml"
        status = r.get("status")
        created_dt = _parse_iso(str(r.get("created_at", "")))
        if status == "pending":
            if created_dt is not None and created_dt < cutoff:
                mark_status(inbox, rid, "expired")
                count += 1
        elif status in TERMINAL_STATUSES:
            updated_dt = _parse_iso(
                str(r.get("status_updated_at") or r.get("created_at", ""))
            )
            if updated_dt is not None and updated_dt < cutoff:
                path.unlink(missing_ok=True)
                count += 1
    return count
