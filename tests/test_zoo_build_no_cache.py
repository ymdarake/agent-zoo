"""Tests for ``zoo build --no-cache`` option.

既存 Docker image の layer cache を skip して 0 から再 build する option。
Dockerfile 変更 (Sprint 008 の CA env 追加等) を確実に反映したい時、
agent-zoo package upgrade 後の dogfood で使う。

layer 構成:
- `docker build --no-cache` (base image)
- `docker compose build --no-cache` (agent + dashboard)

両方に `--no-cache` を伝播させる (片方だけ cache skip すると Dockerfile.base の
変更が agent 側に反映されないため)。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from zoo import api, runner


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend tmp_path is the workspace root (.zoo/ 配下に bundled)."""
    zoo_dir = tmp_path / ".zoo"
    zoo_dir.mkdir()
    (zoo_dir / "docker-compose.yml").write_text("")
    (zoo_dir / "container").mkdir()
    (zoo_dir / "container" / "Dockerfile.base").write_text("FROM scratch\n")
    (zoo_dir / "certs").mkdir()
    (zoo_dir / "certs" / "mitmproxy-ca-cert.pem").write_text("fake-cert")
    monkeypatch.chdir(tmp_path)
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    yield tmp_path
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()


class TestBuildNoCache:
    def test_passes_no_cache_flag_to_base_and_compose_build(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`api.build(no_cache=True)` で base + compose build の両 docker 呼出に
        `--no-cache` が渡される。"""
        calls: list[list[str]] = []
        monkeypatch.setattr(runner, "ensure_certs", lambda: None)
        monkeypatch.setattr(
            runner, "run",
            lambda cmd, **kw: calls.append(list(cmd)) or MagicMock(returncode=0),
        )

        api.build(agent="claude", no_cache=True)

        # base build 行 (docker build -t agent-zoo-base:latest ...) に --no-cache
        base_cmd = next(c for c in calls if "build" in c and "agent-zoo-base:latest" in c)
        assert "--no-cache" in base_cmd

        # compose build 行 (docker compose build ...) に --no-cache
        compose_cmd = next(
            c for c in calls if c[:2] == ["docker", "compose"] and "build" in c
        )
        assert "--no-cache" in compose_cmd

    def test_default_does_not_pass_no_cache(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """default (no_cache=False) では --no-cache 無し。"""
        calls: list[list[str]] = []
        monkeypatch.setattr(runner, "ensure_certs", lambda: None)
        monkeypatch.setattr(
            runner, "run",
            lambda cmd, **kw: calls.append(list(cmd)) or MagicMock(returncode=0),
        )

        api.build(agent="claude")

        for c in calls:
            assert "--no-cache" not in c, (
                f"default で --no-cache が混入: {c}"
            )


class TestBuildBaseNoCache:
    """runner.build_base() も no_cache kwarg を受ける。"""

    def test_build_base_with_no_cache(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[list[str]] = []
        monkeypatch.setattr(
            runner, "run",
            lambda cmd, **kw: captured.append(list(cmd)) or MagicMock(returncode=0),
        )
        runner.build_base(no_cache=True)
        assert captured, "docker build が呼ばれていない"
        assert "--no-cache" in captured[0]

    def test_build_base_default(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[list[str]] = []
        monkeypatch.setattr(
            runner, "run",
            lambda cmd, **kw: captured.append(list(cmd)) or MagicMock(returncode=0),
        )
        runner.build_base()
        assert captured
        assert "--no-cache" not in captured[0]


class TestCliBuildNoCache:
    """CLI layer (`zoo build --no-cache`) で flag が認識される。"""

    def test_cli_has_no_cache_flag(self) -> None:
        """Typer の build command に no-cache option が存在する。"""
        from typer.testing import CliRunner

        from zoo.cli import app

        runner_cli = CliRunner()
        result = runner_cli.invoke(app, ["build", "--help"])
        assert result.exit_code == 0
        assert "--no-cache" in result.stdout, (
            f"`zoo build --help` に --no-cache option が見つからない:\n{result.stdout}"
        )
