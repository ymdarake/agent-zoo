"""Fail-closed decorators for mitmproxy event hooks.

Critical security primitive: if an addon hook raises an uncaught exception,
mitmproxy's default behavior is to log and pass the flow through (fail-open).
This silently disables policy enforcement and causes the security harness to
leak traffic. These decorators convert such exceptions into a blocking action
(fail-closed), preserving the contract that "when policy enforcement is broken,
traffic is denied, not allowed".

Usage in `policy_enforcer.py`:

    @fail_closed_block
    def request(self, flow: http.HTTPFlow): ...

    @fail_closed_block
    def response(self, flow: http.HTTPFlow): ...

    @fail_closed_ws_message
    def websocket_message(self, flow: http.HTTPFlow): ...

    @fail_closed_lifecycle
    def websocket_end(self, flow: http.HTTPFlow): ...

    @fail_closed_lifecycle
    def done(self): ...
"""
from __future__ import annotations

import functools
import sys

from mitmproxy import ctx, http


_FAIL_CLOSED_BODY = b"Policy enforcer internal error (fail-closed)"


def _log_error(self_or_cls: object, fn_name: str, exc: Exception) -> None:
    """エラー内容を ctx.log.error に送出。ctx が使えない場合は stderr にフォールバック。"""
    cls_name = type(self_or_cls).__name__ if not isinstance(self_or_cls, type) else self_or_cls.__name__
    message = (
        f"addon {cls_name}.{fn_name} raised {type(exc).__name__}: {exc} — "
        "fail-closed triggered"
    )
    try:
        ctx.log.error(message)
    except Exception:
        # ctx が未セットアップ (import 直後やテスト環境) の場合のフォールバック
        print(message, file=sys.stderr)


def fail_closed_block(fn):
    """request / response hook 用: 例外発生時に flow.response を 500 で置換し block する。

    hook が正常完了した場合 (policy 判定結果として flow.response を設定した場合も含む)
    は何も触らない。
    """

    @functools.wraps(fn)
    def wrapper(self, flow):
        try:
            return fn(self, flow)
        except Exception as exc:
            _log_error(self, fn.__name__, exc)
            flow.response = http.Response.make(
                500,
                _FAIL_CLOSED_BODY,
                {"Content-Type": "text/plain"},
            )

    return wrapper


def fail_closed_ws_message(fn):
    """websocket_message hook 用: 例外発生時に直前の message を drop する。

    message を drop することで、agent はそのメッセージを受信せず、
    policy 判定が壊れた tool_call を実行できない。
    """

    @functools.wraps(fn)
    def wrapper(self, flow):
        try:
            return fn(self, flow)
        except Exception as exc:
            _log_error(self, fn.__name__, exc)
            try:
                if flow.websocket and flow.websocket.messages:
                    flow.websocket.messages[-1].drop()
            except Exception:
                # drop 自体が壊れても mitmproxy に伝播させない（fail-closed の原則）
                pass

    return wrapper


def fail_closed_lifecycle(fn):
    """lifecycle hook 用 (done / websocket_end 等): 例外発生時はログのみ。

    lifecycle hook は flow 遮断の手段がない (cleanup タイミング) ため、
    ログ出力に留め、再 raise しないことで他 addon / mitmproxy 本体を守る。
    """

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:
            _log_error(self, fn.__name__, exc)

    return wrapper
