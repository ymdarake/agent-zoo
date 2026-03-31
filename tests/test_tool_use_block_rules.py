"""Tests for tool_use_rules combination conditions in addons/policy.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.policy import PolicyEngine

BLOCK_RULES_POLICY = """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[tool_use_rules]
block_tools = []
block_args = []

[[tool_use_rules.rules]]
name = "Bash accessing SSH"
tools = ["Bash"]
args = ["~/.ssh", "id_rsa"]

[[tool_use_rules.rules]]
name = "Large write"
tools = ["Write", "Edit"]
min_size = 5000

[[tool_use_rules.rules]]
name = "Any tool reading shadow"
args = ["/etc/shadow"]
"""


def _write_policy(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestToolUseBlockRules(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(BLOCK_RULES_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_bash_with_ssh_blocked(self):
        """Bash + ~/.ssh → ブロック"""
        blocked, reason = self.engine.should_block_tool_use(
            "Bash", '{"command": "cat ~/.ssh/id_rsa"}'
        )
        self.assertTrue(blocked)
        self.assertIn("Bash accessing SSH", reason)

    def test_bash_without_ssh_not_blocked(self):
        """Bash + 安全な引数 → ブロックしない"""
        blocked, _ = self.engine.should_block_tool_use(
            "Bash", '{"command": "ls -la"}'
        )
        self.assertFalse(blocked)

    def test_read_with_ssh_not_blocked_by_bash_rule(self):
        """Read + ~/.ssh → Bashルールではブロックしない"""
        blocked, reason = self.engine.should_block_tool_use(
            "Read", '{"path": "~/.ssh/id_rsa"}'
        )
        # "Any tool reading shadow"ルールにはマッチしない
        # Bashルールにもマッチしない（ツール不一致）
        self.assertFalse(blocked)

    def test_large_write_blocked(self):
        """Write + 5000超 → ブロック"""
        blocked, reason = self.engine.should_block_tool_use(
            "Write", '{"content": "' + "x" * 6000 + '"}'
        )
        self.assertTrue(blocked)
        self.assertIn("Large write", reason)

    def test_small_write_not_blocked(self):
        """Write + 小サイズ → ブロックしない"""
        blocked, _ = self.engine.should_block_tool_use(
            "Write", '{"content": "small"}'
        )
        self.assertFalse(blocked)

    def test_any_tool_shadow_blocked(self):
        """ツール指定なし + /etc/shadow → どのツールでもブロック"""
        blocked, reason = self.engine.should_block_tool_use(
            "Read", '{"path": "/etc/shadow"}'
        )
        self.assertTrue(blocked)
        self.assertIn("Any tool reading shadow", reason)

    def test_no_rules_passes(self):
        """tool_use_rules.rulesがなければ独立条件のみで判定"""
        path = _write_policy("""
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[tool_use_rules]
block_tools = []
block_args = []
""")
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)
        blocked, _ = engine.should_block_tool_use("Bash", '{"command": "cat ~/.ssh/id_rsa"}')
        self.assertFalse(blocked)

    def test_independent_and_rules_coexist(self):
        """独立条件と組み合わせ条件が共存"""
        path = _write_policy("""
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[tool_use_rules]
block_tools = ["WebSearch"]
block_args = []

[[tool_use_rules.rules]]
name = "Bash SSH"
tools = ["Bash"]
args = ["~/.ssh"]
""")
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)
        # 独立条件でブロック
        blocked, _ = engine.should_block_tool_use("WebSearch", "{}")
        self.assertTrue(blocked)
        # 組み合わせ条件でブロック
        blocked, _ = engine.should_block_tool_use("Bash", '{"path": "~/.ssh/key"}')
        self.assertTrue(blocked)
        # どちらにもマッチしない
        blocked, _ = engine.should_block_tool_use("Read", '{"path": "/tmp/test"}')
        self.assertFalse(blocked)

    def test_empty_rules_not_block(self):
        """条件なしルールはスキップ"""
        path = _write_policy("""
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[tool_use_rules]
block_tools = []
block_args = []

[[tool_use_rules.rules]]
name = "empty"
""")
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)
        blocked, _ = engine.should_block_tool_use("Bash", '{"command": "anything"}')
        self.assertFalse(blocked)


if __name__ == "__main__":
    unittest.main()
