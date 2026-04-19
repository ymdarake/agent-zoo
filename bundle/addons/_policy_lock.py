"""policy.toml の cross-container shared/exclusive lock helper (Sprint 006 PR F)。

包括レビュー M-8 (TOCTOU) を解決するため proxy / dashboard 両方から writable
な共有 lock dir (default `/locks`) 経由で fcntl.flock を取得する。

PR D plan review で発覚した「proxy container の `/config/` ro mount に
LOCK_SH lockfile を書こうとして EROFS」を回避する。

API:
- `lock_path_for(policy_path) -> str`: lock file path を共有 dir 配下にマップ
- `policy_lock_shared(policy_path)`: reader 用 LOCK_SH。失敗時 warn + passthrough
  (ADR 0005 fail-closed と両立する best-effort)
- `policy_lock_exclusive(policy_path)`: writer 用 LOCK_EX。失敗時 raise
  (一貫性破壊を防ぐ fail-closed)

詳細設計: docs/plans/sprint-006-pr-f.md および docs/dev/security-notes.md。
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# default lock dir (proxy / dashboard 両方に bind mount)。
# host-mode (zoo proxy claude 等) では /locks が無いので fallback path に流れる。
_DEFAULT_LOCK_DIR = "/locks"

# self-review #3 (Low): fallback が選ばれた lock path を 1 回だけ warn log する
# ための memo set。container-mode で `/locks` mount 忘れ等の構成不備を観測可能化。
_warned_fallbacks: set[str] = set()


def _resolve_lock_dir() -> str:
    """`POLICY_LOCK_DIR` env を返す。未設定なら `_DEFAULT_LOCK_DIR`。"""
    return os.environ.get("POLICY_LOCK_DIR", _DEFAULT_LOCK_DIR)


def _is_dir_writable(path: str) -> bool:
    return os.path.isdir(path) and os.access(path, os.W_OK)


def lock_path_for(policy_path: str) -> str:
    """policy file 用の lock file path を共有 lock dir 配下にマップ。

    Fallback 順:
    1. POLICY_LOCK_DIR (default /locks) が writable → `<dir>/<basename>.lock`
    2. policy_path と同じ dir が writable → `<policy_path>.lock` (host-mode 互換)
    3. tempdir → `<tmp>/agent_zoo_<basename>.lock`

    self-review #3 (Low): 候補 1 (env-resolved dir) が選ばれなかった場合は
    1 回だけ warn log を出す (構成不備の observability)。
    """
    base = os.path.basename(policy_path)
    primary = os.path.join(_resolve_lock_dir(), f"{base}.lock")
    candidates = [
        primary,
        f"{os.path.abspath(policy_path)}.lock",
        os.path.join(tempfile.gettempdir(), f"agent_zoo_{base}.lock"),
    ]
    for path in candidates:
        parent = os.path.dirname(path) or "."
        if _is_dir_writable(parent):
            if path != primary and policy_path not in _warned_fallbacks:
                _warned_fallbacks.add(policy_path)
                logger.warning(
                    "policy_lock: primary lock dir %r not writable for %r, "
                    "fell back to %r. cross-container coordination may be lost. "
                    "Check POLICY_LOCK_DIR env / docker-compose.yml `./locks:/locks` mount.",
                    os.path.dirname(primary),
                    policy_path,
                    path,
                )
            return path
    # fallback の last resort (tempdir は通常 writable)
    return candidates[-1]


def _open_lock_file(lock_path: str) -> int:
    """lock file を open してファイル descriptor を返す。

    self-review M3 対応: O_NOFOLLOW + 0o600 で symlink 攻撃 / world-readable
    を防ぐ。ファイルが存在しない場合は新規作成。
    """
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(lock_path, flags, 0o600)


@contextmanager
def policy_lock_shared(policy_path: str):
    """reader 用 shared lock (LOCK_SH)。

    Rev.2 (self-review H1): lock 取得失敗時は logger.warning で観測可能化した上で
    passthrough。reader は ADR 0005 fail-closed 原則と両立する best-effort 動作。

    使用例:
        with policy_lock_shared(policy_path):
            with open(policy_path, "rb") as f:
                ...
    """
    lock_path = lock_path_for(policy_path)
    fd: int | None = None
    try:
        fd = _open_lock_file(lock_path)
        fcntl.flock(fd, fcntl.LOCK_SH)
    except OSError as e:
        # EROFS / EPERM / ENOENT 等は warn + passthrough（reader best-effort）
        logger.warning(
            f"policy_lock_shared: lock acquire failed for {policy_path!r} "
            f"(lock_path={lock_path!r}, errno={e.errno}, msg={e!s}). "
            f"Continuing without lock (best-effort)."
        )
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = None
    try:
        yield
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


@contextmanager
def policy_lock_exclusive(policy_path: str):
    """writer 用 exclusive lock (LOCK_EX)。

    Rev.2 (self-review H1): lock 取得失敗時は OSError を raise (fail-closed)。
    writer の失敗は「ユーザー操作 (whitelist accept) が無音で失敗」を意味するため、
    UI 側で 503 を返して retry できるようにする。

    使用例:
        with policy_lock_exclusive(policy_path):
            # write policy_path safely
    """
    lock_path = lock_path_for(policy_path)
    fd = _open_lock_file(lock_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


# 互換性: errno を re-export する利用ケースがあれば
__all__ = [
    "lock_path_for",
    "policy_lock_shared",
    "policy_lock_exclusive",
    "errno",
]
