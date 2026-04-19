"""Tests for dashboard `_validate_domain` strict regex (M-5).

RFC 1035 準拠 label を要求し、UI 経由で `localhost` / `*.com` / `a..com` /
`a-.com` などが allowlist に投入されるのを防ぐ。

既存 `bundle/policy.toml` の 13 domains と `paths.allow` keys 4 件はすべて
新 regex を通過することを回帰テストで保証する。
"""

from __future__ import annotations

import os
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import _validate_domain  # noqa: E402


class TestValidateDomainAllows(unittest.TestCase):
    """許可ケース: RFC 1035 ラベルが 2 段以上 + optional wildcard prefix。"""

    def test_two_label_domain(self):
        self.assertIsNone(_validate_domain("example.com"))

    def test_wildcard_two_label(self):
        self.assertIsNone(_validate_domain("*.example.com"))

    def test_multi_label_domain(self):
        self.assertIsNone(_validate_domain("foo.bar.baz.com"))

    def test_label_with_internal_hyphen(self):
        self.assertIsNone(_validate_domain("a-b.example.com"))

    def test_ipv4_literal(self):
        self.assertIsNone(_validate_domain("1.2.3.4"))

    def test_punycode_idn(self):
        self.assertIsNone(_validate_domain("xn--foo.example.com"))


class TestValidateDomainRejects(unittest.TestCase):
    """拒否ケース: single label / TLD-only wildcard / 連続 dot / trailing hyphen 等。"""

    def test_single_label_rejected(self):
        """localhost / mailserver 等は reject（UI からは追加不可、base policy 編集で対応）"""
        self.assertIsNotNone(_validate_domain("localhost"))

    def test_tld_only_wildcard_rejected(self):
        """*.com は TLD 全乗っ取りになるので reject"""
        self.assertIsNotNone(_validate_domain("*.com"))

    def test_consecutive_dot_rejected(self):
        self.assertIsNotNone(_validate_domain("a..com"))

    def test_trailing_hyphen_rejected(self):
        self.assertIsNotNone(_validate_domain("a-.com"))

    def test_leading_hyphen_rejected(self):
        self.assertIsNotNone(_validate_domain("-a.com"))

    def test_multi_wildcard_rejected(self):
        self.assertIsNotNone(_validate_domain("*.*.example.com"))

    def test_trailing_dot_rejected(self):
        """DNS absolute (末尾 dot) は UI 投入時は reject。Host ヘッダ側では別途 rstrip(.) で許容。"""
        self.assertIsNotNone(_validate_domain("example.com."))

    def test_empty_rejected(self):
        self.assertIsNotNone(_validate_domain(""))

    def test_wildcard_only_rejected(self):
        self.assertIsNotNone(_validate_domain("*"))

    def test_over_253_chars_rejected(self):
        long_domain = ("a" * 60 + ".") * 5 + "com"
        self.assertIsNotNone(_validate_domain(long_domain))


class TestValidateDomainExistingPolicy(unittest.TestCase):
    """既存 `bundle/policy.toml` の全 domain entries が新 regex を通過することを保証。

    strict 化で既存設定が壊れないことの回帰テスト。
    """

    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).parent.parent
        with open(repo_root / "bundle" / "policy.toml", "rb") as f:
            cls.policy = tomllib.load(f)

    def test_domains_allow_list_all_valid(self):
        entries = self.policy.get("domains", {}).get("allow", {}).get("list", [])
        self.assertGreater(len(entries), 0, "sanity: base policy has domain entries")
        for entry in entries:
            with self.subTest(domain=entry):
                self.assertIsNone(
                    _validate_domain(entry),
                    f"既存 allow list entry {entry!r} が strict regex で弾かれた",
                )

    def test_domains_deny_list_all_valid(self):
        entries = self.policy.get("domains", {}).get("deny", {}).get("list", [])
        for entry in entries:
            with self.subTest(domain=entry):
                self.assertIsNone(
                    _validate_domain(entry),
                    f"既存 deny list entry {entry!r} が strict regex で弾かれた",
                )

    def test_paths_allow_keys_all_valid(self):
        paths_allow = self.policy.get("paths", {}).get("allow", {})
        self.assertGreater(len(paths_allow), 0, "sanity: base policy has paths.allow entries")
        for domain in paths_allow:
            with self.subTest(domain=domain):
                self.assertIsNone(
                    _validate_domain(domain),
                    f"既存 paths.allow key {domain!r} が strict regex で弾かれた",
                )


if __name__ == "__main__":
    unittest.main()
