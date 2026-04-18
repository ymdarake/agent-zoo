"""Tests for `zoo init` / `zoo.api.init`."""
from __future__ import annotations

from pathlib import Path

import pytest

import zoo
from zoo import api, runner


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal fake repo root containing source assets."""
    (tmp_path / "docker-compose.yml").write_text("compose-source")
    (tmp_path / "policy.toml").write_text("policy-source")
    (tmp_path / "Makefile").write_text("makefile-source")
    (tmp_path / "docker-compose.strict.yml").write_text("strict-source")
    (tmp_path / "addons").mkdir()
    (tmp_path / "addons" / "policy.py").write_text("# addon")
    (tmp_path / "container").mkdir()
    (tmp_path / "container" / "Dockerfile").write_text("FROM scratch")
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

    def test_copies_files_and_creates_dirs(self, repo_root: Path, tmp_path: Path) -> None:
        target = tmp_path / "workspace"
        result = api.init(target_dir=target)

        assert result == target.resolve()
        assert (target / "docker-compose.yml").read_text() == "compose-source"
        assert (target / "policy.toml").read_text() == "policy-source"
        assert (target / "addons" / "policy.py").read_text() == "# addon"
        assert (target / "container" / "Dockerfile").read_text() == "FROM scratch"
        assert (target / "data").is_dir()
        assert (target / "workspace").is_dir()
        assert (target / "certs").is_dir()
        assert (target / "policy.runtime.toml").exists()

    def test_preserves_existing_without_force(self, repo_root: Path, tmp_path: Path) -> None:
        target = tmp_path / "ws"
        target.mkdir()
        (target / "policy.toml").write_text("user-customized")

        api.init(target_dir=target)
        assert (target / "policy.toml").read_text() == "user-customized"

    def test_force_overwrites(self, repo_root: Path, tmp_path: Path) -> None:
        target = tmp_path / "ws"
        target.mkdir()
        (target / "policy.toml").write_text("old")

        api.init(target_dir=target, force=True)
        assert (target / "policy.toml").read_text() == "policy-source"

    def test_force_overwrites_existing_directory(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """copytree raises FileExistsError on existing dirs — force must rmtree first."""
        target = tmp_path / "ws"
        target.mkdir()
        (target / "addons").mkdir()
        (target / "addons" / "stale.py").write_text("old-addon")

        api.init(target_dir=target, force=True)
        assert not (target / "addons" / "stale.py").exists()
        assert (target / "addons" / "policy.py").read_text() == "# addon"

    def test_idempotent_directory_copy(self, repo_root: Path, tmp_path: Path) -> None:
        target = tmp_path / "ws"
        api.init(target_dir=target)
        api.init(target_dir=target)  # should not raise
        assert (target / "addons" / "policy.py").exists()

    def test_init_with_missing_optional_bundle(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """Missing bundled files (like dashboard/) should be silently skipped."""
        target = tmp_path / "ws"
        api.init(target_dir=target)
        assert not (target / "dashboard").exists()  # not in fake repo

