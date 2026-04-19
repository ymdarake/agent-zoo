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

    def test_csp_strict_no_unsafe_inline(self):
        """Sprint 007 PR I (review H-2): 'unsafe-inline' 完全排除を既存 test 側でも防衛。"""
        rv = self.client.get("/")
        csp = rv.headers["Content-Security-Policy"]
        self.assertNotIn("'unsafe-inline'", csp)

    def test_csp_strict_no_cdn_domains(self):
        """Sprint 007 PR I (M-1 / L-6 resolved): CDN ドメインが CSP に残っていない。"""
        rv = self.client.get("/")
        csp = rv.headers["Content-Security-Policy"]
        self.assertNotIn("cdn.jsdelivr.net", csp)
        self.assertNotIn("unpkg.com", csp)

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

    def test_invalid_port_rejected_by_werkzeug(self):
        """Host: localhost:evil.com (非数値 port) は Werkzeug が pre-middleware で弾く。

        TESTING=False では Flask が例外を伝搬する。production では Werkzeug の
        error handler が 400 Bad Request に変換する。いずれにせよ dashboard の
        policy 層には到達しない (fail-closed)。
        """
        with self.assertRaises(ValueError):
            self.client.get("/", headers={"Host": "localhost:evil.com"})

    def test_host_case_insensitive(self):
        """HTTP RFC 7230 準拠: Host は case-insensitive で許可判定される。"""
        rv = self.client.get("/", headers={"Host": "LOCALHOST"})
        self.assertEqual(rv.status_code, 200)
        rv = self.client.get("/", headers={"Host": "LocalHost:8080"})
        self.assertEqual(rv.status_code, 200)

    def test_host_trailing_dot_accepted(self):
        """DNS absolute 表記 (末尾 dot) は normalize して許可。"""
        rv = self.client.get("/", headers={"Host": "localhost."})
        self.assertEqual(rv.status_code, 200)


if __name__ == "__main__":
    unittest.main()
