"""Tests for `addons._policy_lock` (Sprint 006 PR F, M-8).

cross-container shared/exclusive lock helper の単体検証 + 並行実行テスト。
"""

from __future__ import annotations

import multiprocessing
import os
import stat
import sys
import tempfile
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle"))

from addons._policy_lock import (  # noqa: E402
    lock_path_for,
    policy_lock_exclusive,
    policy_lock_shared,
)


# ---------------- lock_path_for ----------------


def test_lock_path_for_writable_env_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_LOCK_DIR", str(tmp_path))
    p = lock_path_for("/etc/policy.toml")
    assert p == str(tmp_path / "policy.toml.lock")


def test_lock_path_for_missing_env_dir_fallback_to_policy_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_LOCK_DIR", "/nonexistent/path/xyz")
    policy_path = tmp_path / "p.toml"
    policy_path.touch()
    p = lock_path_for(str(policy_path))
    # fallback: policy_path と同じ dir
    assert p == str(policy_path) + ".lock"


def test_lock_path_for_unwritable_falls_to_tempdir(tmp_path, monkeypatch):
    # POLICY_LOCK_DIR 不在 + policy_path の親 dir も unwritable のケース
    monkeypatch.setenv("POLICY_LOCK_DIR", "/nonexistent")
    # policy_path の親が存在しない absolute path
    p = lock_path_for("/nonexistent2/policy.toml")
    expected = os.path.join(tempfile.gettempdir(), "agent_zoo_policy.toml.lock")
    assert p == expected


# ---------------- policy_lock_shared ----------------


def test_shared_lock_creates_file_with_600_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_LOCK_DIR", str(tmp_path))
    policy_path = tmp_path / "policy.toml"
    policy_path.touch()
    with policy_lock_shared(str(policy_path)):
        lock_file = tmp_path / "policy.toml.lock"
        assert lock_file.exists()
        # 600 権限が付与されている (M3 対応)
        assert stat.S_IMODE(lock_file.stat().st_mode) == 0o600


def test_shared_lock_failure_warns_and_passes(tmp_path, monkeypatch, caplog):
    """lock open が失敗しても with 文は成功する (reader best-effort)。"""
    monkeypatch.setenv("POLICY_LOCK_DIR", str(tmp_path))
    policy_path = tmp_path / "policy.toml"
    policy_path.touch()

    real_open = os.open

    def fake_open(path, flags, mode=0o777):
        if path.endswith(".lock"):
            raise OSError(13, "Permission denied")
        return real_open(path, flags, mode)

    import logging
    caplog.set_level(logging.WARNING, logger="addons._policy_lock")
    with patch("addons._policy_lock.os.open", side_effect=fake_open):
        with policy_lock_shared(str(policy_path)):
            pass  # passthrough、例外無し
    # warning が出る
    assert any("lock acquire failed" in r.message for r in caplog.records)


# ---------------- policy_lock_exclusive ----------------


def test_exclusive_lock_creates_file_with_600_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_LOCK_DIR", str(tmp_path))
    policy_path = tmp_path / "policy.toml"
    policy_path.touch()
    with policy_lock_exclusive(str(policy_path)):
        lock_file = tmp_path / "policy.toml.lock"
        assert lock_file.exists()
        assert stat.S_IMODE(lock_file.stat().st_mode) == 0o600


def test_exclusive_lock_failure_raises(tmp_path, monkeypatch):
    """writer は lock 取得失敗時に OSError を raise する (fail-closed)。"""
    monkeypatch.setenv("POLICY_LOCK_DIR", str(tmp_path))
    policy_path = tmp_path / "policy.toml"
    policy_path.touch()

    real_open = os.open

    def fake_open(path, flags, mode=0o777):
        if path.endswith(".lock"):
            raise OSError(13, "Permission denied")
        return real_open(path, flags, mode)

    with patch("addons._policy_lock.os.open", side_effect=fake_open):
        with pytest.raises(OSError):
            with policy_lock_exclusive(str(policy_path)):
                pass


# ---------------- 並行実行テスト ----------------


def _hold_exclusive_lock(policy_path: str, hold_time: float, ready: object) -> None:
    """別プロセスで exclusive lock を hold して通知する。"""
    # 子プロセスでは os.environ が継承される (POLICY_LOCK_DIR も)
    with policy_lock_exclusive(policy_path):
        ready.set()
        time.sleep(hold_time)


def _hold_shared_lock(policy_path: str, hold_time: float, ready: object) -> None:
    """別プロセスで shared lock を hold して通知する。

    Gemini self-review #5: nested function は spawn context で pickle 不可
    なため、module-level に置く。Python 3.14 で fork default 廃止後も動作する。
    """
    with policy_lock_shared(policy_path):
        ready.set()
        time.sleep(hold_time)


def test_exclusive_blocks_shared_in_subprocess(tmp_path, monkeypatch):
    """exclusive lock 中は別プロセスからの shared lock が待つこと。

    multiprocessing.Event で「writer が lock を持った」時点を確実に待つので
    flake-free。
    """
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    monkeypatch.setenv("POLICY_LOCK_DIR", str(lock_dir))
    policy_path = tmp_path / "policy.toml"
    policy_path.touch()

    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    proc = ctx.Process(
        target=_hold_exclusive_lock,
        args=(str(policy_path), 1.0, ready),
    )
    proc.start()
    try:
        assert ready.wait(timeout=3.0), "writer did not acquire lock in time"

        # 親プロセスから shared lock を取ろうとすると blocking する
        start = time.monotonic()
        with policy_lock_shared(str(policy_path)):
            elapsed = time.monotonic() - start
        # writer hold 時間 (1.0s) 程度待たされる
        assert elapsed >= 0.4, (
            f"shared lock should block while exclusive is held, elapsed={elapsed}"
        )
    finally:
        proc.join(timeout=5.0)
        if proc.is_alive():
            proc.terminate()
            proc.join()


def test_concurrent_shared_locks_dont_block(tmp_path, monkeypatch):
    """shared lock は複数同時取得可能 (cross-process)。"""
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    monkeypatch.setenv("POLICY_LOCK_DIR", str(lock_dir))
    policy_path = tmp_path / "policy.toml"
    policy_path.touch()

    # parent と child で同時に shared lock を取れる
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()

    proc = ctx.Process(target=_hold_shared_lock, args=(str(policy_path), 0.5, ready))
    proc.start()
    try:
        assert ready.wait(timeout=3.0)
        # parent でも即座に shared lock 取れる (blocking 無し)
        start = time.monotonic()
        with policy_lock_shared(str(policy_path)):
            elapsed = time.monotonic() - start
        assert elapsed < 0.2, (
            f"concurrent shared locks should not block, elapsed={elapsed}"
        )
    finally:
        proc.join(timeout=5.0)


# ---------------- symlink follow 抑止 (M3) ----------------


def test_lock_open_refuses_symlink(tmp_path, monkeypatch):
    """既に同名の symlink がある場合、O_NOFOLLOW で open 失敗 → reader は warn"""
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW not available on this platform")
    monkeypatch.setenv("POLICY_LOCK_DIR", str(tmp_path))
    target = tmp_path / "outside.txt"
    target.touch()
    lock_path = tmp_path / "policy.toml.lock"
    os.symlink(str(target), str(lock_path))
    policy_path = tmp_path / "policy.toml"
    policy_path.touch()

    # reader: warn + passthrough (例外無し)
    with policy_lock_shared(str(policy_path)):
        pass
    # writer: raise
    with pytest.raises(OSError):
        with policy_lock_exclusive(str(policy_path)):
            pass
