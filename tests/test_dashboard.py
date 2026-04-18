"""Tests for dashboard/app.py - Flask API endpoints."""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import app


class TestDashboardAPI(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        app.config["TESTING"] = True
        os.environ["DB_PATH"] = self.db_path

        # テスト用DBを初期化
        db = sqlite3.connect(self.db_path)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(
            """
            CREATE TABLE requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                host TEXT, method TEXT, url TEXT, status TEXT, body_size INTEGER
            );
            CREATE TABLE blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                host TEXT, reason TEXT
            );
            CREATE TABLE tool_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                tool_name TEXT, input TEXT, input_size INTEGER
            );
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                type TEXT, detail TEXT
            );
            """
        )
        # テストデータ投入
        db.execute(
            "INSERT INTO requests (host, method, url, status, body_size) VALUES (?, ?, ?, ?, ?)",
            ("api.anthropic.com", "POST", "https://api.anthropic.com/v1/messages", "ALLOWED", 1024),
        )
        db.execute(
            "INSERT INTO requests (host, method, url, status, body_size) VALUES (?, ?, ?, ?, ?)",
            ("evil.com", "GET", "https://evil.com/", "BLOCKED", 0),
        )
        db.execute(
            "INSERT INTO blocks (host, reason) VALUES (?, ?)",
            ("evil.com", "denied by pattern: *.evil.com"),
        )
        db.execute(
            "INSERT INTO tool_uses (tool_name, input, input_size) VALUES (?, ?, ?)",
            ("Bash", '{"command": "ls"}', 17),
        )
        db.execute(
            "INSERT INTO alerts (type, detail) VALUES (?, ?)",
            ("suspicious_tool", "suspicious tool: Bash"),
        )
        db.commit()
        db.close()

        self.client = app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_index_returns_html(self):
        rv = self.client.get("/")
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b"Agent Harness", rv.data)

    def test_api_stats(self):
        rv = self.client.get("/api/stats")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertEqual(data["total_requests"], 2)
        self.assertEqual(data["allowed"], 1)
        self.assertEqual(data["blocked"], 1)
        self.assertEqual(data["tool_uses"], 1)
        self.assertEqual(data["alerts"], 1)

    def test_api_requests(self):
        rv = self.client.get("/api/requests")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertEqual(len(data), 2)

    def test_api_requests_filter_status(self):
        rv = self.client.get("/api/requests?status=BLOCKED")
        data = rv.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["host"], "evil.com")

    def test_api_blocks(self):
        rv = self.client.get("/api/blocks")
        data = rv.get_json()
        self.assertEqual(len(data), 1)
        self.assertIn("evil.com", data[0]["host"])

    def test_api_tool_uses(self):
        rv = self.client.get("/api/tool-uses")
        data = rv.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["tool_name"], "Bash")

    def test_api_alerts(self):
        rv = self.client.get("/api/alerts")
        data = rv.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "suspicious_tool")

    def test_api_domains(self):
        rv = self.client.get("/api/domains")
        data = rv.get_json()
        self.assertGreaterEqual(len(data), 2)

    def test_partial_requests(self):
        rv = self.client.get("/partials/requests")
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b"api.anthropic.com", rv.data)

    def test_partial_stats(self):
        rv = self.client.get("/partials/stats")
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b"Total Requests", rv.data)

    def test_api_requests_limit(self):
        rv = self.client.get("/api/requests?limit=1")
        data = rv.get_json()
        self.assertEqual(len(data), 1)


