"""Path traversal 防御テスト（包括レビュー H-2 対応）.

Sprint 005 PR B で `policy_inbox.mark_status` と dashboard の inbox endpoints に
strict regex + path resolve チェックを追加。本ファイルで両層を独立検証する。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "addons"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from policy_inbox import add_request, mark_status  # noqa: E402


class TestMarkStatusPathTraversal(unittest.TestCase):
    """policy_inbox.mark_status が path traversal / invalid id を弾くこと。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test-inbox-trav-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dotdot_path_rejected(self):
        """record_id='../escape' のような path traversal は ValueError で reject。"""
        with self.assertRaises(ValueError) as ctx:
            mark_status(self.tmp, "../escape", "rejected")
        self.assertIn("invalid", str(ctx.exception).lower())

    def test_slash_path_rejected(self):
        with self.assertRaises(ValueError):
            mark_status(self.tmp, "sub/dir", "rejected")

    def test_backslash_path_rejected(self):
        with self.assertRaises(ValueError):
            mark_status(self.tmp, "sub\\dir", "rejected")

    def test_null_byte_rejected(self):
        with self.assertRaises(ValueError):
            mark_status(self.tmp, "good\x00bad", "rejected")

    def test_empty_id_rejected(self):
        with self.assertRaises(ValueError):
            mark_status(self.tmp, "", "rejected")

    def test_dot_only_rejected(self):
        """`.` は ".toml" を生成して current dir の何かを触る経路となりうる。"""
        with self.assertRaises(ValueError):
            mark_status(self.tmp, ".", "rejected")

    def test_valid_id_normal_flow(self):
        """正常な ISO8601 形式 record_id は通り、通常通り status 更新される。"""
        rid = add_request(
            self.tmp,
            {"type": "domain", "value": "ok.example.com", "reason": "t", "agent": "c"},
        )
        self.assertIsNotNone(rid)
        mark_status(self.tmp, rid, "rejected")
        # ファイルが更新され inbox_dir の中に残っている
        self.assertTrue((Path(self.tmp) / f"{rid}.toml").exists())


class TestDashboardRecordIdValidation(unittest.TestCase):
    """dashboard 側でも API 層で record_id を弾くこと (defense-in-depth)。"""

    def setUp(self):
        from app import app
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.tmp = tempfile.mkdtemp(prefix="test-api-inbox-")
        os.environ["INBOX_DIR"] = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reject_rejects_dotdot_record_id(self):
        rv = self.client.post(
            "/api/inbox/reject",
            json={"record_id": "../escape"},
        )
        self.assertEqual(rv.status_code, 400)
        self.assertIn("invalid", rv.get_json()["error"].lower())

    def test_reject_rejects_slash_record_id(self):
        rv = self.client.post(
            "/api/inbox/reject",
            json={"record_id": "a/b"},
        )
        self.assertEqual(rv.status_code, 400)

    def test_accept_rejects_dotdot_record_id(self):
        rv = self.client.post(
            "/api/inbox/accept",
            json={"record_id": "../config/policy"},
        )
        self.assertEqual(rv.status_code, 400)

    def test_bulk_accept_filters_invalid_ids(self):
        """bulk は invalid を silently skip する (成功件数が返る)。"""
        rv = self.client.post(
            "/api/inbox/bulk-accept",
            json={"record_ids": ["../escape", "b/c", "\x00evil"]},
        )
        self.assertEqual(rv.status_code, 200)
        # invalid ids は filter されるので accepted は 0
        self.assertEqual(rv.get_json()["accepted"], 0)

    def test_bulk_reject_filters_invalid_ids(self):
        rv = self.client.post(
            "/api/inbox/bulk-reject",
            json={"record_ids": ["../escape", "a/b"]},
        )
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(rv.get_json()["rejected"], 0)


if __name__ == "__main__":
    unittest.main()
