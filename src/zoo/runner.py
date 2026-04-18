"""Shared helpers: agent config, subprocess execution, cert generation."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Walk up from CWD to find the agent-zoo repo root (docker-compose.yml + policy.toml)."""
    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "docker-compose.yml").exists() and (candidate / "policy.toml").exists():
            return candidate
    raise SystemExit(
        "agent-zoo のリポジトリルートが見つかりません。"
        "docker-compose.yml と policy.toml のあるディレクトリで実行してください。"
    )


def cert_path() -> Path:
    return repo_root() / "certs" / "mitmproxy-ca-cert.pem"


@dataclass(frozen=True)
class AgentConfig:
    name: str
    required_env: str
    run_hint: str
    run_cmd: list[str]
    run_dangerous_cmd: list[str]
    task_cmd_template: list[str]
    allowed_test_url: str


CLAUDE = AgentConfig(
    name="claude",
    required_env="CLAUDE_CODE_OAUTH_TOKEN",
    run_hint="対話モード: 初回はコンテナ内で /login が必要です",
    run_cmd=[
        "docker", "compose", "exec", "claude",
        "claude", "--append-system-prompt-file", "/harness/CLAUDE.harness.md",
    ],
    run_dangerous_cmd=[
        "docker", "compose", "exec", "claude",
        "claude", "--dangerously-skip-permissions",
        "--append-system-prompt-file", "/harness/CLAUDE.harness.md",
    ],
    task_cmd_template=[
        "docker", "compose", "exec", "claude",
        "claude", "-p", "{prompt}",
        "--dangerously-skip-permissions",
        "--append-system-prompt-file", "/harness/CLAUDE.harness.md",
    ],
    allowed_test_url="https://api.anthropic.com/",
)

CODEX = AgentConfig(
    name="codex",
    required_env="OPENAI_API_KEY",
    run_hint="対話モード: 初回は OPENAI_API_KEY またはコンテナ内で codex login が必要です",
    run_cmd=[
        "docker", "compose", "exec", "codex",
        "/usr/local/bin/run-codex.sh", "interactive",
    ],
    run_dangerous_cmd=[
        "docker", "compose", "exec", "codex",
        "/usr/local/bin/run-codex.sh", "interactive-dangerous",
    ],
    task_cmd_template=[
        "docker", "compose", "exec",
        "-e", "USER_PROMPT={prompt}",
        "codex",
        "/usr/local/bin/run-codex.sh", "task",
    ],
    allowed_test_url="https://api.openai.com/",
)

AGENTS = {"claude": CLAUDE, "codex": CODEX}


def resolve_agent(name: str) -> AgentConfig:
    if name not in AGENTS:
        raise SystemExit(f"Unknown agent: {name}. Choose from: {', '.join(AGENTS)}")
    return AGENTS[name]


def host_uid() -> str:
    return str(os.getuid())


def compose_env(workspace: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["HOST_UID"] = host_uid()
    if workspace:
        env["WORKSPACE"] = workspace
    return env


def run(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True,
        cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess with the repo root as CWD by default."""
    proc_env = env if env is not None else os.environ.copy()
    return subprocess.run(
        cmd,
        env=proc_env,
        cwd=cwd or repo_root(),
        check=check,
    )


def run_interactive(cmd: list[str], *, env: dict[str, str] | None = None) -> int:
    """Run a subprocess that attaches stdin/stdout/stderr (for TTY use)."""
    proc_env = env if env is not None else os.environ.copy()
    try:
        return subprocess.call(cmd, env=proc_env, cwd=repo_root())
    except KeyboardInterrupt:
        return 130


def build_base() -> None:
    """共通 base イメージ `agent-zoo-base:latest` をビルドする（B-1）。

    `container/Dockerfile.base` を使う。各 agent イメージはこれを `FROM` する。
    build context は repo root（D-1: certs/extra/ も取り込むため）。
    """
    root = repo_root()
    base_dockerfile = root / "container" / "Dockerfile.base"
    if not base_dockerfile.exists():
        return
    run([
        "docker", "build",
        "-t", "agent-zoo-base:latest",
        "-f", str(base_dockerfile),
        str(root),
    ], env=compose_env())


def ensure_certs() -> None:
    """Generate mitmproxy CA cert if missing."""
    cert = cert_path()
    if cert.exists():
        return
    print("Generating mitmproxy CA certificate...", file=sys.stderr)
    certs_dir = repo_root() / "certs"
    certs_dir.mkdir(exist_ok=True)
    run([
        "docker", "run", "--rm",
        "-v", f"{certs_dir}:/certs",
        "mitmproxy/mitmproxy:10",
        "sh", "-c", "timeout 5 mitmdump --set confdir=/certs 2>&1 || true",
    ], check=False)
    if not cert.exists():
        raise SystemExit("Failed to generate mitmproxy CA certificate")
    print(f"Certificate generated: {cert}", file=sys.stderr)


def touch_runtime_files() -> None:
    for name in ("policy.runtime.toml", "policy_candidate.toml"):
        (repo_root() / name).touch(exist_ok=True)


def _ensure_inbox_dir(workspace: str | None) -> None:
    """ADR 0001 A-3: workspace 内の `.zoo/inbox/` を作成する。

    docker-compose の bind mount 元 path が事前に存在することを保証する。
    """
    base = Path(workspace) if workspace else (repo_root() / "workspace")
    (base / ".zoo" / "inbox").mkdir(parents=True, exist_ok=True)


def compose_up(services: list[str], *, workspace: str | None = None,
               strict: bool = False) -> None:
    ensure_certs()
    touch_runtime_files()
    _ensure_inbox_dir(workspace)
    env = compose_env(workspace)
    if strict:
        cmd = [
            "docker", "compose", "--profile", "strict",
            "-f", "docker-compose.yml", "-f", "docker-compose.strict.yml",
            "up", "-d", *services,
        ]
    else:
        cmd = ["docker", "compose", "up", "-d", *services]
    run(cmd, env=env)


def require_env(var: str, *, hint: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise SystemExit(f"{var} is required. {hint}")
    return value