class TestDashboardInbox(unittest.TestCase):
    """ADR 0001 A-6: dashboard inbox 連携。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox_dir = os.path.join(self.tmp.name, "inbox")
        os.makedirs(self.inbox_dir, exist_ok=True)
        self.policy_path = os.path.join(self.tmp.name, "policy.toml")
        with open(self.policy_path, "w") as f:
            f.write("[domains.allow]\nlist = []\n[paths.allow]\n")

        os.environ["INBOX_DIR"] = self.inbox_dir
        os.environ["POLICY_PATH"] = self.policy_path

        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "bundle", "addons")
        )
        from policy_inbox import add_request  # noqa: E402

        self._add = add_request
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_partial_inbox_empty(self):
        rv = self.client.get("/partials/inbox")
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b"Inbox", rv.data)

    def test_partial_inbox_lists_pending(self):
        self._add(self.inbox_dir, {
            "type": "domain", "value": "needed.com",
            "reason": "test", "agent": "claude",
        })
        rv = self.client.get("/partials/inbox")
        self.assertIn(b"needed.com", rv.data)

    def test_accept_reflects_to_runtime(self):
        rid = self._add(self.inbox_dir, {
            "type": "domain", "value": "ok.com",
            "reason": "test", "agent": "claude",
        })
        rv = self.client.post(
            "/api/inbox/accept", json={"record_id": rid}
        )
        self.assertEqual(rv.status_code, 200)

        import tomllib
        rt_path = self.policy_path.replace(".toml", ".runtime.toml")
        self.assertTrue(os.path.exists(rt_path))
        with open(rt_path, "rb") as f:
            rt = tomllib.load(f)
        self.assertIn(
            "ok.com",
            rt.get("domains", {}).get("allow", {}).get("list", []),
        )

    def test_accept_path_request(self):
        rid = self._add(self.inbox_dir, {
            "type": "path", "value": "/foo/*",
            "domain": "registry.npmjs.org",
            "reason": "test", "agent": "claude",
        })
        rv = self.client.post(
            "/api/inbox/accept", json={"record_id": rid}
        )
        self.assertEqual(rv.status_code, 200)

        import tomllib
        rt_path = self.policy_path.replace(".toml", ".runtime.toml")
        with open(rt_path, "rb") as f:
            rt = tomllib.load(f)
        patterns = rt.get("paths", {}).get("allow", {}).get(
            "registry.npmjs.org", []
        )
        self.assertIn("/foo/*", patterns)

    def test_accept_unknown_record_returns_404(self):
        rv = self.client.post(
            "/api/inbox/accept", json={"record_id": "ghost"}
        )
        self.assertEqual(rv.status_code, 404)

    def test_accept_missing_record_id_returns_400(self):
        rv = self.client.post("/api/inbox/accept", json={})
        self.assertEqual(rv.status_code, 400)

    def test_reject_marks_status(self):
        rid = self._add(self.inbox_dir, {
            "type": "domain", "value": "no.com",
            "reason": "test", "agent": "claude",
        })
        rv = self.client.post(
            "/api/inbox/reject", json={"record_id": rid, "reason": "noo"}
        )
        self.assertEqual(rv.status_code, 200)
        rv2 = self.client.get("/partials/inbox")
        self.assertNotIn(b"no.com", rv2.data)

    def test_bulk_accept(self):
        ids = [
            self._add(self.inbox_dir, {
                "type": "domain", "value": f"d{i}.com",
                "reason": "t", "agent": "claude",
            })
            for i in range(3)
        ]
        rv = self.client.post(
            "/api/inbox/bulk-accept", json={"record_ids": ids}
        )
        self.assertEqual(rv.status_code, 200)

        import tomllib
        rt_path = self.policy_path.replace(".toml", ".runtime.toml")
        with open(rt_path, "rb") as f:
            rt = tomllib.load(f)
        allow = rt.get("domains", {}).get("allow", {}).get("list", [])
        for d in ("d0.com", "d1.com", "d2.com"):
            self.assertIn(d, allow)

    def test_bulk_reject(self):
        ids = [
            self._add(self.inbox_dir, {
                "type": "domain", "value": f"r{i}.com",
                "reason": "t", "agent": "claude",
            })
            for i in range(2)
        ]
        rv = self.client.post(
            "/api/inbox/bulk-reject", json={"record_ids": ids}
        )
        self.assertEqual(rv.status_code, 200)
        rv2 = self.client.get("/partials/inbox")
        for d in ("r0.com", "r1.com"):
            self.assertNotIn(d.encode(), rv2.data)


if __name__ == "__main__":
    unittest.main()
