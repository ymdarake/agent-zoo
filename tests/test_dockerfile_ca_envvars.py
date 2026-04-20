"""Tests for Dockerfile.base CA environment variable setup.

`certs/extra/` に企業 root CA 等を置いた場合、`update-ca-certificates` で
system CA bundle (`/etc/ssl/certs/ca-certificates.crt`) には追加されるが、
それだけでは以下は TLS 検証 fail する:

- **pip**: デフォルトで `certifi` bundle を使用
- **Python requests**: 同上
- **Node.js (npm / agent CLI)**: 自前 CA store を使用、system CA を読まない

これらを同じ system CA bundle に向けるため、Dockerfile.base に 4 つの env
変数を設定する。base image 由来の全 agent image (claude / codex / gemini /
unified) + build 時の RUN (npm install 等) の両方で TLS 解決が通る。
"""

from __future__ import annotations

import pathlib


DOCKERFILE_BASE = pathlib.Path("bundle/container/Dockerfile.base")


def _dockerfile_text() -> str:
    return DOCKERFILE_BASE.read_text()


# expected value: update-ca-certificates が populate する system bundle path
# (Debian / Ubuntu 系) — alpine 禁止なので `/etc/ssl/certs/ca-certificates.crt` 固定
_EXPECTED_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def test_has_ssl_cert_file_env():
    """stdlib ssl / openssl 系が読む SSL_CERT_FILE を設定。"""
    text = _dockerfile_text()
    assert f"SSL_CERT_FILE={_EXPECTED_BUNDLE}" in text, (
        "Dockerfile.base に SSL_CERT_FILE 未設定 — stdlib ssl が corporate CA を検証できない"
    )


def test_has_requests_ca_bundle_env():
    """Python requests が読む REQUESTS_CA_BUNDLE を設定。"""
    text = _dockerfile_text()
    assert f"REQUESTS_CA_BUNDLE={_EXPECTED_BUNDLE}" in text, (
        "Dockerfile.base に REQUESTS_CA_BUNDLE 未設定 — requests が corporate CA を検証できない"
    )


def test_has_pip_cert_env():
    """pip install 時の TLS 検証用 PIP_CERT を設定 (certifi 依存を迂回)。"""
    text = _dockerfile_text()
    assert f"PIP_CERT={_EXPECTED_BUNDLE}" in text, (
        "Dockerfile.base に PIP_CERT 未設定 — pip install が corporate CA を検証できない"
    )


def test_has_node_extra_ca_certs_env():
    """Node.js (npm install + agent CLI) 用 NODE_EXTRA_CA_CERTS を設定。"""
    text = _dockerfile_text()
    assert f"NODE_EXTRA_CA_CERTS={_EXPECTED_BUNDLE}" in text, (
        "Dockerfile.base に NODE_EXTRA_CA_CERTS 未設定 — npm install が corporate CA を検証できない"
    )


def test_env_placed_after_update_ca_certificates():
    """env は `update-ca-certificates` が bundle を populate した後に設定されていること
    (順序が逆だと build 早期の RUN で bundle 未生成、env が指す path が空)。"""
    text = _dockerfile_text()
    lines = text.splitlines()

    # update-ca-certificates を含む行の index
    ca_update_idx = next(
        (i for i, ln in enumerate(lines) if "update-ca-certificates" in ln),
        -1,
    )
    assert ca_update_idx >= 0, "update-ca-certificates 呼び出しが無い"

    # SSL_CERT_FILE を含む行の index (代表として 1 つ確認)
    env_idx = next(
        (i for i, ln in enumerate(lines) if "SSL_CERT_FILE=" in ln),
        -1,
    )
    assert env_idx > ca_update_idx, (
        f"SSL_CERT_FILE env (line {env_idx+1}) が "
        f"update-ca-certificates (line {ca_update_idx+1}) より前に書かれている"
    )
