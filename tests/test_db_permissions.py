"""Tests for `addons._db_secure.secure_db_file` (Sprint 006 PR D, G3-B1).

harness.db + WAL + SHM を chmod 600 に強制。bind mount で EPERM の場合は
log 経由で通知し fail-safe で続行する。
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle"))

from addons._db_secure import secure_db_file  # noqa: E402


class TestSecureDbFile:
    def test_chmod_600_on_main_db(self, tmp_path):
        db = tmp_path / "harness.db"
        db.write_bytes(b"")
        db.chmod(0o644)  # 初期値を明示的に 644
        secure_db_file(str(db))
        assert stat.S_IMODE(db.stat().st_mode) == 0o600

    def test_chmod_600_on_wal_and_shm(self, tmp_path):
        db = tmp_path / "harness.db"
        wal = tmp_path / "harness.db-wal"
        shm = tmp_path / "harness.db-shm"
        for p in (db, wal, shm):
            p.write_bytes(b"")
            p.chmod(0o644)
        secure_db_file(str(db))
        for p in (db, wal, shm):
            assert stat.S_IMODE(p.stat().st_mode) == 0o600, f"{p.name} mode not 600"

    def test_missing_wal_and_shm_ok(self, tmp_path):
        """WAL / SHM が未生成 (初期化直後) でもエラーにならない"""
        db = tmp_path / "harness.db"
        db.write_bytes(b"")
        # WAL / SHM 無しで呼び出し → DB 本体だけ chmod される
        secure_db_file(str(db))
        assert stat.S_IMODE(db.stat().st_mode) == 0o600

    def test_eperm_fail_safe(self, tmp_path):
        """bind mount で chmod が EPERM になっても log error で続行 (fail-safe)"""
        db = tmp_path / "harness.db"
        db.write_bytes(b"")
        errors: list[str] = []

        def fake_chmod(path, mode, *, follow_symlinks=True):
            raise OSError(1, "Operation not permitted")

        with patch("os.chmod", side_effect=fake_chmod):
            secure_db_file(str(db), log_fn=errors.append)
        # log_fn が呼ばれる（最低 1 回、DB 本体分）
        assert len(errors) >= 1
        assert "harness.db" in errors[0]

    def test_log_fn_optional(self, tmp_path):
        """log_fn を省略しても例外を投げない (silent 失敗)"""
        db = tmp_path / "harness.db"
        db.write_bytes(b"")

        def fake_chmod(path, mode, *, follow_symlinks=True):
            raise OSError(1, "EPERM")

        with patch("os.chmod", side_effect=fake_chmod):
            secure_db_file(str(db))  # no log_fn, should not raise

    def test_symlink_not_followed(self, tmp_path):
        """self-review M-1: symlink を chmod 600 で follow しないこと"""
        target = tmp_path / "outside.conf"
        target.write_bytes(b"")
        target.chmod(0o644)
        db = tmp_path / "harness.db"
        os.symlink(str(target), str(db))
        # secure_db_file は symlink を follow しないので outside.conf の mode は変化なし
        secure_db_file(str(db))
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
