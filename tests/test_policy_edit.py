"""Tests for policy editing and whitelist nurturing."""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.policy_edit import (
    add_to_allow_list,
    add_to_dismissed,
    atomic_write,
    get_whitelist_candidates,
    remove_from_dismissed,
)

BASIC_POLICY = """[general]
log_db = "/tmp/test-harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = ["*.evil.com"]

[domains.dismissed]
"""


def _write_policy(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    f.write(content)
    f.close()
    return f.name


def _create_test_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            host TEXT, reason TEXT
        );
        INSERT INTO blocks (host, reason) VALUES ('registry.npmjs.org', 'not in allow list');
        INSERT INTO blocks (host, reason) VALUES ('registry.npmjs.org', 'not in allow list');
        INSERT INTO blocks (host, reason) VALUES ('registry.npmjs.org', 'not in allow list');
        INSERT INTO blocks (host, reason) VALUES ('pypi.org', 'not in allow list');
        """
    )
    db.commit()
    db.close()
    return path


class TestAtomicWrite(unittest.TestCase):
    def test_writes_content(self):
        path = _write_policy("")
        self.addCleanup(os.unlink, path)
        atomic_write(path, "new content")
        with open(path) as f:
            self.assertEqual(f.read(), "new content")

    def test_no_partial_file_on_success(self):
        """成功時に中間ファイルが残らない"""
        path = _write_policy("")
        self.addCleanup(os.unlink, path)
        dir_name = os.path.dirname(path)
        before = set(os.listdir(dir_name))
        atomic_write(path, "content")
        after = set(os.listdir(dir_name))
        # 新しいファイルが増えていない（tmpファイルが残っていない）
        self.assertEqual(len(after - before), 0)


class TestAddToAllowList(unittest.TestCase):
    def test_adds_domain(self):
        path = _write_policy(BASIC_POLICY)
        self.addCleanup(os.unlink, path)
        add_to_allow_list(path, "github.com")
        with open(path) as f:
            content = f.read()
        self.assertIn("github.com", content)
        self.assertIn("api.anthropic.com", content)  # 既存は維持

    def test_no_duplicate(self):
        """既に存在するドメインを追加しても重複しない"""
        path = _write_policy(BASIC_POLICY)
        self.addCleanup(os.unlink, path)
        add_to_allow_list(path, "api.anthropic.com")
        with open(path) as f:
            content = f.read()
        self.assertEqual(content.count("api.anthropic.com"), 1)

    def test_result_is_valid_toml(self):
        """書き換え後のファイルが有効なTOML"""
        import tomllib

        path = _write_policy(BASIC_POLICY)
        self.addCleanup(os.unlink, path)
        add_to_allow_list(path, "new-domain.com")
        with open(path, "rb") as f:
            policy = tomllib.load(f)
        self.assertIn("new-domain.com", policy["domains"]["allow"]["list"])


class TestAddToDismissed(unittest.TestCase):
    def test_adds_dismissed(self):
        path = _write_policy(BASIC_POLICY)
        self.addCleanup(os.unlink, path)
        add_to_dismissed(path, "registry.npmjs.org", "ホスト側でinstall済み")

        import tomllib

        with open(path, "rb") as f:
            policy = tomllib.load(f)
        self.assertIn("registry.npmjs.org", policy["domains"]["dismissed"])

    def test_remove_from_dismissed(self):
        path = _write_policy(BASIC_POLICY)
        self.addCleanup(os.unlink, path)
        add_to_dismissed(path, "registry.npmjs.org", "test")
        remove_from_dismissed(path, "registry.npmjs.org")

        import tomllib

        with open(path, "rb") as f:
            policy = tomllib.load(f)
        self.assertNotIn("registry.npmjs.org", policy["domains"]["dismissed"])


class TestWhitelistCandidates(unittest.TestCase):
    def test_returns_candidates(self):
        db_path = _create_test_db()
        self.addCleanup(os.unlink, db_path)
        policy_path = _write_policy(BASIC_POLICY)
        self.addCleanup(os.unlink, policy_path)

        candidates = get_whitelist_candidates(db_path, policy_path)
        self.assertGreater(len(candidates), 0)
        hosts = [c["host"] for c in candidates]
        self.assertIn("registry.npmjs.org", hosts)

    def test_excludes_already_allowed(self):
        """既にallow listにあるドメインは候補に含まれない"""
        db_path = _create_test_db()
        self.addCleanup(os.unlink, db_path)
        # api.anthropic.comをブロックログに追加
        db = sqlite3.connect(db_path)
        db.execute(
            "INSERT INTO blocks (host, reason) VALUES (?, ?)",
            ("api.anthropic.com", "test"),
        )
        db.commit()
        db.close()

        policy_path = _write_policy(BASIC_POLICY)
        self.addCleanup(os.unlink, policy_path)

        candidates = get_whitelist_candidates(db_path, policy_path)
        hosts = [c["host"] for c in candidates]
        self.assertNotIn("api.anthropic.com", hosts)

    def test_excludes_dismissed(self):
        """dismissed済みドメインは候補に含まれない"""
        db_path = _create_test_db()
        self.addCleanup(os.unlink, db_path)
        policy_with_dismissed = BASIC_POLICY + '"registry.npmjs.org" = { reason = "test", date = "2026-03-30" }\n'
        policy_path = _write_policy(policy_with_dismissed)
        self.addCleanup(os.unlink, policy_path)

        candidates = get_whitelist_candidates(db_path, policy_path)
        hosts = [c["host"] for c in candidates]
        self.assertNotIn("registry.npmjs.org", hosts)

    def test_sorted_by_count(self):
        """ブロック回数の多い順にソートされる"""
        db_path = _create_test_db()
        self.addCleanup(os.unlink, db_path)
        policy_path = _write_policy(BASIC_POLICY)
        self.addCleanup(os.unlink, policy_path)

        candidates = get_whitelist_candidates(db_path, policy_path)
        if len(candidates) >= 2:
            self.assertGreaterEqual(candidates[0]["count"], candidates[1]["count"])


if __name__ == "__main__":
    unittest.main()
