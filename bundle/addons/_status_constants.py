"""log status の中央集権定数（self-review H-1 対応）。

新しい block 系 status を追加するたびに proxy / dashboard / 集計クエリを
同期更新する漏れを防ぐため、唯一の真実として本モジュールを参照する。

dashboard 側は sqlite SQL の `IN (?, ?, ...)` placeholder で利用する想定。
"""

from __future__ import annotations

# 通常許容 (ALLOWED) ではない、ブロック系 status の集合。
# `requests` テーブルの status と `blocks` テーブルへの転記判定に共通利用。
BLOCK_STATUSES: tuple[str, ...] = (
    "BLOCKED",
    "RATE_LIMITED",
    "PAYLOAD_BLOCKED",
    "URL_SECRET_BLOCKED",  # Sprint 006 PR D, M-2
    "BODY_TOO_LARGE",  # Sprint 006 PR D, M-6
)


def block_statuses_sql_placeholders() -> str:
    """`?, ?, ...` の placeholder 文字列を返す（SQL の IN 句で使う）。"""
    return ", ".join(["?"] * len(BLOCK_STATUSES))
