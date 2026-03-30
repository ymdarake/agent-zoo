"""Tests for addons/policy.py - Policy engine domain control logic."""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.policy import PolicyEngine

BASIC_POLICY = """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com", "statsig.anthropic.com"]

[domains.deny]
list = ["*.evil.com", "malware.org"]
"""


def _write_policy(content: str) -> str:
    """一時ファイルにポリシーを書き込み、パスを返す。"""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestPolicyLoading(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(BASIC_POLICY)

    def tearDown(self):
        os.unlink(self.path)

    def test_load_allow_list(self):
        engine = PolicyEngine(self.path)
        self.assertEqual(engine.allow_list, ["api.anthropic.com", "statsig.anthropic.com"])

    def test_load_deny_list(self):
        engine = PolicyEngine(self.path)
        self.assertEqual(engine.deny_list, ["*.evil.com", "malware.org"])

    def test_load_db_path(self):
        engine = PolicyEngine(self.path)
        self.assertEqual(engine.db_path, "/tmp/test-harness.db")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            PolicyEngine("/nonexistent/path/policy.toml")

    def test_invalid_toml_raises(self):
        path = _write_policy("this is not [valid toml")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(Exception):
            PolicyEngine(path)

    def test_empty_toml_uses_defaults(self):
        """セクション欠損のTOMLでは全てdefault denyになる（安全側）"""
        path = _write_policy('[general]\nlog_db = "/tmp/test.db"\n')
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)
        self.assertEqual(engine.allow_list, [])
        self.assertEqual(engine.deny_list, [])
        allowed, _ = engine.is_allowed("api.anthropic.com")
        self.assertFalse(allowed)


class TestDomainControl(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(BASIC_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_allowed_domain(self):
        allowed, reason = self.engine.is_allowed("api.anthropic.com")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_allowed_domain_second_entry(self):
        allowed, _ = self.engine.is_allowed("statsig.anthropic.com")
        self.assertTrue(allowed)

    def test_denied_domain_explicit(self):
        allowed, reason = self.engine.is_allowed("malware.org")
        self.assertFalse(allowed)
        self.assertIn("denied", reason)

    def test_denied_domain_wildcard(self):
        allowed, reason = self.engine.is_allowed("sub.evil.com")
        self.assertFalse(allowed)
        self.assertIn("denied", reason)

    def test_denied_domain_wildcard_nested(self):
        allowed, _ = self.engine.is_allowed("deep.sub.evil.com")
        self.assertFalse(allowed)

    def test_wildcard_also_matches_bare_domain(self):
        """*.evil.com は evil.com 自体にもマッチする（DNS的直感に合わせた拡張）"""
        allowed, reason = self.engine.is_allowed("evil.com")
        self.assertFalse(allowed)
        self.assertIn("denied", reason)

    def test_unlisted_domain_default_deny(self):
        allowed, reason = self.engine.is_allowed("github.com")
        self.assertFalse(allowed)
        self.assertIn("not in allow list", reason)

    def test_case_insensitive(self):
        """DNSはcase-insensitiveなので大文字ホスト名も正しく判定する"""
        allowed, _ = self.engine.is_allowed("API.ANTHROPIC.COM")
        self.assertTrue(allowed)

        allowed, _ = self.engine.is_allowed("Sub.Evil.Com")
        self.assertFalse(allowed)

    def test_deny_takes_precedence_over_allow(self):
        """deny list は allow list より優先される"""
        path = _write_policy(
            """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["*.example.com"]

[domains.deny]
list = ["bad.example.com"]
"""
        )
        self.addCleanup(os.unlink, path)

        engine = PolicyEngine(path)

        allowed, _ = engine.is_allowed("good.example.com")
        self.assertTrue(allowed)

        allowed, reason = engine.is_allowed("bad.example.com")
        self.assertFalse(allowed)
        self.assertIn("denied", reason)


class TestHotReload(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(
            """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []
"""
        )

    def tearDown(self):
        os.unlink(self.path)

    def test_reload_detects_changes(self):
        engine = PolicyEngine(self.path)

        allowed, _ = engine.is_allowed("github.com")
        self.assertFalse(allowed)

        time.sleep(0.1)
        with open(self.path, "w") as f:
            f.write(
                """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com", "github.com"]

[domains.deny]
list = []
"""
            )

        reloaded = engine.maybe_reload()
        self.assertTrue(reloaded)

        allowed, _ = engine.is_allowed("github.com")
        self.assertTrue(allowed)

    def test_no_reload_when_unchanged(self):
        engine = PolicyEngine(self.path)
        reloaded = engine.maybe_reload()
        self.assertFalse(reloaded)

    def test_reload_with_invalid_toml_keeps_old_policy(self):
        """不正なTOMLへの編集時に旧ポリシーを維持する"""
        engine = PolicyEngine(self.path)

        allowed, _ = engine.is_allowed("api.anthropic.com")
        self.assertTrue(allowed)

        time.sleep(0.1)
        with open(self.path, "w") as f:
            f.write("this is {{ not valid toml")

        reloaded = engine.maybe_reload()
        self.assertFalse(reloaded)

        # 旧ポリシーが維持されている
        allowed, _ = engine.is_allowed("api.anthropic.com")
        self.assertTrue(allowed)


class TestEdgeCases(unittest.TestCase):
    def test_empty_allow_list_blocks_everything(self):
        path = _write_policy(
            """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = []

[domains.deny]
list = []
"""
        )
        self.addCleanup(os.unlink, path)

        engine = PolicyEngine(path)
        allowed, _ = engine.is_allowed("api.anthropic.com")
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
