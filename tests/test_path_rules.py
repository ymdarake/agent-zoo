"""Tests for path-based allow/deny rules in addons/policy.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.policy import PolicyEngine

PATH_RULES_POLICY = """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = ["*.evil.com"]

[paths.allow]
"raw.githubusercontent.com" = ["/anthropics/*"]
"registry.npmjs.org" = ["/@anthropic-ai/*"]

[paths.deny]
"api.anthropic.com" = ["/v1/files*"]
"""


def _write_policy(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestPathAllow(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(PATH_RULES_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_allowed_domain_no_path_rule(self):
        """domains.allowにあるドメイン + パスルールなし → 許可"""
        allowed, _ = self.engine.is_allowed("api.anthropic.com", "/v1/messages")
        self.assertTrue(allowed)

    def test_allowed_domain_with_path_deny(self):
        """domains.allowにあるドメイン + paths.denyにマッチ → ブロック"""
        allowed, reason = self.engine.is_allowed("api.anthropic.com", "/v1/files/upload")
        self.assertFalse(allowed)
        self.assertIn("path denied", reason)

    def test_blocked_domain_with_path_allow(self):
        """domains.allowにないドメイン + paths.allowにマッチ → 許可"""
        allowed, _ = self.engine.is_allowed(
            "raw.githubusercontent.com",
            "/anthropics/claude-plugins-official/refs/heads/security/security.json",
        )
        self.assertTrue(allowed)

    def test_blocked_domain_without_path_allow(self):
        """domains.allowにないドメイン + paths.allowにマッチしない → ブロック"""
        allowed, _ = self.engine.is_allowed(
            "raw.githubusercontent.com", "/some-other-user/repo/file.txt"
        )
        self.assertFalse(allowed)

    def test_denied_domain_ignores_path_allow(self):
        """domains.denyにあるドメインはpaths.allowがあってもブロック"""
        path = _write_policy(
            """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = []

[domains.deny]
list = ["*.evil.com"]

[paths.allow]
"sub.evil.com" = ["/*"]
"""
        )
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)
        allowed, _ = engine.is_allowed("sub.evil.com", "/anything")
        self.assertFalse(allowed)

    def test_npm_anthropic_package_allowed(self):
        """npmのAnthropic公式パッケージだけ許可"""
        allowed, _ = self.engine.is_allowed(
            "registry.npmjs.org", "/@anthropic-ai/claude-code"
        )
        self.assertTrue(allowed)

    def test_npm_other_package_blocked(self):
        """npmの他パッケージはブロック"""
        allowed, _ = self.engine.is_allowed(
            "registry.npmjs.org", "/@playwright/mcp"
        )
        self.assertFalse(allowed)

    def test_backward_compatible_without_path(self):
        """pathなしで呼んでも動作する（後方互換）"""
        allowed, _ = self.engine.is_allowed("api.anthropic.com")
        self.assertTrue(allowed)

    def test_no_path_rules_section(self):
        """[paths]セクションがなくても動作する"""
        path = _write_policy(
            """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []
"""
        )
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)
        allowed, _ = engine.is_allowed("api.anthropic.com", "/v1/messages")
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
