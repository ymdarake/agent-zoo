"""Tests for `zoo certs import / list / remove` (issue #64)."""
from __future__ import annotations

from pathlib import Path

import pytest

from zoo import api, runner


_SAMPLE_PEM = (
    b"-----BEGIN CERTIFICATE-----\n"
    b"MIIBkTCB+wIJAJxxxxxxxxxxMA0GCSqGSIb3DQEBCwUAMBMxETAPBgNVBAMMCHRl\n"
    b"c3QtY2EwHhcNMjQwMTAxMDAwMDAwWhcNMzQwMTAxMDAwMDAwWjATMREwDwYDVQQD\n"
    b"DAh0ZXN0LWNhMFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAMxxxxxxxxxxxxxxxxxx\n"
    b"-----END CERTIFICATE-----\n"
)


def test_sample_pem_uses_real_header() -> None:
    """production の `_PEM_HEADER` リテラルが test sample に含まれることを保証 (typo 防御)。"""
    from zoo.api import _PEM_HEADER  # noqa: PLC0415
    assert _PEM_HEADER in _SAMPLE_PEM


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp に最小 workspace と .zoo/certs/extra/.gitkeep を作る。"""
    zoo = tmp_path / ".zoo"
    zoo.mkdir()
    (zoo / "docker-compose.yml").write_text("marker")  # workspace 検出
    (zoo / "certs").mkdir()
    extra = zoo / "certs" / "extra"
    extra.mkdir()
    (extra / ".gitkeep").write_text("")
    monkeypatch.chdir(tmp_path)
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    yield tmp_path
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()


@pytest.fixture
def sample_pem(tmp_path: Path) -> Path:
    """合法な PEM ファイルを 1 枚生成。"""
    p = tmp_path / "company-ca.pem"
    p.write_bytes(_SAMPLE_PEM)
    return p


@pytest.fixture
def invalid_cert(tmp_path: Path) -> Path:
    """PEM ヘッダ無しの非証明書ファイル。"""
    p = tmp_path / "not-a-cert.txt"
    p.write_text("hello world")
    return p


# === certs_import =========================================================


class TestCertsImport:
    def test_copies_to_extra_dir(self, workspace: Path, sample_pem: Path) -> None:
        dest = api.certs_import(sample_pem)
        assert dest == workspace / ".zoo" / "certs" / "extra" / "company-ca.pem"
        assert dest.read_bytes() == _SAMPLE_PEM

    def test_returns_dest_path(self, workspace: Path, sample_pem: Path) -> None:
        dest = api.certs_import(sample_pem)
        assert dest.is_file()

    def test_rename_with_name_option(self, workspace: Path, sample_pem: Path) -> None:
        dest = api.certs_import(sample_pem, name="custom.pem")
        assert dest.name == "custom.pem"
        assert dest.read_bytes() == _SAMPLE_PEM

    def test_existing_without_force_raises(
        self, workspace: Path, sample_pem: Path
    ) -> None:
        api.certs_import(sample_pem)
        with pytest.raises(FileExistsError):
            api.certs_import(sample_pem)

    def test_existing_with_force_overwrites(
        self, workspace: Path, sample_pem: Path, tmp_path: Path
    ) -> None:
        api.certs_import(sample_pem)
        new = tmp_path / "company-ca.pem"
        new.write_bytes(_SAMPLE_PEM + b"# updated\n")
        dest = api.certs_import(new, force=True)
        assert dest.read_bytes().endswith(b"# updated\n")

    def test_missing_source_raises(self, workspace: Path) -> None:
        with pytest.raises(FileNotFoundError):
            api.certs_import("/nonexistent/path.pem")

    def test_invalid_pem_raises(self, workspace: Path, invalid_cert: Path) -> None:
        with pytest.raises(ValueError, match="PEM"):
            api.certs_import(invalid_cert)

    def test_path_traversal_in_name_rejected(
        self, workspace: Path, sample_pem: Path
    ) -> None:
        for evil in ("../escape.pem", "sub/dir.pem", "..", ".", "evil\x00.pem"):
            with pytest.raises(ValueError):
                api.certs_import(sample_pem, name=evil)

    def test_empty_name_rejected(self, workspace: Path, sample_pem: Path) -> None:
        for empty in ("", "   "):
            with pytest.raises(ValueError, match="empty"):
                api.certs_import(sample_pem, name=empty)

    def test_extension_whitelist(self, workspace: Path, sample_pem: Path) -> None:
        # `.pem` / `.crt` / `.cer` のみ許容
        for ok in ("ok.pem", "ok.crt", "ok.cer"):
            api.certs_import(sample_pem, name=ok, force=True)
        for ng in ("ng.txt", "ng.key", "ng", "ng.pem.bak"):
            with pytest.raises(ValueError, match="\\.pem|\\.crt|\\.cer"):
                api.certs_import(sample_pem, name=ng)

    def test_dest_is_dir_rejected(
        self, workspace: Path, sample_pem: Path
    ) -> None:
        # extra/blocked.pem を **dir として** 先に作っておく
        extra = workspace / ".zoo" / "certs" / "extra"
        (extra / "blocked.pem").mkdir()
        with pytest.raises(ValueError, match="directory"):
            api.certs_import(sample_pem, name="blocked.pem", force=True)

    def test_src_is_dir_rejected(self, workspace: Path, tmp_path: Path) -> None:
        src_dir = tmp_path / "ca-dir"
        src_dir.mkdir()
        with pytest.raises(ValueError, match="not a file"):
            api.certs_import(src_dir)

    def test_symlink_src_resolves_to_regular_file(
        self, workspace: Path, sample_pem: Path, tmp_path: Path
    ) -> None:
        link = tmp_path / "ca-link.pem"
        link.symlink_to(sample_pem)
        dest = api.certs_import(link)
        # コピー先は通常 file (symlink ではない) であること
        assert dest.is_file()
        assert not dest.is_symlink()
        assert dest.read_bytes() == _SAMPLE_PEM

    def test_gitkeep_preserved(self, workspace: Path, sample_pem: Path) -> None:
        api.certs_import(sample_pem)
        assert (workspace / ".zoo" / "certs" / "extra" / ".gitkeep").exists()

    def test_gitkeep_protected_from_overwrite(
        self, workspace: Path, sample_pem: Path
    ) -> None:
        with pytest.raises(ValueError):
            api.certs_import(sample_pem, name=".gitkeep", force=True)

    def test_creates_extra_dir_if_missing(
        self, tmp_path: Path, sample_pem: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        zoo = tmp_path / ".zoo"
        zoo.mkdir()
        (zoo / "docker-compose.yml").write_text("marker")
        # 意図的に extra/ を作らない
        monkeypatch.chdir(tmp_path)
        runner.workspace_root.cache_clear()
        runner.zoo_dir.cache_clear()
        try:
            dest = api.certs_import(sample_pem)
            assert dest.parent == zoo / "certs" / "extra"
            assert dest.parent.is_dir()
        finally:
            runner.workspace_root.cache_clear()
            runner.zoo_dir.cache_clear()


# === certs_list ===========================================================


class TestCertsList:
    def test_empty_returns_empty_list(self, workspace: Path) -> None:
        assert api.certs_list() == []

    def test_excludes_gitkeep(self, workspace: Path, sample_pem: Path) -> None:
        api.certs_import(sample_pem)
        result = api.certs_list()
        assert result == ["company-ca.pem"]
        assert ".gitkeep" not in result

    def test_lists_imported_certs_sorted(
        self, workspace: Path, sample_pem: Path
    ) -> None:
        api.certs_import(sample_pem, name="b.pem")
        api.certs_import(sample_pem, name="a.pem")
        api.certs_import(sample_pem, name="c.pem")
        assert api.certs_list() == ["a.pem", "b.pem", "c.pem"]


# === certs_remove =========================================================


class TestCertsRemove:
    def test_removes_existing(self, workspace: Path, sample_pem: Path) -> None:
        api.certs_import(sample_pem)
        assert api.certs_remove("company-ca.pem") is True
        assert "company-ca.pem" not in api.certs_list()

    def test_missing_returns_false(self, workspace: Path) -> None:
        assert api.certs_remove("nonexistent.pem") is False

    def test_gitkeep_protected(self, workspace: Path) -> None:
        with pytest.raises(ValueError):
            api.certs_remove(".gitkeep")
        # 残っている
        assert (workspace / ".zoo" / "certs" / "extra" / ".gitkeep").exists()

    def test_path_traversal_rejected(self, workspace: Path) -> None:
        for evil in ("../escape.pem", "sub/dir", "..", ""):
            with pytest.raises(ValueError):
                api.certs_remove(evil)


# === CLI smoke (typer.testing.CliRunner) =================================


class TestCertsCliSmoke:
    """CLI 層 smoke (callback fire のリグレッション保険)。"""

    def setup_method(self) -> None:
        from typer.testing import CliRunner
        self.runner = CliRunner()

    def test_certs_help_does_not_invoke_default(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`zoo certs --help` で `api.certs()` が呼ばれないこと。"""
        from zoo import cli
        called = []
        monkeypatch.setattr(api, "certs", lambda: called.append("called"))
        result = self.runner.invoke(cli.app, ["certs", "--help"])
        assert result.exit_code == 0
        assert "import" in result.stdout
        assert called == []

    def test_certs_no_arg_invokes_default(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`zoo certs` (no sub-command) で `api.certs()` が呼ばれること。"""
        from zoo import cli
        called = []
        monkeypatch.setattr(api, "certs", lambda: called.append("called"))
        result = self.runner.invoke(cli.app, ["certs"])
        assert result.exit_code == 0
        assert called == ["called"]

    def test_certs_list_empty(self, workspace: Path) -> None:
        from zoo import cli
        result = self.runner.invoke(cli.app, ["certs", "list"])
        assert result.exit_code == 0
        assert "(no extra certs)" in result.stdout


class TestCertsImportReadOnlyDest:
    def test_force_overwrites_readonly_dest(
        self, workspace: Path, sample_pem: Path, tmp_path: Path
    ) -> None:
        """force=True なら既存が read-only でも上書きできる (Gemini review M-2)。"""
        dest = api.certs_import(sample_pem)
        dest.chmod(0o444)
        try:
            new_src = tmp_path / "new.pem"
            new_src.write_bytes(_SAMPLE_PEM + b"# v2\n")
            api.certs_import(new_src, name=dest.name, force=True)
            assert dest.read_bytes().endswith(b"# v2\n")
        finally:
            dest.chmod(0o644)  # cleanup permission for tmp_path teardown
