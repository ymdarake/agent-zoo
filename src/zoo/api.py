"""Public Python API for Agent Zoo.

Import as:
    from zoo import run, task, up, down, ...

All functions are plain Python — no typer/rich dependency — so you can use them
from notebooks, other scripts, or custom tooling.

Interactive commands (``run``, ``task``, ``host_start``, ``test_unit``,
``test_smoke``) attach the current process stdio and return a subprocess-style
exit code. Non-interactive commands raise on failure or return structured data.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import runner

_BUNDLED_FILES = [
    "docker-compose.yml",
    "docker-compose.strict.yml",
    "policy.toml",
    "Makefile",
]
_BUNDLED_DIRS = [
    "container",
    "addons",
    "dashboard",
    "templates",
    "host",
    "dns",
]


def _asset_source() -> Path:
    """Locate bundled assets, preferring installed package data, else repo root."""
    try:
        import importlib.resources as resources

        pkg_assets = resources.files("zoo").joinpath("_assets")
        if pkg_assets.is_dir():
            return Path(str(pkg_assets))
    except (ModuleNotFoundError, AttributeError, OSError):
        pass
    return runner.repo_root()


def init(target_dir: str | Path = ".", *, force: bool = False) -> Path:
    """Bootstrap a ready-to-use agent-zoo workspace at ``target_dir``.

    Copies bundled docker-compose / policy / container / addons files into
    the target and creates the empty mount directories (``data/``,
    ``workspace/``, ``certs/``).  Existing files are preserved unless
    ``force=True``.

    Returns the resolved target path.
    """
    target = Path(target_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    source = _asset_source()

    for name in _BUNDLED_FILES:
        src = source / name
        if not src.exists():
            continue
        dst = target / name
        if dst.exists() and not force:
            continue
        shutil.copy2(src, dst)

    for name in _BUNDLED_DIRS:
        src = source / name
        if not src.exists():
            continue
        dst = target / name
        if dst.exists():
            if not force:
                continue
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    for d in ("data", "workspace", "certs"):
        (target / d).mkdir(exist_ok=True)
    (target / "policy.runtime.toml").touch(exist_ok=True)

    return target


def run(
    *,
    agent: str = "claude",
    workspace: str | Path | None = None,
    dangerous: bool = False,
) -> int:
    """Launch an interactive agent session.

    Returns the agent process exit code.
    """
    cfg = runner.resolve_agent(agent)
    runner.compose_up([cfg.name, "dashboard"], workspace=_as_str(workspace))
    cmd = cfg.run_dangerous_cmd if dangerous else cfg.run_cmd
    return runner.run_interactive(cmd)


def task(
    *,
    prompt: str,
    agent: str = "claude",
    workspace: str | Path | None = None,
) -> int:
    """Run a one-shot autonomous task. Auth via the agent's required env var.

    Returns the agent process exit code.
    """
    cfg = runner.resolve_agent(agent)
    runner.require_env(
        cfg.required_env,
        hint=f"Set {cfg.required_env} before calling task().",
    )
    runner.compose_up([cfg.name, "dashboard"], workspace=_as_str(workspace))
    cmd = [arg.replace("{prompt}", prompt) for arg in cfg.task_cmd_template]
    return runner.run_interactive(cmd)


def bash(
    *,
    agent: str = "claude",
    workspace: str | Path | None = None,
) -> int:
    """B-4: Open an interactive bash shell inside the agent container.

    Useful for manual inspection / ad-hoc debugging within the harness.
    """
    cfg = runner.resolve_agent(agent)
    runner.compose_up([cfg.name, "dashboard"], workspace=_as_str(workspace))
    return runner.run_interactive(
        ["docker", "compose", "exec", cfg.name, "bash"],
    )


def up(
    *,
    agent: str = "claude",
    workspace: str | Path | None = None,
    dashboard_only: bool = False,
    strict: bool = False,
) -> None:
    """Start containers without attaching (no exec)."""
    if dashboard_only:
        services = ["proxy", "dashboard"]
    else:
        cfg = runner.resolve_agent(agent)
        services = [cfg.name, "dashboard"]
    runner.compose_up(services, workspace=_as_str(workspace), strict=strict)


def down() -> None:
    """Stop containers (includes strict profile if present)."""
    env = runner.compose_env()
    strict_cmd = [
        "docker", "compose", "--profile", "strict",
        "-f", "docker-compose.yml", "-f", "docker-compose.strict.yml",
        "down",
    ]
    result = subprocess.run(strict_cmd, env=env, cwd=runner.repo_root())
    if result.returncode != 0:
        runner.run(["docker", "compose", "down"], env=env, check=False)


def reload_policy() -> None:
    """Reload policy.toml by restarting proxy + dashboard (clears addon cache)."""
    cache = runner.repo_root() / "addons" / "__pycache__"
    if cache.exists():
        shutil.rmtree(cache)
    runner.run(
        ["docker", "compose", "restart", "proxy", "dashboard"],
        env=runner.compose_env(),
    )


def build(*, agent: str = "claude") -> None:
    """Build docker images for the given agent + dashboard.

    まず共通 base（B-1: `agent-zoo-base:latest`）をビルドし、次に compose build。
    """
    cfg = runner.resolve_agent(agent)
    runner.ensure_certs()
    runner.build_base()
    runner.run(
        ["docker", "compose", "build", cfg.name, "dashboard"],
        env=runner.compose_env(),
    )


def certs() -> None:
    """Generate the mitmproxy CA certificate if missing."""
    runner.ensure_certs()


def host_start() -> int:
    """Start host-mode mitmproxy via host/setup.sh."""
    return runner.run_interactive(["./host/setup.sh"])


def proxy(*, agent: str, agent_args: list[str] | None = None) -> int:
    """D-3: ホスト CLI に zoo proxy 環境を注入して exec する。

    mitmproxy が未起動なら host/setup.sh で起動。env に
    HTTPS_PROXY / HTTP_PROXY / NODE_EXTRA_CA_CERTS / SSL_CERT_FILE / GIT_SSL_CAINFO
    を注入してサブプロセスを実行する。
    """
    pid_file = runner.repo_root() / "data" / ".mitmproxy.pid"
    if not pid_file.exists():
        runner.run_interactive(["./host/setup.sh"])

    cert = runner.cert_path()
    env = os.environ.copy()
    env.update({
        "HTTPS_PROXY": "http://127.0.0.1:8080",
        "HTTP_PROXY": "http://127.0.0.1:8080",
        "NODE_EXTRA_CA_CERTS": str(cert),
        "SSL_CERT_FILE": str(cert),
        "GIT_SSL_CAINFO": str(cert),
    })
    cmd = [agent, *(agent_args or [])]
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 130


def host_stop() -> int:
    """Stop host-mode mitmproxy via host/stop.sh."""
    return runner.run_interactive(["./host/stop.sh"])


def logs_clear() -> bool:
    """Delete harness.db (and WAL/SHM). Returns True if anything was removed."""
    db = runner.repo_root() / "data" / "harness.db"
    if not db.exists():
        return False
    for name in ("harness.db", "harness.db-wal", "harness.db-shm"):
        (runner.repo_root() / "data" / name).unlink(missing_ok=True)
    return True


def logs_analyze() -> int:
    """Pipe block-log summary + policy.toml into ``claude -p`` for analysis."""
    query = (
        "SELECT host, COUNT(*) as n, GROUP_CONCAT(DISTINCT status) as statuses "
        "FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED','PAYLOAD_BLOCKED') "
        "GROUP BY host ORDER BY n DESC"
    )
    policy = (runner.repo_root() / "policy.toml").read_text()
    context = f"=== ブロックログ ===\n\n=== 現在のpolicy.toml ===\n{policy}"
    return _pipe_to_claude(
        query,
        "ブロックログとpolicy.tomlを比較して改善案をTOML形式で提案して。"
        "許可すべきドメインとその理由、危険なドメインとその理由を分けて。",
        extra_context=context,
    )


def logs_summarize() -> int:
    """Pipe recent tool_use log into ``claude -p`` for policy suggestion."""
    query = (
        "SELECT tool_name, input, input_size, ts "
        "FROM tool_uses ORDER BY ts DESC LIMIT 100"
    )
    return _pipe_to_claude(
        query,
        "このtool_use履歴からホストモード用settings.jsonの最小権限設定を提案して",
    )


def logs_alerts() -> int:
    """Pipe recent alerts into ``claude -p`` for review."""
    query = "SELECT * FROM alerts ORDER BY ts DESC LIMIT 50"
    return _pipe_to_claude(query, "セキュリティ上の懸念があるパターンを報告して")


def test_unit() -> int:
    """Run the project's pytest suite."""
    return runner.run_interactive(
        ["uv", "run", "python", "-m", "pytest", "tests/", "-v"],
    )


