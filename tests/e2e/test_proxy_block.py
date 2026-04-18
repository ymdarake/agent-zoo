"""P2 proxy ブロック疎通 E2E（Docker 必要）.

ADR 0003 D2: docker compose で proxy + claude を起動し、
コンテナ内 curl でドメイン制御の疎通を確認。

実行前提:
- Docker daemon 動作中
- dogfood workspace で `zoo init && zoo build` 済（agent-zoo-base + claude image）
- bundle/certs/mitmproxy-ca-cert.pem 生成済（無ければ docker run で自動生成）

skip: Docker daemon が無い、または bundle/ が無い環境では自動 skip。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = REPO_ROOT / "bundle"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available() or not (BUNDLE / "docker-compose.yml").exists(),
    reason="Docker daemon or bundle/docker-compose.yml not available",
)


@pytest.fixture(scope="module")
def proxy_up():
    """proxy + claude service を起動 → teardown で down。"""
    env = {**os.environ, "HOST_UID": str(os.getuid())}
    # CI / 初回起動で bind-mount 対象ファイルが無いと Docker が dir 化してしまうため事前 touch
    (BUNDLE / "policy.runtime.toml").touch(exist_ok=True)
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "proxy"],
            cwd=BUNDLE,
            env=env,
            check=True,
        )
        # healthcheck を待つ（最大 30 秒）。タイムアウト時は pytest.fail で原因特定しやすく
        for _ in range(30):
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "{{.Health}}", "proxy"],
                cwd=BUNDLE,
                capture_output=True,
                text=True,
            )
            if "healthy" in result.stdout:
                break
            time.sleep(1)
        else:
            logs = subprocess.run(
                ["docker", "compose", "logs", "--tail=50", "proxy"],
                cwd=BUNDLE,
                capture_output=True,
                text=True,
            )
            pytest.fail(
                "proxy did not become healthy in 30s\n"
                f"--- docker compose logs proxy (last 50) ---\n{logs.stdout}\n{logs.stderr}"
            )
        yield
    finally:
        # up -d 自体が失敗した場合も、中途半端な container 残留を防ぐため down は必ず試行
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=BUNDLE,
            env=env,
        )
        # 事前 touch した空ファイルをローカル環境から除去（.gitignore 済だが dev の作業 dir を汚さない）
        (BUNDLE / "policy.runtime.toml").unlink(missing_ok=True)


def _curl_via_proxy(url: str) -> int:
    """claude コンテナ内から proxy 経由で curl、HTTP status を返す（接続失敗は 0）。"""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint=",
            "-e",
            "HTTP_PROXY=http://proxy:8080",
            "-e",
            "HTTPS_PROXY=http://proxy:8080",
            "-e",
            "SSL_CERT_FILE=/certs/mitmproxy-ca-cert.pem",
            "claude",
            "curl",
            "-x",
            "http://proxy:8080",
            "--cacert",
            "/certs/mitmproxy-ca-cert.pem",
            "-s",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--connect-timeout",
            "5",
            url,
        ],
        cwd=BUNDLE,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def test_allowed_domain_returns_response(proxy_up) -> None:
    """allow list 内のドメインへの通信は HTTP response を返す（200/404 等）。"""
    status = _curl_via_proxy("https://api.anthropic.com/")
    assert status > 0, f"expected HTTP response, got {status}"


def test_blocked_domain_returns_403(proxy_up) -> None:
    """allow list 外のドメインは proxy が 403 で block。"""
    status = _curl_via_proxy("https://evil.com/")
    # 403 (block) or 0 (connection reset) どちらも block と扱う
    assert status in (403, 0), f"expected 403 or 0 (blocked), got {status}"


def test_direct_access_without_proxy_fails(proxy_up) -> None:
    """proxy をバイパスした直接アクセスは internal network の制約で失敗する。"""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint=",
            "-e",
            "HTTP_PROXY=",
            "-e",
            "HTTPS_PROXY=",
            "claude",
            "curl",
            "-s",
            "--connect-timeout",
            "3",
            "https://api.anthropic.com/",
        ],
        cwd=BUNDLE,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0, "direct access should fail (network isolated)"
