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
    - scheme は lowercase に、host も lowercase に正規化（DNS は case-insensitive、
      DB 集計でドメインがばらつかないように）
    - port / path はそのまま維持
    - 制御文字 (CR / LF / NUL / 0x00-0x1F / 0x7F) を含む URL は `[invalid-url]`
      （log injection / HTTP request smuggling 対策、self-review H-2）
    - parse 失敗や空文字列は `[invalid-url]` 固定（attacker-controlled 文字列の
      DB 投入を防ぐ fail-safe）

    詳細根拠: docs/dev/security-notes.md の「URL scrub の設計根拠」節。
    """
    if not url:
        return "[invalid-url]"
    # 制御文字混入は不正値（attacker による偽装 URL を弾く、self-review H-2）
    if any(ord(c) < 0x20 or c == "\x7f" for c in url):
        return "[invalid-url]"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[invalid-url]"
    if not parts.scheme or not parts.netloc:
        return "[invalid-url]"

    # netloc を userinfo と host[:port] に分解。host は DNS case-insensitive のため
    # lowercase に正規化（self-review M-2: DB 集計の "EXAMPLE.com" / "example.com"
    # ばらつき防止）
    netloc = parts.netloc
    if "@" in netloc:
        _, _, host_port = netloc.rpartition("@")
        netloc = f"[redacted]@{host_port.lower()}"
    else:
        netloc = netloc.lower()

    query = "[redacted]" if parts.query else ""
    # fragment は完全削除（urlunsplit に "" を渡す）
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def _parse_content_length(header: str | None) -> int | None:
    """Content-Length ヘッダを非負整数にパース。

    RFC 7230 §3.3.2: `Content-Length = 1*DIGIT`（純粋な ASCII 数字のみ）。
    Python `int()` は `+10` / `1_000` を許容するが、HTTP 仕様違反なので
    `str.isdigit()` で先に弾く（self-review M-4）。

    - None / 空文字列 / 非数値（`+`, `_`, 小数点, 単位等）はすべて None
    - 負値は実装上 isdigit で除外されるが念のため n >= 0 を保つ
    - 前後空白は strip
    - 不明の場合は caller 側で body 検査 (check_payload) に委ねる
    """
    if header is None:
        return None
    value = header.strip()
    if not value or not value.isdigit():
        return None
    try:
        n = int(value)
    except ValueError:
        return None
    return n if n >= 0 else None
