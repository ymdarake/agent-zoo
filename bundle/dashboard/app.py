"""Agent Harness Dashboard - Flask + HTMX application."""

import os
import secrets
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, render_template, request
from flask_wtf.csrf import CSRFProtect

# Import policy editing utilities
# In Docker: addons mounted at /app/addons via docker-compose
# Locally: ../addons relative to dashboard/
for p in [
    os.path.join(os.path.dirname(__file__), "..", "addons"),
    os.path.join(os.path.dirname(__file__), "addons"),
    "/app/addons",
]:
    if os.path.isdir(p):
        sys.path.insert(0, p)
        break
from policy_edit import (
    _runtime_path,
    add_to_allow_list,
    add_to_dismissed,
    add_to_paths_allow,
    get_whitelist_candidates,
    remove_from_allow_list,
    remove_from_dismissed,
    remove_from_paths_allow,
)
from _status_constants import (
    BLOCK_STATUSES as _BLOCK_STATUSES,
    block_statuses_sql_placeholders as _block_statuses_sql_placeholders,
)
from policy_inbox import (
    _RECORD_ID_RE as _INBOX_RECORD_ID_RE,
)

_BLOCK_STATUSES_PLACEHOLDERS = _block_statuses_sql_placeholders()
from policy_inbox import (
    bulk_mark_status as inbox_bulk_mark_status,
)
from policy_inbox import (
    list_requests as inbox_list_requests,
)
from policy_inbox import (
    mark_status as inbox_mark_status,
)

app = Flask(__name__)

# CSRF 対策 (包括レビュー H-1): 全 POST / PUT / PATCH / DELETE で token 検証。
# dashboard は localhost bind だが、ブラウザ経由 CSRF / DNS rebinding で任意 origin
# からの POST が成立しうるため防御が必須。
# SECRET_KEY は env 優先（再起動で token を失効させたくない本番想定）。
# 未設定 / 空白のみの場合はプロセスごとの random 値で fallback（単一 worker の dev 想定）。
app.config["SECRET_KEY"] = (
    os.environ.get("SECRET_KEY", "").strip() or secrets.token_hex(32)
)
# HTMX からの token 送出を header ベースで許容（body だけでなく X-CSRFToken を読む）
app.config["WTF_CSRF_HEADERS"] = ["X-CSRFToken", "X-CSRF-Token"]

# Sprint 007 PR G (ADR 0004): asset cache busting 用 version。env 未設定時は空文字
# default で Jinja UndefinedError を回避。PR I で git short sha 等の注入を検討。
# `?v={{ asset_version }}` を template 側で defensive に出すパターンが Plan G review G3。
app.config["ASSET_VERSION"] = os.environ.get("ASSET_VERSION", "")
# Flask-WTF 1.2.x は TESTING=True でも CSRF を自動無効化しない。既存 test は setUp で
# `app.config["WTF_CSRF_ENABLED"] = False` を明示指定している。CSRF 動作検証は
# test_dashboard_csrf.py で WTF_CSRF_ENABLED=True にして実施。
csrf = CSRFProtect(app)


# 包括レビュー G3-B2 (DNS rebinding 対策): Host ヘッダを whitelist に限定。
# 悪意サイトが自ドメインの A レコードを 127.0.0.1 に設定することで同一 origin
# policy を回避して dashboard を直接叩く攻撃 (DNS rebinding) を防ぐ。
# HTTP Host RFC 7230: case-insensitive なので小文字で正規化。env の trailing whitespace
# や大文字設定ミスを吸収するため strip + lower を常に通す。
_ALLOWED_HOSTS = frozenset(
    h.strip().lower()
    for h in os.environ.get("DASHBOARD_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
)


def _extract_host_only(host_header: str) -> str:
    """Host ヘッダから port を除去した hostname を返す（IPv6 リテラル対応 + 不正 port 拒否）。

    `request.host` は `'127.0.0.1:8080'` や `'[::1]:8080'` の形で来る。
    urlsplit は `[::1]` を正しく hostname として解釈する。

    攻撃対応:
    - `Host: localhost:evil.com` (port が非数値) → `parsed.port` アクセスで ValueError
      → 空文字列を返し whitelist 外で reject
    - `Host: 127.0.0.1.` (末尾 dot, DNS absolute) → rstrip で除去して比較
    """
    parsed = urlsplit(f"http://{host_header}")
    try:
        parsed.port  # 非数値 port なら ValueError を raise
    except ValueError:
        return ""
    return (parsed.hostname or "").rstrip(".")


@app.before_request
def _enforce_strict_host() -> None:
    """Host ヘッダが whitelist 外なら 400。

    テスト (TESTING=True) では Flask test client が `localhost` を付与するため透過。
    """
    if app.config.get("TESTING"):
        return None
    host = _extract_host_only(request.host).lower()
    if host not in _ALLOWED_HOSTS:
        abort(400, description=f"Invalid Host header: {request.host!r}")


@app.after_request
def _add_security_headers(response):
    """包括レビュー H-4 / G-2: 最低限の Content-Security-Policy を全レスポンスに付与。

    Sprint 007 で pico.css / htmx.org を自前実装化したら CDN host を削除し `'self'` のみに。
    """
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "script-src 'self' https://unpkg.com 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "object-src 'none'",
    )
    # 関連 hardening (本 PR のスコープ内で追加コストがほぼ 0)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


