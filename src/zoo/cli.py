"""Agent Zoo CLI — `zoo` command. Thin typer wrapper around :mod:`zoo.api`."""
from __future__ import annotations

import os
import sys
from typing import Optional

import typer

from . import api

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
    ws = workspace or os.environ.get("WORKSPACE", "./workspace")
    if dangerous:
        typer.echo(f"箱庭モード: 承認なし自律実行（ネットワーク隔離で保護） (AGENT={agent}, WORKSPACE={ws})")
    else:
        from .runner import resolve_agent
        typer.echo(f"{resolve_agent(agent).run_hint} (AGENT={agent}, WORKSPACE={ws})")
    sys.exit(api.run(agent=agent, workspace=workspace, dangerous=dangerous))


@app.command()
def task(
    prompt: str = typer.Option(..., "--prompt", "-p", help="エージェントに渡すプロンプト"),
    agent: str = AgentOpt,
    workspace: Optional[str] = WorkspaceOpt,
) -> None:
    """自律実行（非対話）。認証は環境変数で渡す。"""
    sys.exit(api.task(prompt=prompt, agent=agent, workspace=workspace))


# === ライフサイクル ===

@app.command()
def up(
    agent: str = AgentOpt,
    workspace: Optional[str] = WorkspaceOpt,
    dashboard_only: bool = typer.Option(False, "--dashboard-only", help="proxy と dashboard のみ"),
    strict: bool = typer.Option(False, "--strict", help="CoreDNS strict モード"),
) -> None:
    """コンテナを起動（起動のみ、exec しない）。"""
    api.up(agent=agent, workspace=workspace, dashboard_only=dashboard_only, strict=strict)


@app.command()
def down() -> None:
    """コンテナ停止（strict プロファイルも含む）。"""
    api.down()


@app.command()
def reload() -> None:
    """policy.toml を反映（proxy と dashboard を再起動）。"""
    api.reload_policy()
    typer.echo("policy.toml reloaded (cache cleared)")


@app.command()
def build(agent: str = AgentOpt) -> None:
    """Docker イメージをビルド。"""
    api.build(agent=agent)


@app.command(name="bash")
def bash_cmd(
    agent: str = AgentOpt,
    workspace: Optional[str] = WorkspaceOpt,
) -> None:
    """コンテナ内に対話 bash を開く（手動操作・調査用、B-4）。"""
    sys.exit(api.bash(agent=agent, workspace=workspace))


@app.command(
    name="proxy",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def proxy_cmd(
    ctx: typer.Context,
    agent: str = typer.Argument(..., help="実行するコマンド (claude / codex / gemini など)"),
) -> None:
    """ホスト CLI に zoo proxy 環境を注入して exec（D-3）。

    例: `zoo proxy claude -p "テスト追加"`
    """
    sys.exit(api.proxy(agent=agent, agent_args=ctx.args))


@app.command()
def certs() -> None:
    """mitmproxy CA 証明書を生成（既に存在すれば何もしない）。"""
    api.certs()


@app.command()
def init(
    target: str = typer.Argument(".", help="ワークスペースを展開するディレクトリ"),
    force: bool = typer.Option(False, "--force", "-f", help="既存ファイルを上書き"),
) -> None:
    """パッケージ同梱のアセットから agent-zoo ワークスペースを展開。"""
    resolved = api.init(target_dir=target, force=force)
    typer.echo(f"Workspace ready: {resolved}")
    typer.echo("")
    typer.echo("Next steps:")
    typer.echo(f"  cd {resolved}")
    typer.echo("  zoo build              # claude image を build (5〜10 min、初回)")
    typer.echo("")
    typer.echo("Run modes (default agent: claude、--agent codex|gemini で切替可):")
    typer.echo("  zoo run                # 対話モード (初回 /login で OAuth)")
    typer.echo("                         #   → CLAUDE.md + system prompt 両方に HARNESS_RULES 注入")
    typer.echo("  zoo run --dangerous    # 箱庭モード (承認なし自律、network 隔離で保護)")
    typer.echo("  zoo task '<指示>'      # 自律 1-shot (要 CLAUDE_CODE_OAUTH_TOKEN env)")
    typer.echo("  zoo bash               # container 内 bash (調査・手動操作用)")
    typer.echo("                         #   → CLAUDE.md は inject 済、system prompt は手動付与可")
    typer.echo("")
    typer.echo("Operations:")
    typer.echo("  zoo up --dashboard-only  # http://127.0.0.1:8080 で監査 dashboard 起動")
    typer.echo("  zoo down                 # 全コンテナ停止")
    typer.echo("  zoo reload               # policy.toml 変更後の reload")
    typer.echo("  zoo logs analyze         # 蓄積ログを AI 分析 (要 host claude CLI)")


# === ホストモード ===

host_app = typer.Typer(help="ホストモード（Docker を使わずローカルで mitmproxy を起動）", no_args_is_help=True)
app.add_typer(host_app, name="host")


@host_app.command("start")
def host_start() -> None:
    """ホストモードを起動。"""
    sys.exit(api.host_start())


@host_app.command("stop")
def host_stop() -> None:
    """ホストモードを停止。"""
    sys.exit(api.host_stop())


# === ログ ===

logs_app = typer.Typer(help="ログ操作（閲覧・分析・クリア）", no_args_is_help=True)
app.add_typer(logs_app, name="logs")


@logs_app.command("clear")
def logs_clear() -> None:
    """harness.db を削除（WAL/SHM 含む）。"""
    if api.logs_clear():
        typer.echo("Logs cleared (DB + WAL/SHM removed)")
    else:
        typer.echo("No log database found")


@logs_app.command("analyze")
def logs_analyze() -> None:
    """ブロックログと policy.toml を比較して改善案を生成（ホスト側 claude CLI 必須）。"""
    try:
        sys.exit(api.logs_analyze())
    except FileNotFoundError as e:
        raise SystemExit(str(e))


@logs_app.command("summarize")
def logs_summarize() -> None:
    """tool_use 履歴からホストモード用の最小権限設定を提案。"""
    try:
        sys.exit(api.logs_summarize())
    except FileNotFoundError as e:
        raise SystemExit(str(e))


@logs_app.command("alerts")
def logs_alerts() -> None:
    """セキュリティアラートを分析。"""
    try:
        sys.exit(api.logs_alerts())
    except FileNotFoundError as e:
        raise SystemExit(str(e))


# === テスト ===

test_app = typer.Typer(help="テスト実行", no_args_is_help=True)
app.add_typer(test_app, name="test")


@test_app.command("unit")
def test_unit() -> None:
    """ユニットテストを実行（pytest）。"""
    sys.exit(api.test_unit())


if __name__ == "__main__":
    app()
