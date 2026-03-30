"""Tests for dashboard/app.py - Flask API endpoints."""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))

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


if __name__ == "__main__":
    unittest.main()