POLICY_PATH = os.environ.get("POLICY_PATH", "/app/policy.toml")


def _policy_path() -> str:
    """env を毎回参照（テストの monkeypatch 対応）。"""
    return os.environ.get("POLICY_PATH", POLICY_PATH)


def _inbox_dir() -> str:
    """env を毎回参照（テストの monkeypatch 対応）。"""
    return os.environ.get("INBOX_DIR", "/inbox")


def _parse_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_db():
    """読み取り専用でSQLiteに接続する。"""
    db_path = os.environ.get("DB_PATH", "/data/harness.db")
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


# === HTML Pages ===


@app.route("/")
def index():
    return render_template("index.html")


# === API Endpoints ===


@app.route("/api/stats")
def api_stats():
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        allowed = db.execute(
            "SELECT COUNT(*) FROM requests WHERE status='ALLOWED'"
        ).fetchone()[0]
        blocked = db.execute(
            f"SELECT COUNT(*) FROM requests WHERE status IN ({_BLOCK_STATUSES_PLACEHOLDERS})",
            _BLOCK_STATUSES,
        ).fetchone()[0]
        tool_uses = db.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0]
        alerts = db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]

        # 直近1分のRPM
        one_min_ago = (datetime.now(UTC) - timedelta(minutes=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        rpm = db.execute(
            "SELECT COUNT(*) FROM requests WHERE ts > ?", (one_min_ago,)
        ).fetchone()[0]

        return jsonify(
            {
                "total_requests": total,
                "allowed": allowed,
                "blocked": blocked,
                "tool_uses": tool_uses,
                "alerts": alerts,
                "rpm": rpm,
            }
        )
    finally:
        db.close()


@app.route("/api/requests")
def api_requests():
    db = get_db()
    try:
        status = request.args.get("status")
        limit = min(_parse_int(request.args.get("limit"), 50), 200)
        offset = _parse_int(request.args.get("offset"), 0)

        if status:
            rows = db.execute(
                "SELECT id, ts, host, method, url, status, body_size "
                "FROM requests WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, ts, host, method, url, status, body_size "
                "FROM requests ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

        return jsonify([dict(r) for r in rows])
    finally:
        db.close()


@app.route("/api/blocks")
def api_blocks():
    db = get_db()
    try:
        limit = min(_parse_int(request.args.get("limit"), 50), 200)
        rows = db.execute(
            "SELECT id, ts, host, reason FROM blocks ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        db.close()


@app.route("/api/tool-uses")
def api_tool_uses():
    db = get_db()
    try:
        limit = min(_parse_int(request.args.get("limit"), 50), 200)
        rows = db.execute(
            "SELECT id, ts, tool_name, input_size FROM tool_uses ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        db.close()


@app.route("/api/alerts")
def api_alerts():
    db = get_db()
    try:
        limit = min(_parse_int(request.args.get("limit"), 50), 200)
        rows = db.execute(
            "SELECT id, ts, type, detail FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        db.close()


@app.route("/api/domains")
def api_domains():
    """ドメイン別の集計。"""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT host, status, COUNT(*) as count "
            "FROM requests GROUP BY host, status ORDER BY count DESC"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        db.close()


# === HTMX Partials ===


@app.route("/partials/requests")
def partial_requests():
    db = get_db()
    try:
        status = request.args.get("status", "").strip()
        if status:
            rows = db.execute(
                "SELECT id, ts, host, url, method, status, body_size "
                "FROM requests WHERE status=? ORDER BY id DESC LIMIT 30",
                (status,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, ts, host, url, method, status, body_size "
                "FROM requests ORDER BY id DESC LIMIT 30"
            ).fetchall()
        # URLからパス部分を抽出
        from urllib.parse import urlparse
        processed = []
        for r in rows:
            d = dict(r)
            try:
                d["path"] = urlparse(d.get("url", "")).path
            except Exception:
                d["path"] = d.get("url", "")
            processed.append(d)
        return render_template("partials/requests.html", rows=processed)
    finally:
        db.close()


@app.route("/partials/stats")
def partial_stats():
    db = get_db()
    try:
        stats = {
            "total": db.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
            "blocked": db.execute(
                f"SELECT COUNT(*) FROM requests WHERE status IN ({_BLOCK_STATUSES_PLACEHOLDERS})",
                _BLOCK_STATUSES,
            ).fetchone()[0],
            "tool_uses": db.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0],
            "alerts": db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0],
        }
        return render_template("partials/stats.html", stats=stats)
    finally:
        db.close()


@app.route("/partials/tool-uses")
def partial_tool_uses():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, ts, tool_name, input, input_size "
            "FROM tool_uses ORDER BY id DESC LIMIT 50"
        ).fetchall()
        return render_template("partials/tool-uses.html", rows=rows)
    finally:
        db.close()


@app.route("/partials/whitelist")
def partial_whitelist():
    import tomllib
    db_path = os.environ.get("DB_PATH", "/data/harness.db")
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    candidates = get_whitelist_candidates(db_path, policy_path)
    # 各候補にブロックされたパスのトップ5を付与
    try:
        db = get_db()
        try:
            for c in candidates:
                rows = db.execute(
                    f"SELECT DISTINCT url FROM requests WHERE host=? AND status IN ({_BLOCK_STATUSES_PLACEHOLDERS}) LIMIT 5",
                    (c["host"], *_BLOCK_STATUSES),
                ).fetchall()
                c["paths"] = [r["url"] for r in rows]
        finally:
            db.close()
    except Exception:
        pass
    # 現在のポリシー設定を取得（base + runtime）
    policy = {}
    runtime = {}
    base_dismissed = {}
    runtime_dismissed = {}
    try:
        with open(policy_path, "rb") as f:
            policy = tomllib.load(f)
        rt_path = _runtime_path(policy_path)
        if os.path.exists(rt_path):
            with open(rt_path, "rb") as f:
                runtime = tomllib.load(f)
        # dismissed: base（手動編集のみ） + runtime（UI操作可能）
        base_dismissed = policy.get("domains", {}).get("dismissed", {})
        runtime_dismissed = runtime.get("domains", {}).get("dismissed", {})
        dismissed = {**base_dismissed, **runtime_dismissed}
    except Exception:
        pass

    # 現在の設定まとめ
    current_policy = {
        "base_allow_domains": policy.get("domains", {}).get("allow", {}).get("list", []),
        "runtime_allow_domains": runtime.get("domains", {}).get("allow", {}).get("list", []),
        "deny_domains": policy.get("domains", {}).get("deny", {}).get("list", []),
        "base_paths_allow": policy.get("paths", {}).get("allow", {}),
        "runtime_paths_allow": runtime.get("paths", {}).get("allow", {}),
        "paths_deny": policy.get("paths", {}).get("deny", {}),
    }

    return render_template(
        "partials/whitelist.html",
        candidates=candidates,
        base_dismissed=base_dismissed,
        runtime_dismissed=runtime_dismissed,
        current_policy=current_policy,
    )


# === Whitelist Nurturing API ===

import re

# 包括レビュー M-5 (Sprint 006 PR D): RFC 1035 準拠の strict regex に置換。
# ラベルごとに leading/trailing hyphen 禁止、1〜63 文字、`*.` wildcard は
# 最後に 2 ラベル以上を強制。`localhost` / `*.com` / `a..com` / `a-.com` / `-a.com`
# / `*.*.example.com` / `example.com.` を全部 reject する。
# 許可 / 拒否の full matrix は tests/test_dashboard_domain_validation.py 参照。
_LABEL_RE = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_DOMAIN_RE = re.compile(rf"^(\*\.)?({_LABEL_RE}\.)+{_LABEL_RE}$")


def _validate_domain(domain: str) -> str | None:
    """ドメイン名のバリデーション。不正なら理由を返す。"""
    if not domain:
        return "domain is required"
    if len(domain) > 253:
        return "domain too long"
    if not _DOMAIN_RE.match(domain):
        return "invalid domain format"
    return None


def _get_json_body() -> dict:
    """JSONまたはフォームデータを取得する（HTMX互換）。"""
    return request.get_json(silent=True) or dict(request.form) or {}


@app.route("/api/whitelist-candidates")
def api_whitelist_candidates():
    db_path = os.environ.get("DB_PATH", "/data/harness.db")
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    candidates = get_whitelist_candidates(db_path, policy_path)
    return jsonify(candidates)


@app.route("/api/whitelist/allow", methods=["POST"])
def api_whitelist_allow():
    body = _get_json_body()
    domain = body.get("domain", "").strip()
    error = _validate_domain(domain)
    if error:
        return jsonify({"error": error}), 400
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    add_to_allow_list(policy_path, domain)
    if request.headers.get("HX-Request"):
        return partial_whitelist()
    return jsonify({"status": "ok", "action": "allowed", "domain": domain})


@app.route("/api/whitelist/allow-path", methods=["POST"])
def api_whitelist_allow_path():
    body = _get_json_body()
    domain = body.get("domain", "").strip()
    path_pattern = body.get("path_pattern", "").strip()
    error = _validate_domain(domain)
    if error:
        return jsonify({"error": error}), 400
    if not path_pattern:
        return jsonify({"error": "path_pattern is required"}), 400
    if not path_pattern.startswith("/"):
        return jsonify({"error": "path_pattern must start with /"}), 400
    if len(path_pattern) > 500:
        return jsonify({"error": "path_pattern too long"}), 400
    if "\n" in path_pattern or "\r" in path_pattern:
        return jsonify({"error": "path_pattern must not contain newlines"}), 400
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    add_to_paths_allow(policy_path, domain, path_pattern)
    if request.headers.get("HX-Request"):
        return partial_whitelist()
    return jsonify({"status": "ok", "action": "path_allowed", "domain": domain, "path_pattern": path_pattern})


@app.route("/api/whitelist/dismiss", methods=["POST"])
def api_whitelist_dismiss():
    body = _get_json_body()
    domain = body.get("domain", "").strip()
    reason = body.get("reason", "").strip()
    error = _validate_domain(domain)
    if error:
        return jsonify({"error": error}), 400
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    add_to_dismissed(policy_path, domain, reason or "dismissed via dashboard")
    if request.headers.get("HX-Request"):
        return partial_whitelist()
    return jsonify({"status": "ok", "action": "dismissed", "domain": domain})


@app.route("/api/whitelist/restore", methods=["POST"])
def api_whitelist_restore():
    body = _get_json_body()
    domain = body.get("domain", "").strip()
    error = _validate_domain(domain)
    if error:
        return jsonify({"error": error}), 400
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    remove_from_dismissed(policy_path, domain)
    if request.headers.get("HX-Request"):
        return partial_whitelist()
    return jsonify({"status": "ok", "action": "restored", "domain": domain})


@app.route("/api/whitelist/revoke-domain", methods=["POST"])
def api_whitelist_revoke_domain():
    body = _get_json_body()
    domain = body.get("domain", "").strip()
    error = _validate_domain(domain)
    if error:
        return jsonify({"error": error}), 400
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    remove_from_allow_list(policy_path, domain)
    if request.headers.get("HX-Request"):
        return partial_whitelist()
    return jsonify({"status": "ok", "action": "revoked", "domain": domain})


@app.route("/api/whitelist/revoke-path", methods=["POST"])
def api_whitelist_revoke_path():
    body = _get_json_body()
    domain = body.get("domain", "").strip()
    path_pattern = body.get("path_pattern", "").strip()
    error = _validate_domain(domain)
    if error:
        return jsonify({"error": error}), 400
    if not path_pattern:
        return jsonify({"error": "path_pattern is required"}), 400
    if not path_pattern.startswith("/"):
        return jsonify({"error": "invalid path_pattern"}), 400
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    remove_from_paths_allow(policy_path, domain, path_pattern)
    if request.headers.get("HX-Request"):
        return partial_whitelist()
    return jsonify({"status": "ok", "action": "revoked", "domain": domain, "path_pattern": path_pattern})


# === Inbox (ADR 0001 A-6) ===


@app.route("/partials/inbox")
def partial_inbox():
    items = inbox_list_requests(_inbox_dir(), status="pending")
    return render_template("partials/inbox.html", items=items)


def _apply_accept(record: dict) -> None:
    """inbox record の type に応じて runtime policy へ反映する。

    self-review M-3: agent が inbox に書いた `value` を validation 無しで
    runtime policy に流すと M-5 の strict regex 防御が UI 経由 (whitelist API)
    でしか効かなくなる。inbox accept でも同じ strict regex を要求する。
    invalid な entry は ValueError を raise し caller (api_inbox_accept /
    api_inbox_bulk_accept) 側で 400 / skip 扱いにする。
    """
    rtype = record.get("type")
    policy_path = _policy_path()
    if rtype == "domain":
        domain = record.get("value", "")
        err = _validate_domain(domain)
        if err:
            raise ValueError(f"invalid inbox domain: {err}")
        add_to_allow_list(policy_path, domain)
    elif rtype == "path":
        domain = record.get("domain", "")
        err = _validate_domain(domain)
        if err:
            raise ValueError(f"invalid inbox domain: {err}")
        add_to_paths_allow(policy_path, domain, record["value"])
    # tool_use_unblock は将来対応（ADR Open / Future）


def _validate_record_id(record_id: str) -> tuple[str, str | None]:
    """record_id を strict 検証（包括レビュー H-2: path traversal 対策）。

    Returns: (cleaned_id, error_message_or_None)
    """
    cleaned = record_id.strip()
    if not cleaned:
        return cleaned, "record_id is required"
    if not _INBOX_RECORD_ID_RE.match(cleaned):
        return cleaned, "invalid record_id"
    return cleaned, None


@app.route("/api/inbox/accept", methods=["POST"])
def api_inbox_accept():
    body = _get_json_body()
    record_id, error = _validate_record_id(body.get("record_id", ""))
    if error:
        return jsonify({"error": error}), 400

    items = inbox_list_requests(_inbox_dir())
    record = next((r for r in items if r["_id"] == record_id), None)
    if record is None:
        return jsonify({"error": "record not found"}), 404

    try:
        _apply_accept(record)
    except ValueError as e:
        # self-review M-3: inbox に書かれた value が strict domain regex を
        # 通らない場合は 400 で拒否（agent が緩い entry を流し込むのを防ぐ）
        return jsonify({"error": str(e)}), 400
    inbox_mark_status(_inbox_dir(), record_id, "accepted")

    if request.headers.get("HX-Request"):
        return partial_inbox()
    return jsonify({"status": "ok", "action": "accepted", "record_id": record_id})


@app.route("/api/inbox/reject", methods=["POST"])
def api_inbox_reject():
    body = _get_json_body()
    record_id, error = _validate_record_id(body.get("record_id", ""))
    if error:
        return jsonify({"error": error}), 400
    reason = body.get("reason", "").strip()
    try:
        inbox_mark_status(
            _inbox_dir(), record_id, "rejected",
            reason or "rejected via dashboard",
        )
    except FileNotFoundError:
        return jsonify({"error": "record not found"}), 404
    except ValueError:
        # policy_inbox 側で更に defense-in-depth の path 検証を行っており、
        # エッジケースで ValueError になった場合も 400 相当として扱う
        return jsonify({"error": "invalid record_id"}), 400

    if request.headers.get("HX-Request"):
        return partial_inbox()
    return jsonify({"status": "ok", "action": "rejected", "record_id": record_id})


def _filter_valid_record_ids(record_ids: list) -> list[str]:
    """list の中から strict regex を満たす record_id のみ返す (H-2 defense-in-depth)。"""
    result = []
    for rid in record_ids:
        if isinstance(rid, str) and _INBOX_RECORD_ID_RE.match(rid.strip()):
            result.append(rid.strip())
    return result


@app.route("/api/inbox/bulk-accept", methods=["POST"])
def api_inbox_bulk_accept():
    body = _get_json_body()
    record_ids = body.get("record_ids", [])
    if not isinstance(record_ids, list):
        return jsonify({"error": "record_ids must be a list"}), 400
    valid_ids = _filter_valid_record_ids(record_ids)

    items = inbox_list_requests(_inbox_dir())
    by_id = {r["_id"]: r for r in items}
    accepted = 0
    for rid in valid_ids:
        record = by_id.get(rid)
        if record is None:
            continue
        try:
            _apply_accept(record)
            inbox_mark_status(_inbox_dir(), rid, "accepted")
            accepted += 1
        except (FileNotFoundError, ValueError, KeyError):
            continue

    if request.headers.get("HX-Request"):
        return partial_inbox()
    return jsonify({"status": "ok", "accepted": accepted})


@app.route("/api/inbox/bulk-reject", methods=["POST"])
def api_inbox_bulk_reject():
    body = _get_json_body()
    record_ids = body.get("record_ids", [])
    if not isinstance(record_ids, list):
        return jsonify({"error": "record_ids must be a list"}), 400
    valid_ids = _filter_valid_record_ids(record_ids)
    n = inbox_bulk_mark_status(_inbox_dir(), valid_ids, "rejected")
    if request.headers.get("HX-Request"):
        return partial_inbox()
    return jsonify({"status": "ok", "rejected": n})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
