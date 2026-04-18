"""URL scrub + Content-Length 前チェックの helper（Sprint 006 PR D, M-2 / M-6）。

mitmproxy への依存を持たず、policy_enforcer と tests から同じロジックを共用できる
ようにするため独立モジュールとした。詳細設計は docs/dev/security-notes.md 参照。
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

# mitmproxy の `--set body_size_limit=1m` と揃えた addon-level fail-closed 閾値。
# Content-Length ヘッダがこの値を超える request は 413 で遮断する（M-6）。
_MAX_BODY_BYTES = 1024 * 1024


def scrub_url(url: str) -> str:
    """URL から機密情報候補を redact する。

    仕様:
    - userinfo (`user:pass@`) → `[redacted]@` 置換
    - query (`?...`) → `?[redacted]` （query 存在の可観測性は保持）
    - fragment (`#...`) → 削除 (OAuth implicit flow 等の token 漏洩対策)
    - scheme / host / port / path はそのまま維持（ドメイン別集計に必要）
    - parse 失敗や空文字列は `[invalid-url]` 固定（attacker-controlled 文字列の
      DB 投入を防ぐ fail-safe）

    詳細根拠: docs/dev/security-notes.md の「URL scrub の設計根拠」節。
    """
    if not url:
        return "[invalid-url]"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[invalid-url]"
    if not parts.scheme or not parts.netloc:
        return "[invalid-url]"

    # netloc を userinfo と host[:port] に分解
    netloc = parts.netloc
    if "@" in netloc:
        _, _, host_port = netloc.rpartition("@")
        netloc = f"[redacted]@{host_port}"

    query = "[redacted]" if parts.query else ""
    # fragment は完全削除（urlunsplit に "" を渡す）
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def _parse_content_length(header: str | None) -> int | None:
    """Content-Length ヘッダを非負整数にパース。

    - None / 空文字列 / 非数値 / 負値はすべて None（「不明」扱い）
    - 前後空白は strip
    - 不明の場合は caller 側で body 検査 (check_payload) に委ねる
    """
    if header is None:
        return None
    value = header.strip()
    if not value:
        return None
    try:
        n = int(value)
    except ValueError:
        return None
    return n if n >= 0 else None
