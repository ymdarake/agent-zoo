"""Tests for `zoo init` / `zoo.api.init` (ADR 0002 .zoo/ layout)."""
from __future__ import annotations

from pathlib import Path

import pytest

import zoo
from zoo import api, runner


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake workspace + bundled assets source (ADR 0002 D7).

    - `tmp_path/.zoo/` を workspace_root 検出用に作成
    - `tmp_path/_src/` を bundled source として用意し、`_asset_source()` を monkeypatch
    - issue #66: bundle/policy.toml → bundle/policy/*.toml 5 profile
    """
    zoo = tmp_path / ".zoo"
    zoo.mkdir()
    (zoo / "docker-compose.yml").write_text("workspace marker")  # workspace 検出用

    src = tmp_path / "_src"
    src.mkdir()
    (src / "docker-compose.yml").write_text("compose-source")
    (src / "docker-compose.strict.yml").write_text("strict-source")
    policy_dir = src / "policy"
    policy_dir.mkdir()
    # profile 名を content に埋め込み copy テストで内容照合できるようにする
    for name in ("minimal", "claude", "codex", "gemini", "all"):
        (policy_dir / f"{name}.toml").write_text(
            f'# fake {name} profile\n[domains.allow]\nlist = []\n'
        )
    (src / "addons").mkdir()
    (src / "addons" / "policy.py").write_text("# addon")
    (src / "container").mkdir()
    (src / "container" / "Dockerfile").write_text("FROM scratch")

    monkeypatch.setattr(api, "_asset_source", lambda: src)
    monkeypatch.chdir(tmp_path)
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    yield src  # tests use repo_root as the bundled source location
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()


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
        # issue #66: default profile = minimal（内容は選択された profile を引き継ぐ）
        policy_body = (target / ".zoo" / "policy.toml").read_text()
        assert "fake minimal profile" in policy_body
        assert (target / ".zoo" / "addons" / "policy.py").read_text() == "# addon"
        assert (target / ".zoo" / "container" / "Dockerfile").read_text() == "FROM scratch"
        # runtime dirs
        assert (target / ".zoo" / "data").is_dir()
        assert (target / ".zoo" / "certs").is_dir()
        # zoo build (Dockerfile.base COPY certs/extra/ ...) で必要 + .gitkeep で空 dir 維持
        assert (target / ".zoo" / "certs" / "extra").is_dir()
        assert (target / ".zoo" / "certs" / "extra" / ".gitkeep").is_file()
        assert (target / ".zoo" / "inbox").is_dir()
        # Sprint 006 PR F: cross-container policy lock 用 dir
        assert (target / ".zoo" / "locks").is_dir()
        assert (target / ".zoo" / "policy.runtime.toml").exists()
        assert (target / ".gitignore").exists()
        assert ".zoo/" in (target / ".gitignore").read_text()

    def test_makefile_is_not_distributed(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """Makefile は配布物に含めない（zoo CLI 一本化、ADR 0002 D5 の後継）。"""
        # source 側に Makefile を置いても、_BUNDLED_FILES に含まれないので copy されない
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
        # force + default(minimal) → minimal profile 内容で上書き
        assert "fake minimal profile" in (target / ".zoo" / "policy.toml").read_text()

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


class TestInitPolicyProfile:
    """issue #66: `zoo init --policy <profile>` で初期ポリシー選択."""

    def test_default_policy_is_minimal(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        api.init(target_dir=target)
        assert "fake minimal profile" in (target / ".zoo" / "policy.toml").read_text()

    @pytest.mark.parametrize(
        "profile", ["minimal", "claude", "codex", "gemini", "all"]
    )
    def test_each_profile_copies_expected_source(
        self, repo_root: Path, tmp_path: Path, profile: str
    ) -> None:
        target = tmp_path / "ws"
        api.init(target_dir=target, policy=profile)
        body = (target / ".zoo" / "policy.toml").read_text()
        assert f"fake {profile} profile" in body

    def test_accepts_enum_member(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        api.init(target_dir=target, policy=api.PolicyProfile.claude)
        assert "fake claude profile" in (target / ".zoo" / "policy.toml").read_text()

    def test_rejects_invalid_policy_name(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        with pytest.raises(ValueError, match="unknown"):
            api.init(target_dir=target, policy="unknown")

    def test_error_message_lists_valid_profiles(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        with pytest.raises(ValueError) as exc_info:
            api.init(target_dir=target, policy="foo")
        msg = str(exc_info.value)
        # 候補一覧が hint されること
        for name in ("minimal", "claude", "codex", "gemini", "all"):
            assert name in msg

    def test_policy_is_keyword_only(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """positional 渡しは禁止（force と同じ哲学）."""
        target = tmp_path / "ws"
        with pytest.raises(TypeError):
            api.init(target, False, "claude")  # type: ignore[misc]

    def test_force_with_policy_overwrites(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "ws"
        (target / ".zoo").mkdir(parents=True)
        (target / ".zoo" / "policy.toml").write_text("user-customized")
        api.init(target_dir=target, force=True, policy="codex")
        assert "fake codex profile" in (target / ".zoo" / "policy.toml").read_text()

    def test_existing_policy_toml_preserved_without_force(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """既存 policy.toml は --policy 指定でも force=False なら維持."""
        target = tmp_path / "ws"
        (target / ".zoo").mkdir(parents=True)
        (target / ".zoo" / "policy.toml").write_text("user-customized")
        api.init(target_dir=target, policy="claude")
        assert (target / ".zoo" / "policy.toml").read_text() == "user-customized"

    def test_generated_output_has_profile_metadata_comment(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """debuggability: 生成後の policy.toml に active profile が分かるコメント付与."""
        target = tmp_path / "ws"
        api.init(target_dir=target, policy="claude")
        body = (target / ".zoo" / "policy.toml").read_text()
        # 先頭に profile 名を含むコメント行
        assert body.startswith("# Generated by")
        assert "--policy claude" in body.splitlines()[0]

    def test_policy_profile_enum_exported_from_api(self) -> None:
        assert hasattr(api, "PolicyProfile")
        assert api.PolicyProfile.minimal.value == "minimal"

    def test_policy_profile_reexported_from_zoo(self) -> None:
        assert hasattr(zoo, "PolicyProfile")
        assert zoo.PolicyProfile is api.PolicyProfile

    def test_missing_policy_source_raises(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """production で profile file が欠落 (wheel 破損等) なら FileNotFoundError.

        Claude self-review #2 指摘: silent skip は原因不明エラーの温床。
        """
        # fixture の source dir から policy/claude.toml を消す
        (repo_root / "policy" / "claude.toml").unlink()
        target = tmp_path / "ws"
        with pytest.raises(FileNotFoundError, match="claude.toml"):
            api.init(target_dir=target, policy="claude")

    def test_invalid_policy_no_chained_exception(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """Claude self-review #1: user 向けエラーは enum 内部 ValueError を chain しない."""
        target = tmp_path / "ws"
        with pytest.raises(ValueError) as exc_info:
            api.init(target_dir=target, policy="foo")
        # __cause__ / __context__ を suppressed (from None 効果の回帰テスト)
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__ is True


class TestInitCliPolicyFlag:
    """CLI 層 (`zoo init --policy ...`) 挙動."""

    def setup_method(self) -> None:
        from typer.testing import CliRunner
        self.runner = CliRunner()

    def test_help_lists_all_profiles(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        from zoo import cli
        result = self.runner.invoke(cli.app, ["init", "--help"])
        assert result.exit_code == 0
        # typer が Enum native choice として展開する想定
        stdout = result.stdout
        for name in ("minimal", "claude", "codex", "gemini", "all"):
            assert name in stdout, f"--help に profile {name!r} が含まれない"

    def test_policy_flag_applies_to_init(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        from zoo import cli
        target = tmp_path / "ws_cli"
        result = self.runner.invoke(
            cli.app, ["init", str(target), "--policy", "codex"]
        )
        assert result.exit_code == 0, result.stdout
        assert "fake codex profile" in (target / ".zoo" / "policy.toml").read_text()

    def test_policy_invalid_value_exits_nonzero(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        from zoo import cli
        target = tmp_path / "ws_cli_invalid"
        result = self.runner.invoke(
            cli.app, ["init", str(target), "--policy", "unknown"]
        )
        # typer が Enum 値不一致を自動で reject（exit code 2 相当）
        assert result.exit_code != 0

    def test_default_policy_via_cli_is_minimal(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        from zoo import cli
        target = tmp_path / "ws_default"
        result = self.runner.invoke(cli.app, ["init", str(target)])
        assert result.exit_code == 0, result.stdout
        assert "fake minimal profile" in (target / ".zoo" / "policy.toml").read_text()

    def test_preserved_existing_policy_emits_hint(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """Claude self-review #4: 既存 policy.toml が preserve された時、
        CLI 表示と実態の乖離を防ぐ hint を出す."""
        from zoo import cli
        target = tmp_path / "ws_preserved"
        (target / ".zoo").mkdir(parents=True)
        (target / ".zoo" / "policy.toml").write_text("user-custom")
        result = self.runner.invoke(cli.app, ["init", str(target), "--policy", "claude"])
        assert result.exit_code == 0, result.stdout
        # 既存維持 hint が出る
        assert "既存" in result.stdout or "preserved" in result.stdout.lower() or "--force" in result.stdout
        # 実ファイルは変わっていない
        assert (target / ".zoo" / "policy.toml").read_text() == "user-custom"

    def test_minimal_default_emits_hint_on_fresh_init(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """minimal profile 選択時 (既存ファイル無し) に Inbox 承認の hint を出す."""
        from zoo import cli
        target = tmp_path / "ws_fresh_minimal"
        result = self.runner.invoke(cli.app, ["init", str(target)])
        assert result.exit_code == 0, result.stdout
        # Inbox hint が含まれる
        assert "Inbox" in result.stdout or "minimal" in result.stdout.lower()


class TestInitPolicyEndToEndSmoke:
    """実 bundle/policy/*.toml を実 api.init 経由で書き出す end-to-end smoke.

    他クラスは fake fixture (tmp_path) で wiring を検証するため、
    「実際の profile 内容が実際の init 経由で正しく届く」ことは transitive 保証。
    このクラスで real × real の整合を 1 本で cover し、回帰の早期検出を狙う。

    _asset_source() を monkeypatch せずに呼ぶため、source repo の bundle/
    (または wheel install の _assets/.zoo/) を実際に解決する。
    """

    def test_real_claude_profile_written_through_real_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "ws_real_claude"
        monkeypatch.chdir(tmp_path)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        try:
            resolved = api.init(target_dir=target, policy="claude")
        finally:
            runner.workspace_root.cache_clear()
            runner.zoo_dir.cache_clear()
        assert resolved == target.resolve()
        body = (target / ".zoo" / "policy.toml").read_text()
        # 実 bundle/policy/claude.toml の allow list が反映されている
        assert "api.anthropic.com" in body
        assert "claude.ai" in body
        # 他 provider の domain は含まれない (profile 分離の確認)
        assert "api.openai.com" not in body
        assert "generativelanguage.googleapis.com" not in body
        # 先頭のメタコメント
        assert body.splitlines()[0].startswith("# Generated by `zoo init --policy claude`")

    def test_real_minimal_profile_has_empty_allow_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """default (minimal) の書き出し結果を tomllib で parse し allow_list=[] を assert.

        secure-by-default の契約 (空 allow list) が wheel install / source repo
        どちらの経路でも保証されることの回帰テスト。
        """
        import tomllib
        target = tmp_path / "ws_real_minimal"
        monkeypatch.chdir(tmp_path)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        try:
            api.init(target_dir=target)  # default policy=minimal
        finally:
            runner.workspace_root.cache_clear()
            runner.zoo_dir.cache_clear()
        with open(target / ".zoo" / "policy.toml", "rb") as f:
            # 先頭のメタコメント行は TOML パーサが無視する (コメントとして)
            parsed = tomllib.load(f)
        assert parsed["domains"]["allow"]["list"] == []
        # rate_limits / paths.allow も空 (secure-by-default の 3 点契約)
        assert parsed.get("rate_limits", {}) == {}
        assert parsed.get("paths", {}).get("allow", {}) == {}
