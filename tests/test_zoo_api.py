"""Tests for the public Python API in zoo.api (subprocess mocked)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import zoo
from zoo import api, runner


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend tmp_path is the agent-zoo repo root."""
    (tmp_path / "docker-compose.yml").write_text("")
    (tmp_path / "policy.toml").write_text("")
    (tmp_path / "data").mkdir()
    (tmp_path / "certs").mkdir()
    (tmp_path / "certs" / "mitmproxy-ca-cert.pem").write_text("fake-cert")
    monkeypatch.chdir(tmp_path)
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    runner.repo_root.cache_clear()
    yield tmp_path
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    runner.repo_root.cache_clear()


class TestPublicExports:
    def test_api_functions_exposed_at_package_root(self) -> None:
        for name in (
            "run", "task", "up", "down", "reload_policy", "build", "certs",
            "host_start", "host_stop", "logs_clear",
            "logs_analyze", "logs_summarize", "logs_alerts",
            "test_unit", "test_smoke",
            "bash",  # B-4
        ):
            assert hasattr(zoo, name), f"zoo.{name} missing"
            assert callable(getattr(zoo, name))


class TestProxy:
    """D-3: ホスト CLI に zoo proxy 環境を注入して exec。"""

    def test_proxy_starts_mitmproxy_if_not_running(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        host_calls: list[list[str]] = []
        sub_calls: list[list[str]] = []

        def fake_interactive(cmd, **kw):
            host_calls.append(cmd)
            return 0

        def fake_subcall(cmd, **kw):
            sub_calls.append(cmd)
            return 0

        # cert を用意（NODE_EXTRA_CA_CERTS の env 注入で使う）
        (repo_root / "certs" / "mitmproxy-ca-cert.pem").write_text("x")
        monkeypatch.setattr(runner, "run_interactive", fake_interactive)
        import subprocess as sp_mod
        monkeypatch.setattr(sp_mod, "call", fake_subcall)

        rc = api.proxy(agent="claude", agent_args=["-p", "hi"])
        assert rc == 0
        # mitmproxy 未起動だったので host/setup.sh が呼ばれる
        assert any("setup.sh" in str(c) for c in host_calls)
        # subprocess.call で claude が exec される
        assert sub_calls[0][0] == "claude"
        assert "-p" in sub_calls[0]

    def test_proxy_skips_setup_when_mitmproxy_running(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repo_root / "certs" / "mitmproxy-ca-cert.pem").write_text("x")
        # PID ファイルを置いて「起動済み」と擬装
        (repo_root / "data" / ".mitmproxy.pid").write_text("99999")

        host_calls: list[list[str]] = []
        sub_calls: list[list[str]] = []

        monkeypatch.setattr(
            runner, "run_interactive",
            lambda cmd, **kw: host_calls.append(cmd) or 0,
        )
        import subprocess as sp_mod
        monkeypatch.setattr(
            sp_mod, "call", lambda cmd, **kw: sub_calls.append(cmd) or 0,
        )

        api.proxy(agent="codex", agent_args=[])
        assert host_calls == []  # 起動済みなので setup.sh は呼ばれない
        assert sub_calls[0][0] == "codex"


class TestBash:
    """B-4: コンテナ内に bash シェルを開く。"""

    def test_invokes_compose_up_then_exec_bash(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compose_up_called: list[tuple] = []
        exec_called: list[list[str]] = []

        monkeypatch.setattr(
            runner, "compose_up",
            lambda services, **kw: compose_up_called.append((tuple(services), kw)),
        )
        monkeypatch.setattr(
            runner, "run_interactive",
            lambda cmd, **kw: exec_called.append(cmd) or 0,
        )

        rc = api.bash(agent="claude")
        assert rc == 0
        assert compose_up_called[0][0] == ("claude", "dashboard")
        assert exec_called[0][:5] == ["docker", "compose", "exec", "claude", "bash"]


class TestLogsClear:
    def test_returns_false_when_no_db(self, repo_root: Path) -> None:
        assert api.logs_clear() is False

    def test_removes_db_and_returns_true(self, repo_root: Path) -> None:
        data_dir = repo_root / "data"
        (data_dir / "harness.db").write_text("x")
        (data_dir / "harness.db-wal").write_text("x")
        (data_dir / "harness.db-shm").write_text("x")

        assert api.logs_clear() is True
        assert not (data_dir / "harness.db").exists()
        assert not (data_dir / "harness.db-wal").exists()
        assert not (data_dir / "harness.db-shm").exists()


class TestComposeUpInbox:
    """ADR 0001 A-3: compose_up は workspace 内 .zoo/inbox/ を確実に作成する。"""

    def test_creates_inbox_dir_under_explicit_workspace(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = repo_root / "ws"
        ws.mkdir()
        monkeypatch.setattr(runner, "run", lambda *a, **k: None)
        runner.compose_up(["claude"], workspace=str(ws))
        assert (ws / ".zoo" / "inbox").is_dir()

    def test_creates_inbox_dir_for_default_workspace(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "run", lambda *a, **k: None)
        runner.compose_up(["claude"])
        assert (repo_root / "workspace" / ".zoo" / "inbox").is_dir()


class TestBuildBase:
    """B-1: Dockerfile.base を独立ビルドするヘルパー。"""

    def test_build_base_invokes_docker_build(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 必要な Dockerfile.base が存在することを fixture に追加
        container = repo_root / "container"
        container.mkdir(exist_ok=True)
        (container / "Dockerfile.base").write_text("FROM node:20-slim\n")
        calls: list[list[str]] = []
        monkeypatch.setattr(runner, "run", lambda cmd, **kw: calls.append(cmd))

        runner.build_base()

        assert any(
            "docker" == c[0] and "build" in c and "agent-zoo-base:latest" in " ".join(c)
            for c in calls
        )

    def test_build_includes_base_then_compose(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """api.build は base → compose build の順で呼ぶ。"""
        container = repo_root / "container"
        container.mkdir(exist_ok=True)
        (container / "Dockerfile.base").write_text("FROM node:20-slim\n")
        (repo_root / "certs" / "mitmproxy-ca-cert.pem").write_text("x")
        calls: list[list[str]] = []
        monkeypatch.setattr(runner, "run", lambda cmd, **kw: calls.append(cmd))

        api.build(agent="claude")

        # 1番目: base ビルド, 2番目: compose build
        assert any("agent-zoo-base:latest" in " ".join(c) for c in calls)
        assert any("compose" in c and "build" in c for c in calls)


class TestRun:
    def test_invokes_compose_up_and_interactive(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []

        def fake_compose_up(services, **kwargs) -> None:
            calls.append(["compose_up", *services])

        def fake_interactive(cmd, **kwargs) -> int:
            calls.append(["interactive", *cmd])
            return 0

        monkeypatch.setattr(runner, "compose_up", fake_compose_up)
        monkeypatch.setattr(runner, "run_interactive", fake_interactive)

        assert api.run(agent="claude") == 0
        assert calls[0] == ["compose_up", "claude", "dashboard"]
        assert calls[1][0] == "interactive"
        assert "claude" in calls[1]

    def test_dangerous_flag_selects_dangerous_cmd(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, list[str]] = {}

        monkeypatch.setattr(runner, "compose_up", lambda *a, **kw: None)

        def fake_interactive(cmd, **kwargs) -> int:
            captured["cmd"] = list(cmd)
            return 0

        monkeypatch.setattr(runner, "run_interactive", fake_interactive)

        api.run(agent="claude", dangerous=True)
        assert "--dangerously-skip-permissions" in captured["cmd"]


class TestTask:
    def test_requires_env_var(self, repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        with pytest.raises(SystemExit):
            api.task(prompt="hello", agent="claude")

    def test_substitutes_prompt(self, repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
        monkeypatch.setattr(runner, "compose_up", lambda *a, **kw: None)

        captured: dict[str, list[str]] = {}

        def fake_interactive(cmd, **kwargs) -> int:
            captured["cmd"] = list(cmd)
            return 0

        monkeypatch.setattr(runner, "run_interactive", fake_interactive)

        api.task(prompt="add tests", agent="claude")
        assert "add tests" in captured["cmd"]
        assert "{prompt}" not in " ".join(captured["cmd"])


class TestInvalidAgent:
    def test_run_rejects_unknown_agent(self, repo_root: Path) -> None:
        with pytest.raises(SystemExit):
            api.run(agent="gpt4")


class TestGeminiAgent:
    """B-3 続編: gemini AgentConfig が登録されている。"""

    def test_resolve_agent_gemini(self) -> None:
        cfg = runner.resolve_agent("gemini")
        assert cfg.name == "gemini"
        assert cfg.required_env == "GEMINI_API_KEY"
        # dangerous = --yolo
        assert "--yolo" in cfg.run_dangerous_cmd
        # task = --yolo + -p
        assert "--yolo" in cfg.task_cmd_template
        assert "-p" in cfg.task_cmd_template
        assert "{prompt}" in " ".join(cfg.task_cmd_template)


class TestWorkspaceRoot:
    """ADR 0002 D4 / D7: workspace_root() / zoo_dir() の fallback 検出。"""

    def test_detects_legacy_layout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Legacy: docker-compose.yml + policy.toml が root 直下（agent-zoo source repo）。"""
        (tmp_path / "docker-compose.yml").write_text("")
        (tmp_path / "policy.toml").write_text("")
        monkeypatch.chdir(tmp_path)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()

        assert runner.workspace_root() == tmp_path
        assert runner.zoo_dir() == tmp_path  # legacy: zoo_dir = workspace_root

        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()

    def test_detects_new_layout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """New layout: .zoo/docker-compose.yml が存在（zoo init された workspace）。"""
        zoo = tmp_path / ".zoo"
        zoo.mkdir()
        (zoo / "docker-compose.yml").write_text("")
        monkeypatch.chdir(tmp_path)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()

        assert runner.workspace_root() == tmp_path
        assert runner.zoo_dir() == zoo

        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()

    def test_new_layout_takes_priority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """両 layout が同時にある場合、new layout が優先される。"""
        (tmp_path / "docker-compose.yml").write_text("")
        (tmp_path / "policy.toml").write_text("")
        zoo = tmp_path / ".zoo"
        zoo.mkdir()
        (zoo / "docker-compose.yml").write_text("")
        monkeypatch.chdir(tmp_path)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()

        assert runner.zoo_dir() == zoo

        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()

    def test_repo_root_is_workspace_root_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """repo_root() は workspace_root() の backward-compat エイリアス。"""
        (tmp_path / "docker-compose.yml").write_text("")
        (tmp_path / "policy.toml").write_text("")
        monkeypatch.chdir(tmp_path)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()

        assert runner.repo_root() == runner.workspace_root()

        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()


class TestRepoRootDiscovery:
    def test_walks_up_from_subdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "docker-compose.yml").write_text("")
        (tmp_path / "policy.toml").write_text("")
        sub = tmp_path / "sub" / "dir"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()
        try:
            assert runner.repo_root() == tmp_path
        finally:
            runner.workspace_root.cache_clear()
            runner.zoo_dir.cache_clear()
            runner.repo_root.cache_clear()

    def test_errors_outside_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        runner.repo_root.cache_clear()
        try:
            with pytest.raises(SystemExit):
                runner.repo_root()
        finally:
            runner.workspace_root.cache_clear()
            runner.zoo_dir.cache_clear()
            runner.repo_root.cache_clear()
