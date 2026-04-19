"""harness.db ファイル群の file 権限を 600 に強制する helper（Sprint 006 PR D, G3-B1）。

policy_enforcer が sqlite に書き込む request body / tool_use input / URL
(scrub 後) は PII / 機密情報を含むため、同一 host の他ユーザーからの read を
防ぐために chmod 600 を明示的に強制する。

bind mount 環境で chmod が EPERM を返すケースに備え、失敗時は log_fn 経由で
通知し fail-safe で続行する。詳細: docs/dev/security-notes.md。
"""

from __future__ import annotations

import os
from typing import Callable, Optional

# WAL モードで追加生成される付随ファイル
_DB_SUFFIXES = ("", "-wal", "-shm")

LogFn = Callable[[str], None]


def secure_db_file(db_path: str, log_fn: Optional[LogFn] = None) -> None:
    """db / db-wal / db-shm を chmod 600 に設定する（ベストエフォート）。

    - 各ファイルが存在しない場合は skip（SQLite が未生成）
    - chmod が OSError を返した場合は `log_fn(message)` で通知して続行
    - log_fn 未指定時は silent （デフォルト挙動）
    """
    for suffix in _DB_SUFFIXES:
        target = db_path + suffix
        if not os.path.exists(target):
            continue
        # symlink follow を抑止 (self-review M-1: TOCTOU で /etc/* 等を
        # chmod 600 化されないように)。lchmod が無い OS / ファイルシステムでは
        # follow_symlinks=False が NotImplementedError → 明示的に islink チェック。
        try:
            try:
                os.chmod(target, 0o600, follow_symlinks=False)
            except (NotImplementedError, OSError) as inner:
                if isinstance(inner, NotImplementedError) or getattr(inner, "errno", None) is None:
                    if os.path.islink(target):
                        if log_fn is not None:
                            log_fn(f"refusing to chmod symlink: {target}")
                        continue
                    os.chmod(target, 0o600)
                else:
                    raise
        except OSError as e:
            if log_fn is not None:
                log_fn(f"chmod {target} failed: {e}")
