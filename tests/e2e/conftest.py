"""E2E test fixtures（ADR 0003）.

- workspace: tmp に minimal `.zoo/` layout を生成
- dashboard: bundle/dashboard を Flask 直起動（Docker 不要）
- pytest-playwright が `page` fixture を提供
"""

from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = REPO_ROOT / "bundle"


def _wait_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _free_port() -> int:
    """OS が空いているポートを割り当てる（Inbox dashboard 用）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _init_db_schema(db_path: Path) -> None:
    """policy_enforcer.py と同じ schema を初期化（dashboard が空 DB でも動くように）。"""
    db = sqlite3.connect(str(db_path))
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            host TEXT, method TEXT, url TEXT, status TEXT, body_size INTEGER
        );
        CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            host TEXT, reason TEXT
        );
        CREATE TABLE IF NOT EXISTS tool_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            tool_name TEXT, input TEXT, input_size INTEGER
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            type TEXT, detail TEXT
        );
        """
    )
    db.commit()
    db.close()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """ADR 0002 layout の minimal workspace を tmp に生成。"""
    zoo = tmp_path / ".zoo"
    zoo.mkdir()
    shutil.copy(BUNDLE / "policy.toml", zoo / "policy.toml")
    (zoo / "policy.runtime.toml").write_text("")
    (zoo / "inbox").mkdir()
    (zoo / "data").mkdir()
    _init_db_schema(zoo / "data" / "harness.db")
    return tmp_path


@pytest.fixture
def dashboard(workspace: Path, tmp_path: Path):
    """bundle/dashboard を Flask で直起動して URL を返す（Docker 不要）。

    起動失敗時の調査のため stdout/stderr を tmp ログにリダイレクトし、
    `RuntimeError` のメッセージに含める。
    """
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "DB_PATH": str(workspace / ".zoo" / "data" / "harness.db"),
            "POLICY_PATH": str(workspace / ".zoo" / "policy.toml"),
            "INBOX_DIR": str(workspace / ".zoo" / "inbox"),
            "FLASK_APP": "app:app",
            "FLASK_DEBUG": "0",
        }
    )
    log_path = tmp_path / "flask.log"
    log_file = log_path.open("w")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "flask",
            "run",
            "--host=127.0.0.1",
            f"--port={port}",
        ],
        env=env,
        cwd=str(BUNDLE / "dashboard"),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    if not _wait_port("127.0.0.1", port, timeout=15):
        proc.terminate()
        proc.wait(timeout=5)
        log_file.close()
        log_text = log_path.read_text() if log_path.exists() else "(no log)"
        raise RuntimeError(
            f"dashboard failed to start on port {port}\n--- flask log ---\n{log_text}"
        )
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()


def _write_inbox_pending(
    workspace: Path,
    *,
    value: str,
    fid_suffix: str,
    type_: str = "domain",
    domain: str = "",
    reason: str = "e2e fixture",
) -> Path:
    """agent が submit した状態を fixture で再現する（ADR 0003 D5）。"""
    inbox = workspace / ".zoo" / "inbox"
    fid = f"2026-04-18T10-00-00-test-{fid_suffix}.toml"
    p = inbox / fid
    p.write_text(
        f"""schema_version = 1
created_at = "2026-04-18T10:00:00Z"
agent = "claude"
type = "{type_}"
value = "{value}"
domain = "{domain}"
reason = "{reason}"
status = "pending"
"""
    )
    return p


@pytest.fixture
def write_inbox_pending(workspace: Path):
    """test から呼びやすいよう関数 fixture 化。"""

    def _factory(**kwargs):
        return _write_inbox_pending(workspace, **kwargs)

    return _factory
