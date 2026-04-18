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
    runner.repo_root.cache_clear()
    yield tmp_path
    runner.repo_root.cache_clear()


class TestPublicExports:
    def test_api_functions_exposed_at_package_root(self) -> None:
        for name in (
            "run", "task", "up", "down", "reload_policy", "build", "certs",
            "host_start", "host_stop", "logs_clear", "logs_candidates",
            "logs_analyze", "logs_summarize", "logs_alerts",
            "test_unit", "test_smoke",
        ):
            assert hasattr(zoo, name), f"zoo.{name} missing"
            assert callable(getattr(zoo, name))


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


class TestLogsCandidates:
    def test_empty_when_file_missing(self, repo_root: Path) -> None:
        assert api.logs_candidates() == []

    def test_parses_toml(self, repo_root: Path) -> None:
        (repo_root / "policy_candidate.toml").write_text(
            '[[candidates]]\n'
            'type = "domain"\n'
            'value = "example.com"\n'
            'reason = "frequently allowed"\n'
        )
        result = api.logs_candidates()
        assert result == [
            {"type": "domain", "value": "example.com", "reason": "frequently allowed"}
        ]


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


class TestRepoRootDiscovery:
    def test_walks_up_from_subdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "docker-compose.yml").write_text("")
        (tmp_path / "policy.toml").write_text("")
        sub = tmp_path / "sub" / "dir"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        runner.repo_root.cache_clear()
        try:
            assert runner.repo_root() == tmp_path
        finally:
            runner.repo_root.cache_clear()

    def test_errors_outside_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner.repo_root.cache_clear()
        try:
            with pytest.raises(SystemExit):
                runner.repo_root()
        finally:
            runner.repo_root.cache_clear()
