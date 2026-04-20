"""Shared helpers: agent config, subprocess execution, cert generation."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def workspace_root() -> Path:
    """Workspace root を CWD から walk-up で検出（ADR 0002 D4）。

    `.zoo/docker-compose.yml` を見つけたらその親を返す。
    """
    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".zoo" / "docker-compose.yml").exists():
            return candidate
    raise SystemExit(
        "agent-zoo の workspace root が見つかりません。"
        " `.zoo/docker-compose.yml` のあるディレクトリで実行してください。"
        " `zoo init <dir>` で workspace を生成できます。"
    )


@lru_cache(maxsize=1)
def zoo_dir() -> Path:
    """zoo の管理ファイル (.zoo/) ディレクトリ（ADR 0002 D4）。"""
    return workspace_root() / ".zoo"


def cert_path() -> Path:
    return zoo_dir() / "certs" / "mitmproxy-ca-cert.pem"


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
        "claude", "--append-system-prompt-file", "/harness/HARNESS_RULES.md",
    ],
    run_dangerous_cmd=[
        "docker", "compose", "exec", "claude",
        "claude", "--dangerously-skip-permissions",
        "--append-system-prompt-file", "/harness/HARNESS_RULES.md",
    ],
    task_cmd_template=[
        "docker", "compose", "exec", "claude",
        "claude", "-p", "{prompt}",
        "--dangerously-skip-permissions",
        "--append-system-prompt-file", "/harness/HARNESS_RULES.md",
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

GEMINI = AgentConfig(
    name="gemini",
    required_env="GEMINI_API_KEY",
    run_hint="対話モード: 初回は GEMINI_API_KEY 設定または OAuth フローが必要です",
    run_cmd=[
        "docker", "compose", "exec", "gemini",
        "gemini",
    ],
    run_dangerous_cmd=[
        "docker", "compose", "exec", "gemini",
        "gemini", "--yolo",
    ],
    task_cmd_template=[
        "docker", "compose", "exec", "gemini",
        "gemini", "--yolo", "-p", "{prompt}",
    ],
    allowed_test_url="https://generativelanguage.googleapis.com/",
)

AGENTS = {"claude": CLAUDE, "codex": CODEX, "gemini": GEMINI}


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
    """Run a subprocess with `.zoo/` as CWD by default (ADR 0002)."""
    proc_env = env if env is not None else os.environ.copy()
    return subprocess.run(
        cmd,
        env=proc_env,
        cwd=cwd or zoo_dir(),
        check=check,
    )


def run_interactive(cmd: list[str], *, env: dict[str, str] | None = None) -> int:
    """Run a subprocess that attaches stdin/stdout/stderr (for TTY use)."""
    proc_env = env if env is not None else os.environ.copy()
    try:
        return subprocess.call(cmd, env=proc_env, cwd=zoo_dir())
    except KeyboardInterrupt:
        return 130


def build_base() -> None:
    """共通 base イメージ `agent-zoo-base:latest` をビルドする（B-1）。

    `container/Dockerfile.base` を使う。各 agent イメージはこれを `FROM` する。
    build context は zoo_dir（D-1: certs/extra/ も取り込むため）。
    """
    zoo = zoo_dir()
    base_dockerfile = zoo / "container" / "Dockerfile.base"
    if not base_dockerfile.exists():
        return
    run([
        "docker", "build",
        "-t", "agent-zoo-base:latest",
        "-f", str(base_dockerfile),
        str(zoo),
    ], env=compose_env())


def ensure_certs() -> None:
    """Generate mitmproxy CA cert if missing."""
    cert = cert_path()
    if cert.exists():
        return
    print("Generating mitmproxy CA certificate...", file=sys.stderr)
    certs_dir = zoo_dir() / "certs"
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
    (zoo_dir() / "policy.runtime.toml").touch(exist_ok=True)


def _ensure_inbox_dir(workspace: str | None) -> None:
    """ADR 0001 A-3 + ADR 0002: workspace 内 `.zoo/inbox/` を作成。"""
    base = Path(workspace) if workspace else workspace_root()
    (base / ".zoo" / "inbox").mkdir(parents=True, exist_ok=True)


def ensure_agent_images_built(services: list[str]) -> None:
    """Pre-check that locally-built agent-zoo images exist before `docker compose up`.

    agent-zoo images (``agent-zoo-base`` / ``agent-zoo-<agent>``) are built
    locally by ``zoo build`` and are **not** available on any registry.
    Without this check, compose would attempt to pull from Docker Hub and
    fail with a cryptic ``pull access denied`` error.

    Fail-fast with an English hint pointing at ``zoo build --agent <name>``
    so maintainers / new users don't waste time debugging the pull failure.

    Args:
        services: compose service names (e.g. ``["claude"]`` or
            ``["proxy", "dashboard"]``). Only services in :data:`AGENTS`
            trigger per-agent image checks; other services are assumed to
            use external images (proxy / dashboard / dns) and are skipped.
    """
    agent_services = [s for s in services if s in AGENTS]
    required = ["agent-zoo-base:latest"]
    for svc in agent_services:
        required.append(f"agent-zoo-{svc}:latest")

    missing: list[str] = []
    for img in required:
        result = subprocess.run(
            ["docker", "image", "inspect", img],
            capture_output=True,
        )
        if result.returncode != 0:
            missing.append(img)

    if not missing:
        return

    # English hint: `zoo build --agent <name>` で直る
    agent_hint = agent_services[0] if agent_services else "<agent>"
    lines = [
        "",
        f"::error::Docker image not found locally: {', '.join(missing)}",
        "",
        "agent-zoo images are built locally (not pulled from a registry).",
        f"Run `zoo build --agent {agent_hint}` first (initial build takes a few minutes).",
        "",
    ]
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(1)


def compose_up(services: list[str], *, workspace: str | None = None,
               strict: bool = False) -> None:
    ensure_agent_images_built(services)
    ensure_certs()
    touch_runtime_files()
    _ensure_inbox_dir(workspace)
    env = compose_env(workspace)
    # ADR 0002: workspace 指定時はその `.zoo/` を compose の cwd に
    # （`../:/workspace` mount が指定 path を指すように）
    cwd = (Path(workspace) / ".zoo") if workspace else None
    if strict:
        cmd = [
            "docker", "compose", "--profile", "strict",
            "-f", "docker-compose.yml", "-f", "docker-compose.strict.yml",
            "up", "-d", *services,
        ]
    else:
        cmd = ["docker", "compose", "up", "-d", *services]
    run(cmd, env=env, cwd=cwd)


def require_env(var: str, *, hint: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise SystemExit(f"{var} is required. {hint}")
    return value
