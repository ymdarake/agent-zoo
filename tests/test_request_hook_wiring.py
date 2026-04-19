"""Integration test: PolicyEnforcer.request() の wiring 検証 (self-review H-4).

各 helper (scrub_url / check_url_secrets / Content-Length 413) は単体テスト済だが、
request() hook 内の判定順序 / DB 書込時の URL scrubbing / blocks テーブルへの
新 status 転記は wiring の正しさが pure-helper テストでは検証できない。

mitmproxy モジュールを sys.modules shim で置換し、最小限の policy.toml と
sqlite を temp で立てて PolicyEnforcer.request() を直接呼ぶ。
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

# ── mitmproxy の sys.modules shim ──
# 注意: setdefault は他テスト (test_addon_fail_closed.py) で既に登録済の場合 NO-OP。
# そのため必ず sys.modules 由来の _mitm を取得し、それに side_effect を設定する。
_mitm = sys.modules.setdefault("mitmproxy", MagicMock())
sys.modules.setdefault("mitmproxy.ctx", _mitm.ctx)
sys.modules.setdefault("mitmproxy.http", _mitm.http)
sys.modules.setdefault("mitmproxy.exceptions", _mitm.exceptions)


# Response.make を実物に近い形で再現（assertion で status_code / content を見るため）
class _FakeResponse:
    def __init__(self, status_code: int, content: bytes, headers: dict):
        self.status_code = status_code
        self.content = content
        self.headers = headers


def _make_response(status, content=b"", headers=None):
    return _FakeResponse(status, content, headers or {})


_mitm.http.Response.make.side_effect = _make_response


@pytest.fixture
def policy_path(tmp_path):
    """secret_patterns 込みの最小 policy.toml を temp に書く。"""
    p = tmp_path / "policy.toml"
    p.write_text(
        f"""
[general]
log_db = "{tmp_path}/harness.db"

[domains.allow]
list = ["api.example.com"]

[domains.deny]
list = []

[payload_rules]
secret_patterns = ["ANTHROPIC_API_KEY"]
""".lstrip()
    )
    return str(p)


@pytest.fixture
def enforcer(policy_path, monkeypatch):
    """PolicyEnforcer を temp policy/db で起動。

    addons モジュールを差し替え可能にするため、import 直前に POLICY_PATH を
    monkeypatch する。既に import 済の場合は addons = [PolicyEnforcer()] が
    module-level で旧 path を握っているため、test 専用に新 instance を作る。
    """
    monkeypatch.setenv("POLICY_PATH", policy_path)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle"))
    # 既に import 済ならキャッシュをクリア
    for mod in list(sys.modules):
        if mod.startswith("addons.") or mod == "addons":
            sys.modules.pop(mod, None)
    from addons.policy_enforcer import PolicyEnforcer  # noqa: E402
    return PolicyEnforcer()


def _make_flow(method, url, headers=None, body=b""):
    """mitmproxy.http.HTTPFlow を MagicMock で再現。"""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    flow = MagicMock()
    flow.request.host = parts.hostname or ""
    flow.request.method = method
    flow.request.url = url
    flow.request.path = parts.path + (f"?{parts.query}" if parts.query else "")
    flow.request.content = body
    flow.request.headers = headers or {}
    flow.response = None
    return flow


def _last_request_row(db_path):
    db = sqlite3.connect(db_path)
    try:
        row = db.execute(
            "SELECT host, status, url FROM requests ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        db.close()
    return row


def _block_count(db_path):
    db = sqlite3.connect(db_path)
    try:
        return db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    finally:
        db.close()


class TestRequestHookWiring:
    def test_allowed_request_logged_with_scrubbed_url(self, enforcer, tmp_path):
        flow = _make_flow(
            "GET",
            "https://api.example.com/v1/messages?api_key=secret",
            headers={"content-length": "10"},
            body=b'{"x":"y"}',
        )
        enforcer.request(flow)
        # response 未設定 = 通過
        assert flow.response is None
        host, status, url = _last_request_row(f"{tmp_path}/harness.db")
        assert status == "ALLOWED"
        # scrubbed URL が DB に保存されている (raw query は流出していない)
        assert "secret" not in url
        assert "?[redacted]" in url

    def test_content_length_over_limit_returns_413_before_domain_check(
        self, enforcer, tmp_path
    ):
        # 1MB+1B、ドメインは allow にあるが Content-Length 前段で 413
        flow = _make_flow(
            "POST",
            "https://api.example.com/v1/large",
            headers={"content-length": str(1024 * 1024 + 1)},
            body=b"x" * 100,  # 実 body は小さくても header が大きければ 413
        )
        enforcer.request(flow)
        assert flow.response is not None
        assert flow.response.status_code == 413
        host, status, _ = _last_request_row(f"{tmp_path}/harness.db")
        assert status == "BODY_TOO_LARGE"
        # blocks テーブルにも転記される (H-1 修正の検証)
        assert _block_count(f"{tmp_path}/harness.db") == 1

    def test_url_with_secret_returns_403_url_secret_blocked(self, enforcer, tmp_path):
        flow = _make_flow(
            "GET",
            "https://api.example.com/v1/messages?ANTHROPIC_API_KEY=sk-xxxx",
            headers={"content-length": "0"},
            body=b"",
        )
        enforcer.request(flow)
        assert flow.response is not None
        assert flow.response.status_code == 403
        host, status, url = _last_request_row(f"{tmp_path}/harness.db")
        assert status == "URL_SECRET_BLOCKED"
        assert "?[redacted]" in url
        assert "sk-xxxx" not in url
        # blocks テーブル転記 (H-1 修正)
        assert _block_count(f"{tmp_path}/harness.db") == 1

    def test_disallowed_domain_blocked_with_scrubbed_url(self, enforcer, tmp_path):
        flow = _make_flow(
            "GET",
            "https://evil.com/?token=abc",
            headers={"content-length": "0"},
            body=b"",
        )
        enforcer.request(flow)
        assert flow.response is not None
        assert flow.response.status_code == 403
        host, status, url = _last_request_row(f"{tmp_path}/harness.db")
        assert status == "BLOCKED"
        # ドメイン拒否でも URL は scrub されて DB 保存（M-2 一貫性）
        assert "?[redacted]" in url
        assert "abc" not in url
