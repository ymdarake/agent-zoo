"""Tests for combined alert rules ([[alerts.rules]]) in addons/policy.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.policy import PolicyEngine

COMBINED_RULES_POLICY = """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[alerts]
suspicious_tools = []
suspicious_args = []
tool_arg_size_alert = 0

[[alerts.rules]]
name = "Bash accessing secrets"
tools = ["Bash"]
args = ["~/.ssh", "~/.aws"]

[[alerts.rules]]
name = "Large write"
tools = ["Write", "Edit"]
min_size = 5000

[[alerts.rules]]
name = "Any tool reading shadow"
args = ["/etc/shadow"]
"""


def _write_policy(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestCombinedAlertRules(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(COMBINED_RULES_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_bash_with_ssh_triggers(self):
        """Bash + ~/.ssh → ルール発火"""
        alerts = self.engine.check_tool_use("Bash", '{"command": "cat ~/.ssh/id_rsa"}', 30)
        rule_alerts = [a for a in alerts if a.type == "rule_match"]
        self.assertEqual(len(rule_alerts), 1)
        self.assertIn("Bash accessing secrets", rule_alerts[0].detail)

    def test_bash_without_secret_no_trigger(self):
        """Bash + 安全な引数 → ルール発火しない"""
        alerts = self.engine.check_tool_use("Bash", '{"command": "ls -la"}', 15)
        rule_alerts = [a for a in alerts if a.type == "rule_match"]
        self.assertEqual(len(rule_alerts), 0)

    def test_read_with_ssh_no_trigger(self):
        """Read + ~/.ssh → Bashルールは発火しない（ツール不一致）"""
        alerts = self.engine.check_tool_use("Read", '{"path": "~/.ssh/id_rsa"}', 25)
        rule_alerts = [a for a in alerts if a.type == "rule_match" and "Bash accessing" in a.detail]
        self.assertEqual(len(rule_alerts), 0)

    def test_large_write_triggers(self):
        """Write + 5000バイト超 → ルール発火"""
        alerts = self.engine.check_tool_use("Write", '{"content": "x"}', 6000)
        rule_alerts = [a for a in alerts if a.type == "rule_match"]
        self.assertEqual(len(rule_alerts), 1)
        self.assertIn("Large write", rule_alerts[0].detail)

    def test_small_write_no_trigger(self):
        """Write + 小さいサイズ → ルール発火しない"""
        alerts = self.engine.check_tool_use("Write", '{"content": "x"}', 100)
        rule_alerts = [a for a in alerts if a.type == "rule_match" and "Large write" in a.detail]
        self.assertEqual(len(rule_alerts), 0)

    def test_edit_also_matches_write_rule(self):
        """Edit も Write ルールの tools にマッチ"""
        alerts = self.engine.check_tool_use("Edit", '{"content": "x"}', 6000)
        rule_alerts = [a for a in alerts if a.type == "rule_match"]
        self.assertGreater(len(rule_alerts), 0)
        self.assertIn("Large write", rule_alerts[0].detail)

    def test_any_tool_shadow_triggers(self):
        """ツール指定なし + /etc/shadow → どのツールでも発火"""
        alerts = self.engine.check_tool_use("Read", '{"path": "/etc/shadow"}', 12)
        rule_alerts = [a for a in alerts if a.type == "rule_match"]
        self.assertEqual(len(rule_alerts), 1)
        self.assertIn("Any tool reading shadow", rule_alerts[0].detail)

    def test_multiple_rules_can_fire(self):
        """複数ルールが同時に発火"""
        # Bash + ~/.ssh → ルール1発火、/etc/shadow → ルール3発火
        alerts = self.engine.check_tool_use(
            "Bash", '{"command": "cat ~/.ssh/id_rsa /etc/shadow"}', 40
        )
        rule_alerts = [a for a in alerts if a.type == "rule_match"]
        names = [a.detail for a in rule_alerts]
        self.assertTrue(any("Bash accessing secrets" in n for n in names))
        self.assertTrue(any("Any tool reading shadow" in n for n in names))

    def test_no_rules_section_no_error(self):
        """[[alerts.rules]]がなくてもエラーにならない"""
        path = _write_policy(
            """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[alerts]
suspicious_tools = []
suspicious_args = []
tool_arg_size_alert = 0
"""
        )
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)
        alerts = engine.check_tool_use("Bash", '{"command": "cat ~/.ssh/id_rsa"}', 30)
        rule_alerts = [a for a in alerts if a.type == "rule_match"]
        self.assertEqual(len(rule_alerts), 0)

    def test_args_use_word_boundary_match(self):
        """argsはワード境界マッチ（.envが.envrcにマッチしない）"""
        path = _write_policy(
            """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[alerts]
suspicious_tools = []
suspicious_args = []
tool_arg_size_alert = 0

[[alerts.rules]]
name = "env access"
args = [".env"]
"""
        )
        self.addCleanup(os.unlink, path)
        engine = PolicyEngine(path)

        # .env → マッチ
        alerts = engine.check_tool_use("Read", '{"path": "/.env"}', 10)
        self.assertTrue(any(a.type == "rule_match" for a in alerts))

        # .envrc → マッチしない
        alerts = engine.check_tool_use("Read", '{"path": "/.envrc"}', 10)
        self.assertFalse(any(a.type == "rule_match" for a in alerts))


if __name__ == "__main__":
    unittest.main()
