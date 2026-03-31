"""mitmproxy addon for agent-harness policy enforcement.

Features:
- Domain control (allow/deny via policy.toml)
- Rate limiting (RPM + burst per domain)
- Payload inspection (block_patterns + secret_patterns)
- Request logging to SQLite
- SSE streaming with tool_use extraction
"""

import json
import os
import sqlite3
import sys

from mitmproxy import ctx, http

# mitmproxy loads addons by path (-s flag), so add this directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))
from policy import PolicyEngine
from sse_parser import AnthropicSSEParser, ToolUse


class PolicyEnforcer:
    def __init__(self):
        policy_path = os.environ.get("POLICY_PATH", "/config/policy.toml")
        self.engine = PolicyEngine(policy_path)
        self._db: sqlite3.Connection | None = None
        self._init_db()
        self._cleanup_old_logs()
        ctx.log.info(
            f"PolicyEnforcer loaded: "
            f"{len(self.engine.allow_list)} allowed, "
            f"{len(self.engine.deny_list)} denied, "
            f"{len(self.engine.rate_limits)} rate-limited, "
            f"{len(self.engine.block_patterns)} block patterns, "
            f"{len(self.engine.secret_patterns)} secret patterns"
        )

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self.engine.db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
        return self._db

    def _init_db(self):
        """スキーマ初期化。mitmproxy起動時に__init__から1回だけ呼ばれる。
        リクエストごとには呼ばれない（INSERTのみ）。"""
        db = self._get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                host TEXT,
                method TEXT,
                url TEXT,
                status TEXT,
                body_size INTEGER
            );
            CREATE TABLE IF NOT EXISTS blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                host TEXT,
                reason TEXT
            );
            CREATE TABLE IF NOT EXISTS tool_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                tool_name TEXT,
                input TEXT,
                input_size INTEGER
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                type TEXT,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);
            CREATE INDEX IF NOT EXISTS idx_blocks_ts ON blocks(ts);
            CREATE INDEX IF NOT EXISTS idx_tool_uses_ts ON tool_uses(ts);
            CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
            """
        )
        db.commit()

    def _log_request(self, host, method, url, status, body_size, reason=""):
        """リクエストをログし、ブロック系ステータスの場合はblocksテーブルにも記録する。"""
        try:
            db = self._get_db()
            db.execute(
                "INSERT INTO requests (host, method, url, status, body_size) "
                "VALUES (?, ?, ?, ?, ?)",
                (host, method, url, status, body_size),
            )
            if status in ("BLOCKED", "RATE_LIMITED", "PAYLOAD_BLOCKED") and reason:
                db.execute(
                    "INSERT INTO blocks (host, reason) VALUES (?, ?)",
                    (host, reason),
                )
            db.commit()
        except Exception as e:
            ctx.log.error(f"DB write failed: {e}")

    def _log_tool_use(self, tool_use):
        """tool_useをDBに記録し、アラートチェックを行う。"""
        try:
            db = self._get_db()
            stored_input = tool_use.input
            max_store = self.engine.max_tool_input_store
            if max_store and len(stored_input) > max_store:
                stored_input = stored_input[:max_store] + "... (truncated)"
            db.execute(
                "INSERT INTO tool_uses (tool_name, input, input_size) "
                "VALUES (?, ?, ?)",
                (tool_use.name, stored_input, tool_use.input_size),
            )

            # アラートチェック
            alerts = self.engine.check_tool_use(
                tool_use.name, tool_use.input, tool_use.input_size
            )
            for alert in alerts:
                db.execute(
                    "INSERT INTO alerts (type, detail) VALUES (?, ?)",
                    (alert.type, alert.detail),
                )
                ctx.log.warn(f"ALERT [{alert.type}]: {alert.detail}")

            db.commit()
            ctx.log.info(f"tool_use: {tool_use.name} (size={tool_use.input_size})")
        except Exception as e:
            ctx.log.error(f"DB write failed (tool_uses): {e}")

    def _cleanup_old_logs(self):
        """log_retention_daysに基づいて古いログを自動削除する。"""
        days = self.engine.log_retention_days
        if not days:
            return
        try:
            db = self._get_db()
            days = int(days)
            for table in ("requests", "blocks", "tool_uses", "alerts"):
                db.execute(
                    f"DELETE FROM {table} WHERE ts < datetime('now', ? || ' days')",
                    (f"-{days}",),
                )
            db.commit()
            ctx.log.info(f"Cleaned up logs older than {days} days")
        except Exception as e:
            ctx.log.error(f"Log cleanup failed: {e}")

    def _log_block_tool_use(self, tool_name, reason):
        """ブロックされたtool_useをblocksテーブルに記録する。"""
        try:
            db = self._get_db()
            db.execute(
                "INSERT INTO blocks (host, reason) VALUES (?, ?)",
                (f"tool_use:{tool_name}", reason),
            )
            db.commit()
        except Exception as e:
            ctx.log.error(f"DB write failed (tool_use block): {e}")

    def request(self, flow: http.HTTPFlow):
        self.engine.maybe_reload()

        host = flow.request.host
        method = flow.request.method
        url = flow.request.url
        body = flow.request.content
        body_size = len(body) if body else 0

        # 1. ドメイン + パス制御
        req_path = flow.request.path  # URLパス（クエリ含む）
        allowed, reason = self.engine.is_allowed(host, req_path)
        if not allowed:
            self._log_request(host, method, url, "BLOCKED", body_size, reason)
            flow.response = http.Response.make(
                403, b"Blocked by policy", {"Content-Type": "text/plain"}
            )
            ctx.log.warn(f"BLOCKED: {host} ({reason})")
            return

        # 2. レート制限
        allowed, reason = self.engine.check_rate_limit(host)
        if not allowed:
            self._log_request(host, method, url, "RATE_LIMITED", body_size, reason)
            flow.response = http.Response.make(
                429,
                b"Rate limit exceeded",
                {"Content-Type": "text/plain", "Retry-After": "60"},
            )
            ctx.log.warn(f"RATE_LIMITED: {host} ({reason})")
            return

        # 3. ペイロード検査
        blocked, reason = self.engine.check_payload(body)
        if blocked:
            self._log_request(host, method, url, "PAYLOAD_BLOCKED", body_size, reason)
            flow.response = http.Response.make(
                403, b"Blocked by payload policy", {"Content-Type": "text/plain"}
            )
            ctx.log.warn(f"PAYLOAD_BLOCKED: {reason}")
            return

        self._log_request(host, method, url, "ALLOWED", body_size)

    # Note: responseheaders()は意図的に未定義。
    # mitmproxy 10.xではstream callableが使えないため、SSEレスポンスをバッファし
    # response()でtool_useを抽出する。ストリーミング透過はROADMAPの将来対応。

    def response(self, flow: http.HTTPFlow):
        """レスポンスからtool_useを抽出する。SSE/JSON両対応。"""
        if not flow.response or not flow.response.content:
            return

        content_type = flow.response.headers.get("content-type", "")

        # tool_useを抽出（SSE/JSON両対応）
        tool_uses = []
        if "text/event-stream" in content_type:
            try:
                sse_buf = AnthropicSSEParser()
                sse_buf.feed(flow.response.content)
                tool_uses = sse_buf.drain_completed()
            except Exception as e:
                ctx.log.debug(f"SSE parse error: {e}")
        elif "application/json" in content_type:
            try:
                data = json.loads(flow.response.content)
                for block in data.get("content", []):
                    if block.get("type") == "tool_use":
                        input_str = json.dumps(block.get("input", {}))
                        tool_uses.append(ToolUse(
                            name=block.get("name", ""),
                            input=input_str,
                            input_size=len(input_str),
                        ))
            except Exception as e:
                ctx.log.debug(f"JSON parse error: {e}")
        else:
            return

        # 全tool_useをログしてからブロック判定
        should_block_response = False
        for tool_use in tool_uses:
            ctx.log.info(f"tool_use detected: {tool_use.name}")
            self._log_tool_use(tool_use)
            should_block, reason = self.engine.should_block_tool_use(
                tool_use.name, tool_use.input
            )
            if should_block:
                ctx.log.warn(f"TOOL_USE_BLOCKED: {reason}")
                self._log_block_tool_use(tool_use.name, reason)
                should_block_response = True

        if should_block_response:
            flow.response = http.Response.make(
                403, b"Tool use blocked by policy",
                {"Content-Type": "text/plain"},
            )
        except Exception as e:
            ctx.log.debug(f"Response parse skipped: {e}")

    def done(self):
        """mitmproxyアドオンのライフサイクル終了時にDB接続をクローズする。"""
        if self._db:
            self._db.close()
            self._db = None


addons = [PolicyEnforcer()]
