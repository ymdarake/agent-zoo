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
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=dir_name, delete=False, suffix=".tmp"
        ) as f:
            f.write(content)
            tmp_path = f.name
        os.rename(tmp_path, abs_path)
    except OSError:
        # Docker bind mount: rename may fail (device or resource busy)
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        with open(abs_path, "w") as f:
            f.write(content)


def _runtime_path(policy_path: str) -> str:
    """policy.tomlに対応するruntime TOMLパスを返す。"""
    if policy_path.endswith(".toml"):
        return policy_path[:-5] + ".runtime.toml"
    return policy_path + ".runtime"


def _load_policy(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _load_runtime(policy_path: str) -> dict:
    """runtime TOMLを読み込む。存在しなければ空辞書。"""
    rt_path = _runtime_path(policy_path)
    if os.path.exists(rt_path):
        with open(rt_path, "rb") as f:
            return tomllib.load(f)
    return {}


def _save_runtime(policy_path: str, runtime: dict) -> None:
    """runtime TOMLに書き込む（base policy.tomlは変更しない）。"""
    content = tomli_w.dumps(runtime)
    atomic_write(_runtime_path(policy_path), content)


def add_to_allow_list(policy_path: str, domain: str) -> None:
    """runtime TOMLのdomains.allow.listにドメインを追加する。"""
    rt_path = _runtime_path(policy_path)
    with policy_lock(rt_path):
        runtime = _load_runtime(policy_path)
        allow_list = runtime.setdefault("domains", {}).setdefault("allow", {}).setdefault(
            "list", []
        )
        if domain not in allow_list:
            allow_list.append(domain)
        _save_runtime(policy_path, runtime)


def add_to_dismissed(policy_path: str, domain: str, reason: str) -> None:
    """runtime TOMLのdomains.dismissedにドメインと理由を追加する。"""
    rt_path = _runtime_path(policy_path)
    with policy_lock(rt_path):
        runtime = _load_runtime(policy_path)
        dismissed = runtime.setdefault("domains", {}).setdefault("dismissed", {})
        dismissed[domain] = {
            "reason": reason,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        _save_runtime(policy_path, runtime)


def add_to_paths_allow(policy_path: str, domain: str, path_pattern: str) -> None:
    """runtime TOMLのpaths.allowにドメイン+パスパターンを追加する。"""
    rt_path = _runtime_path(policy_path)
    with policy_lock(rt_path):
        runtime = _load_runtime(policy_path)
        paths_allow = runtime.setdefault("paths", {}).setdefault("allow", {})
        patterns = paths_allow.get(domain, [])
        if path_pattern not in patterns:
            patterns.append(path_pattern)
        paths_allow[domain] = patterns
        _save_runtime(policy_path, runtime)


def remove_from_allow_list(policy_path: str, domain: str) -> None:
    """runtime TOMLのdomains.allow.listからドメインを削除する。"""
    rt_path = _runtime_path(policy_path)
    with policy_lock(rt_path):
        runtime = _load_runtime(policy_path)
        domains = runtime.get("domains", {})
        allow = domains.get("allow", {})
        allow_list = allow.get("list", [])
        if domain not in allow_list:
            return
        allow_list.remove(domain)
        _save_runtime(policy_path, runtime)


def remove_from_paths_allow(policy_path: str, domain: str, path_pattern: str) -> None:
    """runtime TOMLのpaths.allowからパスパターンを削除する。"""
    rt_path = _runtime_path(policy_path)
    with policy_lock(rt_path):
        runtime = _load_runtime(policy_path)
        paths_allow = runtime.get("paths", {}).get("allow", {})
        patterns = paths_allow.get(domain, [])
        if path_pattern in patterns:
            patterns.remove(path_pattern)
            if not patterns:
                paths_allow.pop(domain, None)
        _save_runtime(policy_path, runtime)


def remove_from_dismissed(policy_path: str, domain: str) -> None:
    """runtime TOMLのdomains.dismissedからドメインを削除する。"""
    rt_path = _runtime_path(policy_path)
    with policy_lock(rt_path):
        runtime = _load_runtime(policy_path)
        dismissed = runtime.get("domains", {}).get("dismissed", {})
        dismissed.pop(domain, None)
        _save_runtime(policy_path, runtime)


def get_whitelist_candidates(
    db_path: str, policy_path: str
) -> list[dict]:
    """blocksテーブルから集計し、許可候補を返す。
    既にallow listまたはdismissedにあるドメインは除外する。
    """
    policy = _load_policy(policy_path)
    runtime = _load_runtime(policy_path)
    # base + runtime の allow list を結合
    allow_list = set(
        policy.get("domains", {}).get("allow", {}).get("list", [])
        + runtime.get("domains", {}).get("allow", {}).get("list", [])
    )
    # base + runtime の dismissed を結合
    dismissed = set(
        policy.get("domains", {}).get("dismissed", {}).keys()
    ) | set(
        runtime.get("domains", {}).get("dismissed", {}).keys()
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
