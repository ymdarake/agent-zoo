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
