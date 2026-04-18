"""セキュリティヘッダ + Strict Host middleware テスト (H-4 / G-2 / G3-B2).

Sprint 005 PR B:
- Content-Security-Policy + X-Content-Type-Options + X-Frame-Options + Referrer-Policy
  を全レスポンスに付与
- Host ヘッダ whitelist (DNS rebinding 対策)
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import app  # noqa: E402


class TestSecurityHeaders(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        os.environ["DB_PATH"] = self.db_path
        db = sqlite3.connect(self.db_path)
        db.executescript(
            """
            CREATE TABLE requests (id INTEGER PRIMARY KEY, ts TEXT, host TEXT, method TEXT, url TEXT, status TEXT, body_size INTEGER);
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

    def test_csp_header_present_on_index(self):
        rv = self.client.get("/")
        self.assertEqual(rv.status_code, 200)
        self.assertIn("Content-Security-Policy", rv.headers)
        csp = rv.headers["Content-Security-Policy"]
        # default-src 'self' が含まれる
        self.assertIn("default-src 'self'", csp)
        # frame-ancestors 'none' で clickjacking 防御
        self.assertIn("frame-ancestors 'none'", csp)

    def test_csp_header_present_on_api(self):
        rv = self.client.get("/api/requests")
        self.assertIn("Content-Security-Policy", rv.headers)

    def test_x_content_type_options_nosniff(self):
        rv = self.client.get("/")
        self.assertEqual(rv.headers.get("X-Content-Type-Options"), "nosniff")

    def test_x_frame_options_deny(self):
        rv = self.client.get("/")
        self.assertEqual(rv.headers.get("X-Frame-Options"), "DENY")

    def test_referrer_policy_no_referrer(self):
        rv = self.client.get("/")
        self.assertEqual(rv.headers.get("Referrer-Policy"), "no-referrer")


class TestStrictHostMiddleware(unittest.TestCase):
    """Host ヘッダ whitelist で DNS rebinding を防ぐこと。

    TESTING=True では middleware をスキップする設計なので、本テストでは明示的に
    TESTING=False + WTF_CSRF_ENABLED=False でチェック。
    """

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        app.config["TESTING"] = False  # Strict Host を有効化するため
        app.config["WTF_CSRF_ENABLED"] = False
        os.environ["DB_PATH"] = self.db_path
        db = sqlite3.connect(self.db_path)
        db.executescript(
            """
            CREATE TABLE requests (id INTEGER PRIMARY KEY, ts TEXT, host TEXT, method TEXT, url TEXT, status TEXT, body_size INTEGER);
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
        # 他テストに影響残さないよう TESTING を True に戻す
        app.config["TESTING"] = True

    def test_localhost_host_allowed(self):
        rv = self.client.get("/", headers={"Host": "localhost"})
        self.assertEqual(rv.status_code, 200)

    def test_127_0_0_1_host_allowed(self):
        rv = self.client.get("/", headers={"Host": "127.0.0.1"})
        self.assertEqual(rv.status_code, 200)

    def test_attacker_domain_rejected(self):
        rv = self.client.get("/", headers={"Host": "attacker.example.com"})
        self.assertEqual(rv.status_code, 400)

    def test_rebinding_subdomain_rejected(self):
        rv = self.client.get("/", headers={"Host": "evil.127.0.0.1.nip.io"})
        self.assertEqual(rv.status_code, 400)

    def test_host_with_port_still_checked(self):
        rv = self.client.get("/", headers={"Host": "localhost:8080"})
        self.assertEqual(rv.status_code, 200)
        rv = self.client.get("/", headers={"Host": "evil.com:8080"})
        self.assertEqual(rv.status_code, 400)


if __name__ == "__main__":
    unittest.main()
