"""Tests for alert checking in addons/policy.py."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.policy import PolicyEngine

ALERTS_POLICY = """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[alerts]
suspicious_tools = ["Bash"]
suspicious_args = ["~/.ssh", "~/.aws", ".env", "id_rsa"]
tool_arg_size_alert = 5000
"""


def _write_policy(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestAlerts(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(ALERTS_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_tool_arg_size_alert(self):
        """閾値超過でアラート生成"""
        alerts = self.engine.check_tool_use("Read", "x" * 6000, 6000)
        types = [a.type for a in alerts]
        self.assertIn("tool_arg_size", types)

    def test_tool_arg_size_below_threshold(self):
        """閾値以下はアラートなし"""
        alerts = self.engine.check_tool_use("Read", "small input", 11)
        types = [a.type for a in alerts]
        self.assertNotIn("tool_arg_size", types)

    def test_suspicious_tool_detected(self):
        """suspicious_toolsにマッチするツール"""
        alerts = self.engine.check_tool_use("Bash", '{"command": "ls"}', 17)
        types = [a.type for a in alerts]
        self.assertIn("suspicious_tool", types)

    def test_non_suspicious_tool_no_alert(self):
        """suspicious_toolsにマッチしないツール"""
        alerts = self.engine.check_tool_use("Read", '{"path": "/tmp"}', 16)
        types = [a.type for a in alerts]
        self.assertNotIn("suspicious_tool", types)

    def test_suspicious_arg_detected(self):
        """suspicious_argsを含むinput"""
        alerts = self.engine.check_tool_use("Read", '{"path": "~/.ssh/id_rsa"}', 25)
        details = [a.detail for a in alerts]
        self.assertTrue(any("~/.ssh" in d for d in details))

    def test_multiple_alerts_single_tool_use(self):
        """複数条件に同時マッチ"""
        big_input = '{"command": "cat ~/.ssh/id_rsa"}' + "x" * 5000
        alerts = self.engine.check_tool_use("Bash", big_input, len(big_input))
        types = [a.type for a in alerts]
        self.assertIn("suspicious_tool", types)
        self.assertIn("suspicious_arg", types)
        self.assertIn("tool_arg_size", types)

    def test_suspicious_arg_no_false_positive_envrc(self):
        """.envが.envrcにマッチしない"""
        alerts = self.engine.check_tool_use("Read", '{"path": "/home/.envrc"}', 24)
        arg_alerts = [a for a in alerts if a.type == "suspicious_arg"]
        env_alerts = [a for a in arg_alerts if ".env" in a.detail]
        self.assertEqual(len(env_alerts), 0)

    def test_suspicious_arg_no_false_positive_environment(self):
        """.envが.environment_configにマッチしない"""
        alerts = self.engine.check_tool_use("Read", '{"path": ".environment_config"}', 31)
        arg_alerts = [a for a in alerts if a.type == "suspicious_arg"]
        env_alerts = [a for a in arg_alerts if ".env" in a.detail]
        self.assertEqual(len(env_alerts), 0)

    def test_suspicious_arg_no_false_positive_env_backup(self):
        """.envが.env_backupにマッチしない"""
        alerts = self.engine.check_tool_use("Read", '{"path": ".env_backup"}', 22)
        arg_alerts = [a for a in alerts if a.type == "suspicious_arg"]
        env_alerts = [a for a in arg_alerts if ".env" in a.detail]
        self.assertEqual(len(env_alerts), 0)

    def test_suspicious_arg_matches_dotenv_exact(self):
        """.envが/.envにマッチする"""
        alerts = self.engine.check_tool_use("Read", '{"path": "/.env"}', 17)
        arg_alerts = [a for a in alerts if a.type == "suspicious_arg" and ".env" in a.detail]
        self.assertGreater(len(arg_alerts), 0)

    def test_suspicious_arg_matches_dotenv_with_extension(self):
        """.envが/.env.localにマッチする"""
        alerts = self.engine.check_tool_use("Read", '{"path": "/.env.local"}', 23)
        arg_alerts = [a for a in alerts if a.type == "suspicious_arg" and ".env" in a.detail]
        self.assertGreater(len(arg_alerts), 0)

    def test_no_alerts_config_empty(self):
        """alerts設定なしで空リスト"""
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
        alerts = engine.check_tool_use("Bash", '{"command": "rm -rf /"}', 23)
        self.assertEqual(len(alerts), 0)


if __name__ == "__main__":
    unittest.main()
