"""Tests for `addons.policy_enforcer.scrub_url` (Sprint 006 PR D, M-2).

URL 保存前に userinfo / query / fragment を redact し、DB に機密情報が
永続化されるのを防ぐ。mitmproxy 本体を import せずに helper 単体で動く。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle"))

from addons._url_scrub import scrub_url  # noqa: E402


class TestScrubUrl:
    def test_simple_url_no_query(self):
        assert scrub_url("https://example.com/path") == "https://example.com/path"

    def test_url_with_query_redacted(self):
        # query の値が redact され、存在は placeholder で保持される
        assert (
            scrub_url("https://example.com/path?api_key=secret&foo=bar")
            == "https://example.com/path?[redacted]"
        )

    def test_url_with_fragment_removed(self):
        # fragment は完全削除（OAuth implicit flow 等の token 漏洩対策）
        assert (
            scrub_url("https://example.com/path#access_token=xxx")
            == "https://example.com/path"
        )

    def test_url_with_userinfo_redacted(self):
        assert (
            scrub_url("https://user:pass@example.com/path")
            == "https://[redacted]@example.com/path"
        )

    def test_url_with_all_three(self):
        # userinfo + query + fragment 全部乗った複合 URL
        assert (
            scrub_url("https://user:pass@example.com:443/path?q=1&api_key=2#frag")
            == "https://[redacted]@example.com:443/path?[redacted]"
        )

    def test_ipv6_literal_preserved(self):
        # [::1] で netloc に収まるケース
        assert (
            scrub_url("https://[::1]:8080/path?a=b")
            == "https://[::1]:8080/path?[redacted]"
        )

    def test_empty_url_returns_invalid(self):
        # 空 URL はパース結果が意味を持たないので固定文字列
        assert scrub_url("") == "[invalid-url]"

    def test_non_http_scheme_preserved(self):
        # ws / wss 等の scheme も維持（mitmproxy では WebSocket も通る）
        assert (
            scrub_url("wss://example.com/socket?token=abc")
            == "wss://example.com/socket?[redacted]"
        )

    def test_query_only_placeholder_keeps_evidence(self):
        # 「query があった事実」は placeholder で保持（dashboard 観察性のため）
        result = scrub_url("https://example.com/path?k=v")
        assert "?[redacted]" in result
        assert "k=v" not in result

    # --- self-review H-2: log injection / smuggling 防御 ---

    def test_url_with_newline_returns_invalid(self):
        assert scrub_url("https://example.com\nEvil") == "[invalid-url]"

    def test_url_with_carriage_return_returns_invalid(self):
        assert scrub_url("https://example.com\r\nX-Inject: 1") == "[invalid-url]"

    def test_url_with_null_byte_returns_invalid(self):
        assert scrub_url("https://example.com\x00/path") == "[invalid-url]"

    def test_url_with_tab_returns_invalid(self):
        assert scrub_url("https://example.com\t/path") == "[invalid-url]"

    # --- self-review M-2: host normalization ---

    def test_uppercase_host_normalized_to_lowercase(self):
        assert scrub_url("https://EXAMPLE.COM/PATH") == "https://example.com/PATH"

    def test_mixed_case_host_normalized(self):
        assert scrub_url("https://Example.Com/path") == "https://example.com/path"

    def test_userinfo_host_lowercased_too(self):
        assert (
            scrub_url("https://user:pass@EXAMPLE.com/path")
            == "https://[redacted]@example.com/path"
        )

    def test_path_case_preserved(self):
        # path は case-sensitive (RFC 3986)、host のみ lowercase
        assert scrub_url("https://example.com/Path/Case") == "https://example.com/Path/Case"
