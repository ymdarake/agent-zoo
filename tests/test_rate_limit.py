"""Tests for rate limiting in addons/policy.py."""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.policy import PolicyEngine

RATE_LIMIT_POLICY = """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com", "statsig.anthropic.com"]

[domains.deny]
list = []

[rate_limits]
"api.anthropic.com" = { rpm = 5, burst = 2 }
"""

# burst制限なしでRPMだけテストする用
RPM_ONLY_POLICY = """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[rate_limits]
"api.anthropic.com" = { rpm = 3, burst = 100 }
"""


def _write_policy(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestBurstLimit(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(RATE_LIMIT_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_burst_within_limit(self):
        """burst以内のリクエストは許可される"""
        allowed1, _ = self.engine.check_rate_limit("api.anthropic.com")
        allowed2, _ = self.engine.check_rate_limit("api.anthropic.com")
        self.assertTrue(allowed1)
        self.assertTrue(allowed2)

    def test_burst_exceeds_limit(self):
        """burst=2なので、1秒以内に3件目でブロック"""
        self.engine.check_rate_limit("api.anthropic.com")
        self.engine.check_rate_limit("api.anthropic.com")
        allowed, reason = self.engine.check_rate_limit("api.anthropic.com")
        self.assertFalse(allowed)
        self.assertIn("burst", reason.lower())


class TestRpmLimit(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(RPM_ONLY_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_within_rpm_allowed(self):
        """RPM以内のリクエストは許可される"""
        for _ in range(3):
            allowed, reason = self.engine.check_rate_limit("api.anthropic.com")
            self.assertTrue(allowed, f"Should be allowed but got: {reason}")

    def test_exceeds_rpm_blocked(self):
        """RPMを超えるリクエストはブロックされる"""
        for _ in range(3):
            self.engine.check_rate_limit("api.anthropic.com")

        allowed, reason = self.engine.check_rate_limit("api.anthropic.com")
        self.assertFalse(allowed)
        self.assertIn("rate limit", reason.lower())

    def test_window_slides_after_time(self):
        """時間経過後にウィンドウがスライドしてカウントがリセットされる"""
        for _ in range(3):
            self.engine.check_rate_limit("api.anthropic.com")

        allowed, _ = self.engine.check_rate_limit("api.anthropic.com")
        self.assertFalse(allowed)

        # 内部タイムスタンプを60秒前に巻き戻す（sleepを避ける）
        old_time = time.time() - 61
        for window in [self.engine._rate_windows, self.engine._burst_windows]:
            w = window.get("api.anthropic.com")
            if w:
                for i in range(len(w)):
                    w[i] = old_time

        allowed, _ = self.engine.check_rate_limit("api.anthropic.com")
        self.assertTrue(allowed)


class TestRateLimitGeneral(unittest.TestCase):
    def setUp(self):
        self.path = _write_policy(RATE_LIMIT_POLICY)
        self.engine = PolicyEngine(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_no_config_unlimited(self):
        """rate_limitsに設定がないドメインは制限なし"""
        for _ in range(100):
            allowed, _ = self.engine.check_rate_limit("statsig.anthropic.com")
            self.assertTrue(allowed)

    def test_rate_limits_loaded_from_policy(self):
        """policy.tomlからrate_limitsが正しくロードされる"""
        self.assertIn("api.anthropic.com", self.engine.rate_limits)
        self.assertEqual(self.engine.rate_limits["api.anthropic.com"]["rpm"], 5)
        self.assertEqual(self.engine.rate_limits["api.anthropic.com"]["burst"], 2)

    def test_reload_updates_limits(self):
        """ホットリロードでレート制限値が更新される"""
        time.sleep(0.1)
        with open(self.path, "w") as f:
            f.write(
                """
[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = []

[rate_limits]
"api.anthropic.com" = { rpm = 100, burst = 50 }
"""
            )
        self.engine.maybe_reload()
        self.assertEqual(self.engine.rate_limits["api.anthropic.com"]["rpm"], 100)


class TestRateLimitNoConfig(unittest.TestCase):
    def test_no_rate_limits_section(self):
        """[rate_limits]セクションがなくてもエラーにならない"""
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
        self.assertEqual(engine.rate_limits, {})
        allowed, _ = engine.check_rate_limit("api.anthropic.com")
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
