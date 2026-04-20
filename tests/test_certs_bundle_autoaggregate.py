"""Tests for automatic `certs/extra/bundle.pem` aggregation.

mitmproxy は上流 TLS 検証に ``--set ssl_verify_upstream_trusted_ca`` で
**単一 path** (`bundle.pem`) を要求する。`zoo certs import` / `certs_remove`
で個別 PEM file を操作した時、bundle.pem を自動再生成する仕組みがないと
user が手動で `cat *.pem > bundle.pem` しなければならない (設計欠陥)。

本 module は以下を検証:

- `certs_import` 後に ``bundle.pem`` が extra/ 内の全 PEM を結合した内容で生成
- `certs_remove` 後に bundle.pem が更新 (削除した cert の内容が消える)
- 全 cert が remove された時、bundle.pem も削除 (empty bundle を残さない)
- bundle.pem 自体は import 対象外 (再帰結合しない)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import zoo
from zoo import api, runner


_PEM_A = b"""-----BEGIN CERTIFICATE-----
MIIAAAAA-FAKE-CERT-A-FOR-TEST-ONLY
-----END CERTIFICATE-----
"""

_PEM_B = b"""-----BEGIN CERTIFICATE-----
MIIBBBBB-FAKE-CERT-B-FOR-TEST-ONLY
-----END CERTIFICATE-----
"""


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp_path に `.zoo/certs/extra/` を用意し CWD を合わせる。"""
    zoo_dir = tmp_path / ".zoo"
    (zoo_dir / "certs" / "extra").mkdir(parents=True)
    (zoo_dir / "docker-compose.yml").write_text("")
    (zoo_dir / "certs" / "extra" / ".gitkeep").touch()
    monkeypatch.chdir(tmp_path)
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    yield tmp_path
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()


def _write_src_pem(tmp_path: Path, name: str, body: bytes) -> Path:
    src = tmp_path / name
    src.write_bytes(body)
    return src


def test_import_creates_bundle_pem(workspace: Path, tmp_path: Path) -> None:
    src = _write_src_pem(tmp_path, "corp.pem", _PEM_A)
    api.certs_import(src)
    bundle = workspace / ".zoo" / "certs" / "extra" / "bundle.pem"
    assert bundle.exists(), "bundle.pem が生成されていない"
    assert _PEM_A in bundle.read_bytes()


def test_import_multiple_aggregates_all(workspace: Path, tmp_path: Path) -> None:
    api.certs_import(_write_src_pem(tmp_path, "corp.pem", _PEM_A))
    api.certs_import(_write_src_pem(tmp_path, "internal.pem", _PEM_B))
    bundle = workspace / ".zoo" / "certs" / "extra" / "bundle.pem"
    content = bundle.read_bytes()
    assert _PEM_A in content
    assert _PEM_B in content


def test_remove_updates_bundle(workspace: Path, tmp_path: Path) -> None:
    api.certs_import(_write_src_pem(tmp_path, "corp.pem", _PEM_A))
    api.certs_import(_write_src_pem(tmp_path, "internal.pem", _PEM_B))
    api.certs_remove("corp.pem")
    bundle = workspace / ".zoo" / "certs" / "extra" / "bundle.pem"
    content = bundle.read_bytes()
    assert _PEM_A not in content, "削除した cert が bundle から消えていない"
    assert _PEM_B in content


def test_remove_last_cert_deletes_bundle(workspace: Path, tmp_path: Path) -> None:
    api.certs_import(_write_src_pem(tmp_path, "corp.pem", _PEM_A))
    api.certs_remove("corp.pem")
    bundle = workspace / ".zoo" / "certs" / "extra" / "bundle.pem"
    assert not bundle.exists(), (
        "extra/*.pem が空なのに bundle.pem が残留 (mitmproxy が空 bundle を誤読)"
    )


def test_bundle_pem_itself_is_not_listed_in_certs_list(
    workspace: Path, tmp_path: Path
) -> None:
    """`zoo certs list` は bundle.pem を自動生成物として除外する。"""
    api.certs_import(_write_src_pem(tmp_path, "corp.pem", _PEM_A))
    assert "bundle.pem" not in api.certs_list()


def test_bundle_pem_is_rejected_as_import_source_name(
    workspace: Path, tmp_path: Path
) -> None:
    """`zoo certs import foo.pem --name bundle.pem` は reject (予約名)。"""
    src = _write_src_pem(tmp_path, "corp.pem", _PEM_A)
    with pytest.raises(ValueError, match=r"bundle\.pem"):
        api.certs_import(src, name="bundle.pem")


def test_init_rebuilds_bundle_from_existing_extras(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既存 extra/*.pem がある workspace で zoo init を再実行すると bundle を再生成。
    (古い version で import した user が `zoo init --force` でも `init` でも同期可能)。"""
    target = tmp_path / "ws"
    target.mkdir()
    runner.workspace_root.cache_clear()
    runner.zoo_dir.cache_clear()
    # zoo init で .zoo/ 展開
    api.init(target_dir=target)
    extra = target / ".zoo" / "certs" / "extra"
    # 既存の extra/ に pem を直接配置 (古い import 経由を simulate)
    (extra / "corp.pem").write_bytes(_PEM_A)
    # bundle は無い状態で再度 init
    assert not (extra / "bundle.pem").exists()
    api.init(target_dir=target)
    assert (extra / "bundle.pem").exists(), (
        "既存 extra/*.pem がある時に zoo init が bundle を再生成していない"
    )
    assert _PEM_A in (extra / "bundle.pem").read_bytes()
