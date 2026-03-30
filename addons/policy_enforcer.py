"""mitmproxy addon for agent-harness policy enforcement.

Features:
- Domain control (allow/deny via policy.toml)
- Rate limiting (RPM + burst per domain)
- Payload inspection (block_patterns + secret_patterns)
- Request logging to SQLite
- SSE streaming passthrough (tool_use detection is Phase 2b)
"""

import os
import sqlite3
import sys

from mitmproxy import ctx, http

# mitmproxy loads addons by path (-s flag), so add this directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))
from policy import PolicyEngine


class PolicyEnforcer:
    def __init__(self):
        policy_path = os.environ.get("POLICY_PATH", "/config/policy.toml")
        self.engine = PolicyEngine(policy_path)
        self._db: sqlite3.Connection | None = None
        self._init_db()
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

    def request(self, flow: http.HTTPFlow):
        self.engine.maybe_reload()

        host = flow.request.host
        method = flow.request.method
        url = flow.request.url
        body = flow.request.content
        body_size = len(body) if body else 0

        # 1. ドメイン制御
        allowed, reason = self.engine.is_allowed(host)
        if not allowed:
            self._log_request(host, method, url, "BLOCKED", body_size, reason)
            flow.kill()
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
            flow.kill()
            ctx.log.warn(f"PAYLOAD_BLOCKED: {reason}")
            return

        self._log_request(host, method, url, "ALLOWED", body_size)

    def responseheaders(self, flow: http.HTTPFlow):
        """SSEストリーミングレスポンスは透過させる（tool_use検出はPhase 2b）"""
        if flow.response:
            content_type = flow.response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                flow.response.stream = True

    def done(self):
        """mitmproxyアドオンのライフサイクル終了時にDB接続をクローズする。"""
        if self._db:
            self._db.close()
            self._db = None


addons = [PolicyEnforcer()]