def test_smoke(*, agent: str = "claude") -> int:
    """Run the Docker smoke test (delegates to Makefile)."""
    env = runner.compose_env()
    env["AGENT"] = agent
    return subprocess.call(
        ["make", "test", f"AGENT={agent}"],
        env=env,
        cwd=runner.repo_root(),
    )


# --- internal helpers --------------------------------------------------------

def _as_str(value: str | Path | None) -> str | None:
    return str(value) if value is not None else None


def _pipe_to_claude(sqlite_query: str, prompt: str, *, extra_context: str = "") -> int:
    """Run ``sqlite3 ... | claude -p PROMPT``. Returns the claude exit code."""
    db_path = runner.repo_root() / "data" / "harness.db"
    if not db_path.exists():
        raise FileNotFoundError(
            "data/harness.db が見つかりません。先にエージェントを実行してください。"
        )
    sqlite = subprocess.Popen(
        ["sqlite3", str(db_path), "-json", sqlite_query],
        stdout=subprocess.PIPE,
    )
    try:
        if extra_context:
            data = sqlite.stdout.read()  # type: ignore[union-attr]
            sqlite.wait()
            input_bytes = (extra_context + "\n" + data.decode()).encode()
            claude = subprocess.Popen(["claude", "-p", prompt], stdin=subprocess.PIPE)
            claude.stdin.write(input_bytes)  # type: ignore[union-attr]
            claude.stdin.close()
            return claude.wait()
        claude = subprocess.Popen(["claude", "-p", prompt], stdin=sqlite.stdout)
        sqlite.stdout.close()  # type: ignore[union-attr]
        return claude.wait()
    finally:
        sqlite.wait()
