"""Tests for `addons.policy_enforcer._parse_content_length` (Sprint 006 PR D, M-6).

mitmproxy の `body_size_limit=1m` は 1MB 超で stream pass-through するため
secret_patterns 検査が silently bypass される恐れ。addon 側で Content-Length
ヘッダを事前チェックし、閾値超過は 413 fail-closed する。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle"))

from addons._url_scrub import _MAX_BODY_BYTES, _parse_content_length  # noqa: E402


class TestParseContentLength:
    def test_valid_integer(self):
        assert _parse_content_length("1024") == 1024

    def test_zero_allowed(self):
        # Content-Length: 0 は GET / OPTIONS で正常
        assert _parse_content_length("0") == 0

    def test_none_returns_none(self):
        # header 欠落 (chunked transfer encoding 等) は None
        assert _parse_content_length(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_content_length("") is None

    def test_negative_returns_none(self):
        # 仕様違反値は None 扱い（body 検査に委ねる）
        assert _parse_content_length("-1") is None

    def test_non_numeric_returns_none(self):
        assert _parse_content_length("abc") is None

    def test_with_whitespace_stripped(self):
        assert _parse_content_length(" 512 ") == 512


class TestMaxBodyBytes:
    def test_default_is_one_megabyte(self):
        # mitmproxy の `--set body_size_limit=1m` と一致（1 MiB = 1024*1024）
        assert _MAX_BODY_BYTES == 1024 * 1024
