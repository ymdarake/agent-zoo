"""CSRF 保護テスト（包括レビュー H-1 対応）.

Sprint 005 PR B で dashboard に Flask-WTF CSRFProtect を導入。
既存 test_dashboard.py は WTF_CSRF_ENABLED=False で CSRF を bypass しているが、
本ファイルでは CSRF を **有効化** して保護が実際に効くことを検証する。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import app  # noqa: E402


class TestCSRFProtection(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        app.config["TESTING"] = True
        # CSRF を **有効化** して保護動作を検証する (既存 test はこれを False にしている)
        app.config["WTF_CSRF_ENABLED"] = True
        os.environ["DB_PATH"] = self.db_path
        self.tmp_inbox = tempfile.mkdtemp(prefix="test-inbox-")
        self.tmp_policy = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        self.tmp_policy.write('[domains.allow]\nlist = []\n[paths.allow]\n')
        self.tmp_policy.close()
        os.environ["POLICY_PATH"] = self.tmp_policy.name
        os.environ["INBOX_DIR"] = self.tmp_inbox

        # テスト用 DB 初期化
        db = sqlite3.connect(self.db_path)
        db.executescript(
            """
            CREATE TABLE requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                host TEXT, method TEXT, url TEXT, status TEXT, body_size INTEGER
            );
            CREATE TABLE blocks (id INTEGER PRIMARY KEY, ts TEXT, host TEXT, reason TEXT);
            CREATE TABLE tool_uses (id INTEGER PRIMARY KEY, ts TEXT, tool_name TEXT, input TEXT, input_size INTEGER);
            CREATE TABLE alerts (id INTEGER PRIMARY KEY, ts TEXT, type TEXT, detail TEXT);
            """
        )
        db.commit()
        db.close()

        self.client = app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)
        os.unlink(self.tmp_policy.name)
        import shutil
        shutil.rmtree(self.tmp_inbox, ignore_errors=True)
        # 他テストに影響を残さないよう CSRF を無効化に戻す
        app.config["WTF_CSRF_ENABLED"] = False

    def _get_csrf_token(self) -> str:
        """`GET /` から meta tag の csrf_token を取り出す。"""
        rv = self.client.get("/")
        self.assertEqual(rv.status_code, 200)
        html = rv.get_data(as_text=True)
        # <meta name="csrf-token" content="..."> から値を抽出
        import re
        m = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html)
        self.assertIsNotNone(m, "csrf-token meta tag not found in /")
        return m.group(1)

    # === 無 token POST は全て 400 ===

    def test_whitelist_allow_without_token_returns_400(self):
        rv = self.client.post(
            "/api/whitelist/allow",
            json={"domain": "attacker.example.com"},
        )
        self.assertEqual(rv.status_code, 400)

    def test_whitelist_allow_path_without_token_returns_400(self):
        rv = self.client.post(
            "/api/whitelist/allow-path",
            json={"domain": "attacker.example.com", "path_pattern": "/*"},
        )
        self.assertEqual(rv.status_code, 400)

    def test_inbox_accept_without_token_returns_400(self):
        rv = self.client.post(
            "/api/inbox/accept",
            json={"record_id": "any"},
        )
        self.assertEqual(rv.status_code, 400)

    def test_inbox_reject_without_token_returns_400(self):
        rv = self.client.post(
            "/api/inbox/reject",
            json={"record_id": "any"},
        )
        self.assertEqual(rv.status_code, 400)

    def test_inbox_bulk_accept_without_token_returns_400(self):
        rv = self.client.post(
            "/api/inbox/bulk-accept",
            json={"record_ids": ["any"]},
        )
        self.assertEqual(rv.status_code, 400)

    def test_inbox_bulk_reject_without_token_returns_400(self):
        rv = self.client.post(
            "/api/inbox/bulk-reject",
            json={"record_ids": ["any"]},
        )
        self.assertEqual(rv.status_code, 400)

    # === token 付き POST は通る ===

    def test_whitelist_allow_with_token_succeeds(self):
        token = self._get_csrf_token()
        rv = self.client.post(
            "/api/whitelist/allow",
            json={"domain": "ok.example.com"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(rv.status_code, 200)

    def test_inbox_reject_with_token_passes_to_handler(self):
        """token 付きなら CSRF 層は通過し、handler が 404 (record 不在) を返す。"""
        token = self._get_csrf_token()
        rv = self.client.post(
            "/api/inbox/reject",
            json={"record_id": "nonexistent-record"},
            headers={"X-CSRFToken": token},
        )
        # CSRF は通過、record が無いので 404 を期待（400 では無い）
        self.assertIn(rv.status_code, (200, 404))

    # === GET は CSRF 対象外 ===

    def test_get_requests_not_csrf_protected(self):
        rv = self.client.get("/api/requests")
        self.assertEqual(rv.status_code, 200)

    def test_partial_inbox_get_not_csrf_protected(self):
        rv = self.client.get("/partials/inbox")
        self.assertEqual(rv.status_code, 200)


if __name__ == "__main__":
    unittest.main()
