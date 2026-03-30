"""Agent Harness Dashboard - Flask + HTMX application."""

import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta

from flask import Flask, jsonify, render_template, request

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
    add_to_allow_list,
    add_to_dismissed,
    get_whitelist_candidates,
    remove_from_dismissed,
)

app = Flask(__name__)

POLICY_PATH = os.environ.get("POLICY_PATH", "/app/policy.toml")


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
            "SELECT COUNT(*) FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED','PAYLOAD_BLOCKED')"
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
        rows = db.execute(
            "SELECT id, ts, host, url, method, status, body_size "
            "FROM requests ORDER BY id DESC LIMIT 30"
        ).fetchall()
        return render_template("partials/requests.html", rows=rows)
    finally:
        db.close()


@app.route("/partials/stats")
def partial_stats():
    db = get_db()
    try:
        stats = {
            "total": db.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
            "blocked": db.execute(
                "SELECT COUNT(*) FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED','PAYLOAD_BLOCKED')"
            ).fetchone()[0],
            "tool_uses": db.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0],
            "alerts": db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0],
        }
        return render_template("partials/stats.html", stats=stats)
    finally:
        db.close()


@app.route("/partials/whitelist")
def partial_whitelist():
    import tomllib
    db_path = os.environ.get("DB_PATH", "/data/harness.db")
    policy_path = os.environ.get("POLICY_PATH", "/app/policy.toml")
    candidates = get_whitelist_candidates(db_path, policy_path)
    # dismissed一覧を取得
    dismissed = {}
    try:
        with open(policy_path, "rb") as f:
            policy = tomllib.load(f)
        dismissed = policy.get("domains", {}).get("dismissed", {})
    except Exception:
        pass
    return render_template("partials/whitelist.html", candidates=candidates, dismissed=dismissed)


# === Whitelist Nurturing API ===

import re

_DOMAIN_RE = re.compile(r"^(\*\.)?[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$")


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
    """request.jsonがNoneの場合に安全にハンドルする。"""
    return request.get_json(silent=True) or {}


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
