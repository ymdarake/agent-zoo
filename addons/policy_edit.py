"""Policy editing and whitelist nurturing utilities.

Pure logic, no mitmproxy or Flask dependency.
Used by the dashboard for policy.toml editing and whitelist candidate management.
"""

import fcntl
import os
import sqlite3
import tempfile
import tomllib
from contextlib import contextmanager
from datetime import datetime

import tomli_w


@contextmanager
def policy_lock(policy_path: str):
    """policy.tomlのload-modify-saveを排他制御するコンテキストマネージャ。"""
    lock_path = f"{os.path.abspath(policy_path)}.lock"
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def atomic_write(path: str, content: str) -> None:
    """Atomically write content to a file.
    Tries tmpfile + rename first (POSIX atomic).
    Falls back to direct overwrite for Docker bind mounts where rename fails.
    """
    abs_path = os.path.abspath(path)
    dir_name = os.path.dirname(abs_path)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=dir_name, delete=False, suffix=".tmp"
        ) as f:
            f.write(content)
            tmp_path = f.name
        os.rename(tmp_path, abs_path)
    except OSError:
        # Docker bind mount: rename may fail (device or resource busy)
        # Fall back to direct overwrite
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        with open(abs_path, "w") as f:
            f.write(content)


def _load_policy(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _save_policy(path: str, policy: dict) -> None:
    content = tomli_w.dumps(policy)
    atomic_write(path, content)


def add_to_allow_list(policy_path: str, domain: str) -> None:
    """policy.tomlのdomains.allow.listにドメインを追加する。自動でファイルロックを取得。"""
    with policy_lock(policy_path):
        policy = _load_policy(policy_path)
        allow_list = policy.setdefault("domains", {}).setdefault("allow", {}).setdefault(
            "list", []
        )
        if domain not in allow_list:
            allow_list.append(domain)
        _save_policy(policy_path, policy)


def add_to_dismissed(policy_path: str, domain: str, reason: str) -> None:
    """policy.tomlのdomains.dismissedにドメインと理由を追加する。自動でファイルロックを取得。"""
    with policy_lock(policy_path):
        policy = _load_policy(policy_path)
        dismissed = policy.setdefault("domains", {}).setdefault("dismissed", {})
        dismissed[domain] = {
            "reason": reason,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        _save_policy(policy_path, policy)


def add_to_paths_allow(policy_path: str, domain: str, path_pattern: str) -> None:
    """policy.tomlのpaths.allowにドメイン+パスパターンを追加する。自動でファイルロックを取得。"""
    with policy_lock(policy_path):
        policy = _load_policy(policy_path)
        paths_allow = policy.setdefault("paths", {}).setdefault("allow", {})
        patterns = paths_allow.get(domain, [])
        if path_pattern not in patterns:
            patterns.append(path_pattern)
        paths_allow[domain] = patterns
        _save_policy(policy_path, policy)


def remove_from_dismissed(policy_path: str, domain: str) -> None:
    """policy.tomlのdomains.dismissedからドメインを削除する。自動でファイルロックを取得。"""
    with policy_lock(policy_path):
        policy = _load_policy(policy_path)
        dismissed = policy.get("domains", {}).get("dismissed", {})
        dismissed.pop(domain, None)
        _save_policy(policy_path, policy)


def get_whitelist_candidates(
    db_path: str, policy_path: str
) -> list[dict]:
    """blocksテーブルから集計し、許可候補を返す。
    既にallow listまたはdismissedにあるドメインは除外する。
    """
    policy = _load_policy(policy_path)
    allow_list = set(
        policy.get("domains", {}).get("allow", {}).get("list", [])
    )
    dismissed = set(
        policy.get("domains", {}).get("dismissed", {}).keys()
    )
    excluded = allow_list | dismissed

    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "SELECT host, COUNT(*) as count "
            "FROM blocks GROUP BY host ORDER BY count DESC"
        ).fetchall()
    finally:
        db.close()

    candidates = []
    for row in rows:
        if row["host"] not in excluded:
            candidates.append({"host": row["host"], "count": row["count"]})

    return candidates
