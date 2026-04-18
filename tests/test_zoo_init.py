"""Tests for `zoo init` / `zoo.api.init` (ADR 0002 .zoo/ layout)."""
from __future__ import annotations

from pathlib import Path

import pytest

import zoo
from zoo import api, runner


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal fake source repo containing bundled assets at root level.

    agent-zoo source repo = legacy layout（D7）。`api._asset_source()` は
    `runner.repo_root()` を返すため、ここで作った tmp_path 直下が source 相当となる。
    """
    (tmp_path / "docker-compose.yml").write_text("compose-source")
    (tmp_path / "policy.toml").write_text("policy-source")
    (tmp_path / "docker-compose.strict.yml").write_text("strict-source")
    (tmp_path / "addons").mkdir()
    (tmp_path / "addons" / "policy.py").write_text("# addon")
    (tmp_path / "container").mkdir()
    (tmp_path / "container" / "Dockerfile").write_text("FROM scratch")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "workspace-gitignore").write_text(
        "# workspace ignore\n.zoo/\n"
    )
    (tmp_path / "templates" / "zoo-gitignore").write_text(
        "# zoo internal ignore\ndata/\ncerts/\npolicy.runtime.toml\n"
    )
    monkeypatch.chdir(tmp_path)
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    runner.repo_root.cache_clear()
    yield tmp_path
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    runner.repo_root.cache_clear()


class TestInit:
    def test_init_is_exported(self) -> None:
        assert zoo.init is api.init

    def test_copies_files_and_creates_zoo_dir(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "workspace"
        result = api.init(target_dir=target)

        assert result == target.resolve()
        # 新 layout: 全 bundled は target/.zoo/ 配下
        assert (target / ".zoo" / "docker-compose.yml").read_text() == "compose-source"
        assert (target / ".zoo" / "policy.toml").read_text() == "policy-source"
        assert (target / ".zoo" / "addons" / "policy.py").read_text() == "# addon"
        assert (target / ".zoo" / "container" / "Dockerfile").read_text() == "FROM scratch"
        # runtime dirs
        assert (target / ".zoo" / "data").is_dir()
        assert (target / ".zoo" / "certs").is_dir()
        assert (target / ".zoo" / "inbox").is_dir()
        assert (target / ".zoo" / "policy.runtime.toml").exists()
        # gitignore × 2
        assert (target / ".gitignore").exists()
        assert ".zoo/" in (target / ".gitignore").read_text()
        assert (target / ".zoo" / ".gitignore").exists()
        assert "data/" in (target / ".zoo" / ".gitignore").read_text()

    def test_makefile_is_not_distributed(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """ADR 0002 D5: Makefile は配布物に含めない。"""
        (repo_root / "Makefile").write_text("makefile-source")
        target = tmp_path / "ws"
        api.init(target_dir=target)
        assert not (target / ".zoo" / "Makefile").exists()
        assert not (target / "Makefile").exists()

    def test_workspace_dir_is_not_created(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """新 layout: target 自体が workspace、target/workspace は作らない。"""
        target = tmp_path / "ws"
        api.init(target_dir=target)
        assert not (target / "workspace").exists()

    def test_preserves_existing_zoo_files_without_force(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        (target / ".zoo").mkdir(parents=True)
        (target / ".zoo" / "policy.toml").write_text("user-customized")
        api.init(target_dir=target)
        assert (target / ".zoo" / "policy.toml").read_text() == "user-customized"

    def test_preserves_existing_workspace_gitignore(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """user の workspace 直下 .gitignore は既存を尊重する。"""
        target = tmp_path / "ws"
        target.mkdir()
        (target / ".gitignore").write_text("user-rules\n")
        api.init(target_dir=target)
        assert (target / ".gitignore").read_text() == "user-rules\n"

    def test_force_overwrites_zoo_files(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        (target / ".zoo").mkdir(parents=True)
        (target / ".zoo" / "policy.toml").write_text("old")
        api.init(target_dir=target, force=True)
        assert (target / ".zoo" / "policy.toml").read_text() == "policy-source"

    def test_force_overwrites_existing_directory(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        (target / ".zoo" / "addons").mkdir(parents=True)
        (target / ".zoo" / "addons" / "stale.py").write_text("old-addon")
        api.init(target_dir=target, force=True)
        assert not (target / ".zoo" / "addons" / "stale.py").exists()
        assert (target / ".zoo" / "addons" / "policy.py").read_text() == "# addon"

    def test_idempotent_directory_copy(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        api.init(target_dir=target)
        api.init(target_dir=target)  # should not raise
        assert (target / ".zoo" / "addons" / "policy.py").exists()

    def test_init_with_missing_optional_bundle(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """Missing bundled dirs (e.g. dashboard/) は silently skip。"""
        target = tmp_path / "ws"
        api.init(target_dir=target)
        assert not (target / ".zoo" / "dashboard").exists()
