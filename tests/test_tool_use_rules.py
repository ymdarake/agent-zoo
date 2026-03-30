"""Tests for tool_use blocking rules in addons/policy.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.policy import PolicyEngine

TOOL_USE_RULES_POLICY = """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[tool_use_rules]
block_tools = ["WebSearch"]
block_args = ["~/.ssh/id_rsa", "/etc/shadow", "DROP TABLE"]
"""


def _write_policy(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestToolUseBlock(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(TOOL_USE_RULES_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_blocked_tool(self):
        """block_toolsに含まれるツールはブロック"""
        should_block, reason = self.engine.should_block_tool_use("WebSearch", "{}")
        self.assertTrue(should_block)
        self.assertIn("WebSearch", reason)

    def test_allowed_tool(self):
        """block_toolsに含まれないツールは通過"""
        should_block, _ = self.engine.should_block_tool_use("Bash", '{"command": "ls"}')
        self.assertFalse(should_block)

    def test_blocked_arg_pattern(self):
        """block_argsにマッチする引数はブロック"""
        should_block, reason = self.engine.should_block_tool_use(
            "Read", '{"path": "~/.ssh/id_rsa"}'
        )
        self.assertTrue(should_block)
        self.assertIn("~/.ssh/id_rsa", reason)

    def test_blocked_arg_sql_injection(self):
        """SQLインジェクションパターンのブロック"""
        should_block, _ = self.engine.should_block_tool_use(
            "Bash", '{"command": "sqlite3 db.sqlite \\"DROP TABLE users\\""}'
        )
        self.assertTrue(should_block)

    def test_safe_arg_passes(self):
        """安全な引数は通過"""
        should_block, _ = self.engine.should_block_tool_use(
            "Read", '{"path": "/tmp/test.txt"}'
        )
        self.assertFalse(should_block)

    def test_no_rules_passes_everything(self):
        """tool_use_rulesセクションがなければ全て通過"""
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
        should_block, _ = engine.should_block_tool_use("WebSearch", "{}")
        self.assertFalse(should_block)

    def test_empty_rules_passes_everything(self):
        """空のルールは全て通過"""
        path = _write_policy(
            """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[tool_use_rules]
block_tools = []
block_args = []
"""
        )
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)
        should_block, _ = engine.should_block_tool_use("WebSearch", "{}")
        self.assertFalse(should_block)


if __name__ == "__main__":
    unittest.main()
