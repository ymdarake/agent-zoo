"""Tests for `.github/dependabot.yml` (Sprint 006 PR E).

新 Dockerfile / requirements.txt を追加するときに dependabot 設定への登録漏れ
を防ぐ回帰テスト。Plan review M5 で「parse できることだけより、coverage 漏れ
検出が価値高い」と指摘あり。
"""

from __future__ import annotations

import pathlib

import yaml


def _config() -> dict:
    return yaml.safe_load(
        pathlib.Path(".github/dependabot.yml").read_text()
    )


def test_version_is_2():
    assert _config()["version"] == 2


def test_all_external_dockerfiles_covered():
    """external image を引く Dockerfile が全部 docker ecosystem に登録されていること。

    `FROM agent-zoo-base:latest` のみの内部参照 Dockerfile は対象外。
    """
    config = _config()
    docker_dirs = {
        u["directory"].lstrip("/").rstrip("/")
        for u in config["updates"]
        if u["package-ecosystem"] == "docker"
    }
    # 既知の external image を引く Dockerfile dir + docker-compose.yml dir
    expected = {"bundle/container", "bundle/dashboard", "bundle"}
    missing = expected - docker_dirs
    assert not missing, f"Dependabot に未登録の docker dir: {missing}"


def test_all_python_requirements_covered():
    """Python 依存ファイルが全部 pip ecosystem に登録されていること。"""
    config = _config()
    pip_dirs = {
        u["directory"].lstrip("/").rstrip("/")
        for u in config["updates"]
        if u["package-ecosystem"] == "pip"
    }
    # root (pyproject.toml) + bundle/dashboard (requirements.txt)
    expected = {"", "bundle/dashboard"}
    missing = expected - pip_dirs
    assert not missing, f"Dependabot に未登録の pip dir: {missing}"


def test_github_actions_ecosystem_present():
    config = _config()
    actions_entries = [
        u for u in config["updates"] if u["package-ecosystem"] == "github-actions"
    ]
    assert len(actions_entries) == 1, "github-actions は root に 1 entry"
    assert actions_entries[0]["directory"] == "/"


def test_groups_present_for_pr_consolidation():
    """PR 重複防止のため、各 update entry に groups を設定していること。"""
    config = _config()
    for u in config["updates"]:
        assert "groups" in u, (
            f"groups 未設定 (PR 重複の恐れ): "
            f"{u['package-ecosystem']} / {u['directory']}"
        )


def test_commit_message_uses_gitmoji_prefix():
    """既存リポジトリの gitmoji 規約に整合していること。"""
    config = _config()
    for u in config["updates"]:
        prefix = u.get("commit-message", {}).get("prefix")
        assert prefix == ":arrow_up:", (
            f"commit-message.prefix が gitmoji :arrow_up: でない: "
            f"{u['package-ecosystem']} / {u['directory']} → {prefix!r}"
        )


def test_weekly_schedule_for_all():
    """全 entry が weekly schedule で運用負荷を一定に保つこと。"""
    config = _config()
    for u in config["updates"]:
        interval = u["schedule"]["interval"]
        assert interval == "weekly", (
            f"schedule.interval が weekly でない: {u['directory']} → {interval!r}"
        )


# ---------- self-review H1: SHA pin 形式の回帰防止テスト ----------
# 後続 PR で誰かが `FROM node:20-slim@sha256:...` を `FROM node:20-slim` に
# 戻したり、`uses: actions/checkout@<40-hex>` を `@v5` に戻すケースを CI で
# fail-fast 検出する。本テストが pass するためには SHA pin が壊されていない
# ことが必要。

import re

_SHA_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# 内部参照 image (FROM agent-zoo-base:latest 等) は registry に無いので除外
_INTERNAL_IMAGE_PATTERNS = ("agent-zoo-base:",)


def _is_external_from(line: str) -> bool:
    line = line.strip()
    if not line.startswith("FROM "):
        return False
    return not any(p in line for p in _INTERNAL_IMAGE_PATTERNS)


def test_external_dockerfile_from_uses_sha_pin():
    """external image を引く全 Dockerfile の FROM 行が @sha256: で pin されていること。"""
    targets = [
        pathlib.Path("bundle/container/Dockerfile.base"),
        pathlib.Path("bundle/dashboard/Dockerfile"),
    ]
    for path in targets:
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _is_external_from(line):
                assert _SHA_DIGEST_RE.search(line), (
                    f"{path}:{lineno} の FROM 行が SHA pin されていない: {line!r}"
                )


def test_docker_compose_image_uses_sha_pin():
    """docker-compose.yml の image: 行 (Dependabot 対象) が SHA pin されていること。"""
    path = pathlib.Path("bundle/docker-compose.yml")
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("image:") and "agent-zoo-base" not in stripped:
            assert _SHA_DIGEST_RE.search(stripped), (
                f"{path}:{lineno} の image: 行が SHA pin されていない: {stripped!r}"
            )


def test_workflow_uses_pinned_to_commit_sha():
    """ci.yml / release.yml の uses: 行が必ず 40 文字 hex commit SHA で pin。

    `@v5` のような mutable tag や branch ref を reject する。
    """
    workflow_dir = pathlib.Path(".github/workflows")
    for wf in workflow_dir.glob("*.yml"):
        for lineno, line in enumerate(wf.read_text().splitlines(), start=1):
            stripped = line.strip()
            # `- uses: foo/bar@<ref>` または `uses: foo/bar@<ref>` を抽出
            m = re.search(r"\buses:\s*([^\s#]+)", stripped)
            if not m:
                continue
            action_ref = m.group(1)
            if "@" not in action_ref:
                continue
            ref = action_ref.split("@", 1)[1]
            assert _COMMIT_SHA_RE.match(ref), (
                f"{wf}:{lineno} uses が commit SHA pin でない: {action_ref!r} (ref={ref!r})"
            )
