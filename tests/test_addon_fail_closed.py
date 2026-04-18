"""Tests for `addons._fail_closed` fail-closed decorators.

Critical security primitive: if a mitmproxy addon hook raises, mitmproxy's
default behavior is to log and pass the flow through (fail-open). The
decorators must convert that into a blocking action (fail-closed).

Tests mock `mitmproxy.ctx` / `mitmproxy.http` via `sys.modules` so this file
runs without `mitmproxy` installed (matching the rest of `tests/` layout).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

# ── mitmproxy の sys.modules shim ──
# addons._fail_closed は `from mitmproxy import ctx, http` を行うが、
# mitmproxy はランタイム (proxy コンテナ) にしか存在しない。
# テストでは shim で置き換え、decorator の振る舞いだけを検証する。
_mitm = MagicMock()
sys.modules.setdefault("mitmproxy", _mitm)
sys.modules.setdefault("mitmproxy.ctx", _mitm.ctx)
sys.modules.setdefault("mitmproxy.http", _mitm.http)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle"))

from addons._fail_closed import (  # noqa: E402  (sys.path 設定後に import)
    fail_closed_block,
    fail_closed_lifecycle,
    fail_closed_ws_message,
)


class _FakeAddon:
    """addon の self 側モック（type(self).__name__ を提供）。"""

    pass


@pytest.fixture
def mitm_mock(monkeypatch):
    """各テストで ctx.log と http.Response を新規 MagicMock に差し替える。"""
    from addons import _fail_closed

    log = MagicMock()
    response_obj = MagicMock(name="BlockResponse500")
    http_mod = MagicMock()
    http_mod.Response.make = MagicMock(return_value=response_obj)

    ctx_mod = MagicMock()
    ctx_mod.log = log

    monkeypatch.setattr(_fail_closed, "ctx", ctx_mod)
    monkeypatch.setattr(_fail_closed, "http", http_mod)
    return log, http_mod, response_obj


# ─────────────────────────────────────────────────────────
# fail_closed_block (request / response hook 共通)
# ─────────────────────────────────────────────────────────


def test_block_normal_execution_does_not_block(mitm_mock):
    """例外が起きない場合は flow.response を触らず、log も出ない。"""
    log, http_mod, _ = mitm_mock
    flow = MagicMock()
    flow.response = None

    @fail_closed_block
    def hook(self, flow):
        # 正常完了
        return None

    hook(_FakeAddon(), flow)

    log.error.assert_not_called()
    http_mod.Response.make.assert_not_called()
    assert flow.response is None


def test_block_normal_preserves_hook_explicit_response(mitm_mock):
    """hook 内で明示的に flow.response を設定した場合はそのまま残る（policy 判定結果の block）。"""
    log, http_mod, _ = mitm_mock
    flow = MagicMock()
    hook_set_response = MagicMock(name="PolicyBlock403")

    @fail_closed_block
    def hook(self, flow):
        flow.response = hook_set_response  # policy 判定で 403 set

    hook(_FakeAddon(), flow)

    log.error.assert_not_called()
    http_mod.Response.make.assert_not_called()
    assert flow.response is hook_set_response


def test_block_exception_sets_500_response(mitm_mock):
    """例外発生時に flow.response が 500 で埋まり、エラーログが出る。"""
    log, http_mod, response_obj = mitm_mock
    flow = MagicMock()

    @fail_closed_block
    def hook(self, flow):
        raise KeyError("simulated addon bug")

    hook(_FakeAddon(), flow)  # 再 raise しないこと

    # 500 response で置換
    assert flow.response is response_obj
    http_mod.Response.make.assert_called_once()
    status_code = http_mod.Response.make.call_args[0][0]
    assert status_code == 500

    # エラーログ: クラス名 / メソッド名 / 例外タイプ / fail-closed 文字列を含む
    log.error.assert_called_once()
    msg = log.error.call_args[0][0]
    assert "_FakeAddon" in msg
    assert "hook" in msg
    assert "KeyError" in msg
    assert "fail-closed" in msg.lower()


def test_block_exception_never_reraises(mitm_mock):
    """決して再 raise しない（mitmproxy 側に伝播させない）。"""
    flow = MagicMock()

    @fail_closed_block
    def hook(self, flow):
        raise RuntimeError("boom")

    # pytest.raises でないことを確認
    hook(_FakeAddon(), flow)  # returns None silently


# ─────────────────────────────────────────────────────────
# fail_closed_ws_message
# ─────────────────────────────────────────────────────────


def test_ws_message_exception_drops_last_message(mitm_mock):
    """WebSocket message hook の例外で、最後の message が drop される。"""
    log, _, _ = mitm_mock
    flow = MagicMock()
    flow.websocket = MagicMock()
    m1 = MagicMock(name="prev_message")
    m2 = MagicMock(name="current_message")
    flow.websocket.messages = [m1, m2]

    @fail_closed_ws_message
    def hook(self, flow):
        raise ValueError("parse failure")

    hook(_FakeAddon(), flow)

    m2.drop.assert_called_once()
    m1.drop.assert_not_called()
    log.error.assert_called_once()


def test_ws_message_exception_without_websocket_does_not_raise(mitm_mock):
    """flow.websocket が None でも decorator 自身は raise しない。"""
    log, _, _ = mitm_mock
    flow = MagicMock()
    flow.websocket = None

    @fail_closed_ws_message
    def hook(self, flow):
        raise ValueError("boom")

    hook(_FakeAddon(), flow)  # should not raise

    log.error.assert_called_once()


def test_ws_message_exception_with_empty_messages_does_not_raise(mitm_mock):
    """flow.websocket.messages が空でも decorator 自身は raise しない。"""
    log, _, _ = mitm_mock
    flow = MagicMock()
    flow.websocket = MagicMock()
    flow.websocket.messages = []

    @fail_closed_ws_message
    def hook(self, flow):
        raise ValueError("boom")

    hook(_FakeAddon(), flow)

    log.error.assert_called_once()


def test_ws_message_normal_execution_does_not_drop(mitm_mock):
    """正常完了時は drop を呼ばない。"""
    log, _, _ = mitm_mock
    flow = MagicMock()
    flow.websocket = MagicMock()
    m1 = MagicMock()
    flow.websocket.messages = [m1]

    @fail_closed_ws_message
    def hook(self, flow):
        return None

    hook(_FakeAddon(), flow)

    m1.drop.assert_not_called()
    log.error.assert_not_called()


# ─────────────────────────────────────────────────────────
# fail_closed_lifecycle (done, websocket_end 等)
# ─────────────────────────────────────────────────────────


def test_lifecycle_exception_logs_only(mitm_mock):
    """lifecycle hook の例外はログのみ、再 raise しない。"""
    log, _, _ = mitm_mock

    @fail_closed_lifecycle
    def done_hook(self):
        raise RuntimeError("cleanup failed")

    done_hook(_FakeAddon())  # should not raise

    log.error.assert_called_once()
    msg = log.error.call_args[0][0]
    assert "_FakeAddon" in msg
    assert "done_hook" in msg
    assert "RuntimeError" in msg


def test_lifecycle_normal_execution_runs(mitm_mock):
    """lifecycle hook の正常呼び出しは return 値を返す。"""
    log, _, _ = mitm_mock

    @fail_closed_lifecycle
    def done_hook(self):
        return "cleaned"

    assert done_hook(_FakeAddon()) == "cleaned"
    log.error.assert_not_called()


def test_lifecycle_accepts_extra_args(mitm_mock):
    """websocket_end(self, flow) のような (self, ...) シグネチャでも動く。"""
    log, _, _ = mitm_mock
    flow = MagicMock()

    @fail_closed_lifecycle
    def hook(self, flow):
        raise ValueError("boom")

    hook(_FakeAddon(), flow)  # should not raise

    log.error.assert_called_once()


# ─────────────────────────────────────────────────────────
# ログ fallback (ctx が参照できない場合)
# ─────────────────────────────────────────────────────────


def test_log_fallback_when_ctx_unavailable(monkeypatch, capsys):
    """ctx.log への書込が失敗しても例外で死なず stderr にフォールバックする。"""
    from addons import _fail_closed

    # ctx を壊す（log.error が AttributeError を raise）
    broken_ctx = MagicMock()
    broken_ctx.log.error.side_effect = AttributeError("ctx not ready")
    monkeypatch.setattr(_fail_closed, "ctx", broken_ctx)

    flow = MagicMock()

    @fail_closed_block
    def hook(self, flow):
        raise KeyError("boom")

    hook(_FakeAddon(), flow)  # should not raise

    captured = capsys.readouterr()
    assert "fail-closed" in captured.err.lower() or "KeyError" in captured.err
