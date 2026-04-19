"""Tests for `_apply_accept` strict domain validation (Sprint 006 PR D self-review M-3).

inbox accept で agent が書いた value (domain) を runtime policy に流す前に
M-5 の strict regex を要求する。invalid な domain は ValueError で拒否し、
api_inbox_accept は 400 を返す。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import _apply_accept  # noqa: E402


class TestApplyAcceptValidation(unittest.TestCase):
    def setUp(self):
        # add_to_allow_list が書き込む先の temp policy
        self.tmpdir = tempfile.mkdtemp()
        self.policy_path = os.path.join(self.tmpdir, "policy.toml")
        with open(self.policy_path, "w") as f:
            f.write("[domains.allow]\nlist = []\n")
        os.environ["POLICY_PATH"] = self.policy_path

    def tearDown(self):
        for f in os.listdir(self.tmpdir):
            try:
                os.unlink(os.path.join(self.tmpdir, f))
            except OSError:
                pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass
        os.environ.pop("POLICY_PATH", None)

    def test_valid_domain_accepted(self):
        # 通常 case: 正しい domain は ValueError を投げない
        _apply_accept({"type": "domain", "value": "api.example.com"})

    def test_localhost_rejected(self):
        # M-5 strict regex で localhost (single label) は reject
        with self.assertRaises(ValueError) as ctx:
            _apply_accept({"type": "domain", "value": "localhost"})
        self.assertIn("invalid", str(ctx.exception))

    def test_tld_only_wildcard_rejected(self):
        with self.assertRaises(ValueError):
            _apply_accept({"type": "domain", "value": "*.com"})

    def test_consecutive_dot_rejected(self):
        with self.assertRaises(ValueError):
            _apply_accept({"type": "domain", "value": "a..com"})

    def test_path_type_validates_domain_field(self):
        # path type は record["domain"] を使う、それを validate
        with self.assertRaises(ValueError):
            _apply_accept({"type": "path", "domain": "localhost", "value": "/api/*"})

    def test_path_type_with_valid_domain_accepted(self):
        _apply_accept({"type": "path", "domain": "api.example.com", "value": "/v1/*"})


if __name__ == "__main__":
    unittest.main()
