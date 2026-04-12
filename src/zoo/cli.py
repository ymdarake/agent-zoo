"""Agent Zoo CLI — `zoo` command.

Subcommand map:
    zoo run            対話モード起動
    zoo task           自律実行（非対話）
    zoo up             サービスだけ起動
    zoo down           サービス停止
    zoo reload         policy.toml を反映
    zoo build          Dockerイメージビルド
    zoo certs          CA証明書生成
    zoo host start|stop   ホストモード
    zoo logs ...       ログ操作（clear/analyze/summarize/alerts/candidates）
    zoo test unit|smoke   テスト
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Optional

import typer

from . import runner
from .runner import compose_env, compose_up, ensure_certs, repo_root, require_env, resolve_agent, run

app = typer.Typer(
    help="Agent Zoo — AIコーディングエージェント用セキュリティハーネス",
    no_args_is_help=True,
    add_completion=False,
)

AgentOpt = typer.Option("claude", "--agent", "-a", help="エージェント種別 (claude|codex)")
WorkspaceOpt = typer.Option(None, "--workspace", "-w", help="マウントするワークスペースパス（環境変数 WORKSPACE より優先）")


# === 実行系 ===

@app.command(name="run")
def run_cmd(
    agent: str = AgentOpt,
    workspace: Optional[str] = WorkspaceOpt,
    dangerous: bool = typer.Option(False, "--dangerous", help="承認なし（箱庭モード）"),
) -> None:
    """対話モードでエージェントを起動。"""
    cfg = resolve_agent(agent)
    compose_up([cfg.name, "dashboard"], workspace=workspace)
    ws = workspace or os.environ.get("WORKSPACE", "./workspace")
    if dangerous:
        typer.echo(f"箱庭モード: 承認なし自律実行（ネットワーク隔離で保護） (AGENT={cfg.name}, WORKSPACE={ws})")
        cmd = cfg.run_dangerous_cmd
    else:
        typer.echo(f"{cfg.run_hint} (AGENT={cfg.name}, WORKSPACE={ws})")
        cmd = cfg.run_cmd
    sys.exit(runner.run_interactive(cmd))


@app.command()
def task(
    prompt: str = typer.Option(..., "--prompt", "-p", help="エージェントに渡すプロンプト"),
    agent: str = AgentOpt,
    workspace: Optional[str] = WorkspaceOpt,
) -> None:
    """自律実行（非対話）。認証は環境変数で渡す。"""
    cfg = resolve_agent(agent)
    require_env(
        cfg.required_env,
        hint=f"Usage: {cfg.required_env}=xxx zoo task --agent {cfg.name} -p \"...\"",
    )
    compose_up([cfg.name, "dashboard"], workspace=workspace)
    cmd = [arg.replace("{prompt}", prompt) for arg in cfg.task_cmd_template]
    sys.exit(runner.run_interactive(cmd))


# === ライフサイクル ===

@app.command()
def up(
    agent: str = AgentOpt,
    workspace: Optional[str] = WorkspaceOpt,
    dashboard_only: bool = typer.Option(False, "--dashboard-only", help="proxy と dashboard のみ"),
    strict: bool = typer.Option(False, "--strict", help="CoreDNS strict モード"),
) -> None:
    """コンテナを起動（起動のみ、exec しない）。"""
    if dashboard_only:
        compose_up(["proxy", "dashboard"], workspace=workspace, strict=strict)
    else:
        cfg = resolve_agent(agent)
        compose_up([cfg.name, "dashboard"], workspace=workspace, strict=strict)


@app.command()
def down() -> None:
    """コンテナ停止（strict プロファイルも含む）。"""
    env = compose_env()
    cmd_strict = [
        "docker", "compose", "--profile", "strict",
        "-f", "docker-compose.yml", "-f", "docker-compose.strict.yml",
        "down",
    ]
    result = subprocess.run(cmd_strict, env=env, cwd=repo_root())
    if result.returncode != 0:
        run(["docker", "compose", "down"], env=env, check=False)


@app.command()
def reload() -> None:
    """policy.toml を反映（proxy と dashboard を再起動）。"""
    cache = repo_root() / "addons" / "__pycache__"
    if cache.exists():
        shutil.rmtree(cache)
    run(["docker", "compose", "restart", "proxy", "dashboard"], env=compose_env())
    typer.echo("policy.toml reloaded (cache cleared)")


@app.command()
def build(agent: str = AgentOpt) -> None:
    """Docker イメージをビルド。"""
    cfg = resolve_agent(agent)
    ensure_certs()
    run(["docker", "compose", "build", cfg.name, "dashboard"], env=compose_env())


@app.command()
def certs() -> None:
    """mitmproxy CA 証明書を生成（既に存在すれば何もしない）。"""
    ensure_certs()


# === ホストモード ===

host_app = typer.Typer(help="ホストモード（Docker を使わずローカルで mitmproxy を起動）", no_args_is_help=True)
app.add_typer(host_app, name="host")


@host_app.command("start")
def host_start() -> None:
    """ホストモードを起動。"""
    sys.exit(runner.run_interactive(["./host/setup.sh"]))


@host_app.command("stop")
def host_stop() -> None:
    """ホストモードを停止。"""
    sys.exit(runner.run_interactive(["./host/stop.sh"]))


# === ログ ===

logs_app = typer.Typer(help="ログ操作（閲覧・分析・クリア）", no_args_is_help=True)
app.add_typer(logs_app, name="logs")


@logs_app.command("clear")
def logs_clear() -> None:
    """harness.db を削除（WAL/SHM 含む）。"""
    db = repo_root() / "data" / "harness.db"
    if not db.exists():
        typer.echo("No log database found")
        return
    for name in ("harness.db", "harness.db-wal", "harness.db-shm"):
        p = repo_root() / "data" / name
        p.unlink(missing_ok=True)
    typer.echo("Logs cleared (DB + WAL/SHM removed)")


def _pipe_to_claude(sqlite_query: str, prompt: str, *, extra_context: str = "") -> None:
    """sqlite3 の出力を claude -p に流す。"""
    db_path = repo_root() / "data" / "harness.db"
    if not db_path.exists():
        raise SystemExit("data/harness.db が見つかりません。先にエージェントを実行してください。")
    sqlite = subprocess.Popen(
        ["sqlite3", str(db_path), "-json", sqlite_query],
        stdout=subprocess.PIPE,
    )
    assert sqlite.stdout is not None
    if extra_context:
        # sqlite の出力の前後に文脈を足す場合
        data = sqlite.stdout.read()
        sqlite.wait()
        input_bytes = (extra_context + "\n" + data.decode()).encode()
        claude = subprocess.Popen(
            ["claude", "-p", prompt],
            stdin=subprocess.PIPE,
        )
        assert claude.stdin is not None
        claude.stdin.write(input_bytes)
        claude.stdin.close()
        sys.exit(claude.wait())
    else:
        claude = subprocess.Popen(["claude", "-p", prompt], stdin=sqlite.stdout)
        sqlite.stdout.close()
        sys.exit(claude.wait())


@logs_app.command("analyze")
def logs_analyze() -> None:
    """ブロックログと policy.toml を比較して改善案を生成（ホスト側 claude CLI 必須）。"""
    query = (
        "SELECT host, COUNT(*) as n, GROUP_CONCAT(DISTINCT status) as statuses "
        "FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED','PAYLOAD_BLOCKED') "
        "GROUP BY host ORDER BY n DESC"
    )
    policy = (repo_root() / "policy.toml").read_text()
    context = f"=== ブロックログ ===\n\n=== 現在のpolicy.toml ===\n{policy}"
    _pipe_to_claude(
        query,
        "ブロックログとpolicy.tomlを比較して改善案をTOML形式で提案して。許可すべきドメインとその理由、危険なドメインとその理由を分けて。",
        extra_context=context,
    )


@logs_app.command("summarize")
def logs_summarize() -> None:
    """tool_use 履歴からホストモード用の最小権限設定を提案。"""
    query = "SELECT tool_name, input, input_size, ts FROM tool_uses ORDER BY ts DESC LIMIT 100"
    _pipe_to_claude(
        query,
        "このtool_use履歴からホストモード用settings.jsonの最小権限設定を提案して",
    )


@logs_app.command("alerts")
def logs_alerts() -> None:
    """セキュリティアラートを分析。"""
    query = "SELECT * FROM alerts ORDER BY ts DESC LIMIT 50"
    _pipe_to_claude(query, "セキュリティ上の懸念があるパターンを報告して")


@logs_app.command("candidates")
def logs_candidates() -> None:
    """policy_candidate.toml に溜まったホワイトリスト候補を一覧表示。"""
    import tomllib

    candidate_file = repo_root() / "policy_candidate.toml"
    if not candidate_file.exists():
        typer.echo("0 candidate(s)")
        return
    try:
        data = tomllib.loads(candidate_file.read_text())
    except Exception as e:
        raise SystemExit(f"Parse error: {e}")
    candidates = data.get("candidates", [])
    typer.echo(f"{len(candidates)} candidate(s)")
    for c in candidates:
        typer.echo(f"  [{c.get('type','?')}] {c.get('value','?')} - {c.get('reason','')}")


# === テスト ===

test_app = typer.Typer(help="テスト実行", no_args_is_help=True)
app.add_typer(test_app, name="test")


@test_app.command("unit")
def test_unit() -> None:
    """ユニットテストを実行（pytest）。"""
    sys.exit(runner.run_interactive(["uv", "run", "python", "-m", "pytest", "tests/", "-v"]))


@test_app.command("smoke")
def test_smoke(agent: str = AgentOpt) -> None:
    """Docker スモークテスト。まだ Makefile 実装に委譲（複雑なため）。"""
    env = compose_env()
    env["AGENT"] = agent
    sys.exit(subprocess.call(["make", "test", f"AGENT={agent}"], env=env, cwd=repo_root()))


if __name__ == "__main__":
    app()
