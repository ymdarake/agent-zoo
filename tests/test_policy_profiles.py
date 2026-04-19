"""bundle/policy/*.toml の 5 profile が仕様を満たすことを検証（issue #66）.

- 5 profile が存在し、tomllib で parse 可能
- minimal は真に空（domains.allow.list / paths.allow / rate_limits すべて空）
- all は旧 bundle/policy.toml 相当の 13 domain を allow
- claude / codex / gemini は該当 provider domain のみ許可
- 共通セクション（general / domains.deny / domains.dismissed / payload_rules /
  tool_use_rules / alerts）は全 profile で parsed dict 等価（drift 検出）
- PolicyProfile enum の value と file 名が 1:1 対応
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from zoo.api import PolicyProfile

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = REPO_ROOT / "bundle" / "policy"

PROFILE_NAMES = ("minimal", "claude", "codex", "gemini", "all")
COMMON_SECTIONS = (
    "general",
    ("domains", "deny"),
    ("domains", "dismissed"),
    "payload_rules",
    "tool_use_rules",
    "alerts",
)


def _load(name: str) -> dict:
    with open(POLICY_DIR / f"{name}.toml", "rb") as f:
        return tomllib.load(f)


def _section(data: dict, path: str | tuple[str, ...]) -> dict:
    if isinstance(path, str):
        return data.get(path, {})
    cur = data
    for key in path:
        cur = cur.get(key, {})
    return cur


@pytest.fixture(scope="module")
def profiles() -> dict[str, dict]:
    return {name: _load(name) for name in PROFILE_NAMES}


class TestProfileFilesExist:
    def test_policy_dir_exists(self) -> None:
        assert POLICY_DIR.is_dir(), f"{POLICY_DIR} not found"

    @pytest.mark.parametrize("name", PROFILE_NAMES)
    def test_profile_file_exists(self, name: str) -> None:
        assert (POLICY_DIR / f"{name}.toml").is_file(), f"{name}.toml missing"

    @pytest.mark.parametrize("name", PROFILE_NAMES)
    def test_profile_parses_as_toml(self, name: str) -> None:
        _load(name)  # raises TOMLDecodeError on failure


class TestMinimalProfile:
    """secure by default: minimal は真に空."""

    def test_allow_list_is_empty(self, profiles: dict[str, dict]) -> None:
        assert profiles["minimal"].get("domains", {}).get("allow", {}).get("list", []) == []

    def test_paths_allow_is_empty(self, profiles: dict[str, dict]) -> None:
        assert profiles["minimal"].get("paths", {}).get("allow", {}) == {}

    def test_rate_limits_is_empty(self, profiles: dict[str, dict]) -> None:
        assert profiles["minimal"].get("rate_limits", {}) == {}


class TestAllProfile:
    """all profile は旧 bundle/policy.toml 相当（移行完全性）."""

    EXPECTED_DOMAINS = frozenset({
        "api.anthropic.com",
        "statsig.anthropic.com",
        "platform.claude.com",
        "code.claude.com",
        "claude.ai",
        "mcp-proxy.anthropic.com",
        "api.openai.com",
        "auth0.openai.com",
        "*.auth.openai.com",
        "*.chatgpt.com",
        "generativelanguage.googleapis.com",
        "oauth2.googleapis.com",
        "accounts.google.com",
    })

    def test_allow_list_contains_all_13_domains(
        self, profiles: dict[str, dict]
    ) -> None:
        allow = set(profiles["all"]["domains"]["allow"]["list"])
        assert allow == self.EXPECTED_DOMAINS

    def test_paths_allow_has_legacy_4_entries(
        self, profiles: dict[str, dict]
    ) -> None:
        paths = profiles["all"]["paths"]["allow"]
        assert set(paths.keys()) == {
            "raw.githubusercontent.com",
            "registry.npmjs.org",
            "downloads.claude.ai",
            "github.com",
        }

    def test_rate_limits_has_anthropic_and_openai(
        self, profiles: dict[str, dict]
    ) -> None:
        assert set(profiles["all"]["rate_limits"].keys()) == {
            "api.anthropic.com",
            "api.openai.com",
        }


class TestProviderProfiles:
    """claude/codex/gemini は provider 固有のみ allow."""

    def test_claude_has_only_anthropic_domains(
        self, profiles: dict[str, dict]
    ) -> None:
        allow = set(profiles["claude"]["domains"]["allow"]["list"])
        assert allow == {
            "api.anthropic.com",
            "statsig.anthropic.com",
            "platform.claude.com",
            "code.claude.com",
            "claude.ai",
            "mcp-proxy.anthropic.com",
        }

    def test_claude_rate_limits_anthropic_only(
        self, profiles: dict[str, dict]
    ) -> None:
        assert set(profiles["claude"]["rate_limits"].keys()) == {"api.anthropic.com"}

    def test_claude_paths_allow_is_anthropic_scoped(
        self, profiles: dict[str, dict]
    ) -> None:
        paths = profiles["claude"].get("paths", {}).get("allow", {})
        assert "raw.githubusercontent.com" in paths
        assert "registry.npmjs.org" in paths
        assert "downloads.claude.ai" in paths
        assert "github.com" in paths

    def test_codex_has_only_openai_domains(
        self, profiles: dict[str, dict]
    ) -> None:
        allow = set(profiles["codex"]["domains"]["allow"]["list"])
        assert allow == {
            "api.openai.com",
            "auth0.openai.com",
            "*.auth.openai.com",
            "*.chatgpt.com",
        }

    def test_codex_rate_limits_openai_only(
        self, profiles: dict[str, dict]
    ) -> None:
        assert set(profiles["codex"]["rate_limits"].keys()) == {"api.openai.com"}

    def test_codex_paths_allow_is_empty(
        self, profiles: dict[str, dict]
    ) -> None:
        assert profiles["codex"].get("paths", {}).get("allow", {}) == {}

    def test_gemini_has_only_google_domains(
        self, profiles: dict[str, dict]
    ) -> None:
        allow = set(profiles["gemini"]["domains"]["allow"]["list"])
        assert allow == {
            "generativelanguage.googleapis.com",
            "oauth2.googleapis.com",
            "accounts.google.com",
        }

    def test_gemini_rate_limits_is_empty(
        self, profiles: dict[str, dict]
    ) -> None:
        assert profiles["gemini"].get("rate_limits", {}) == {}

    def test_gemini_paths_allow_is_empty(
        self, profiles: dict[str, dict]
    ) -> None:
        assert profiles["gemini"].get("paths", {}).get("allow", {}) == {}


class TestCommonSectionsDrift:
    """共通セクション drift 検出: 5 profile 間で parsed dict が等価."""

    @pytest.mark.parametrize("section", COMMON_SECTIONS)
    def test_common_section_identical_across_profiles(
        self, profiles: dict[str, dict], section
    ) -> None:
        ref = _section(profiles["minimal"], section)
        for name in PROFILE_NAMES[1:]:
            actual = _section(profiles[name], section)
            assert actual == ref, (
                f"drift detected: [{section}] differs between "
                f"minimal and {name} profile"
            )


class TestPolicyProfileEnum:
    """PolicyProfile enum の value と file 名が 1:1 対応."""

    def test_enum_members_match_file_names(self) -> None:
        enum_values = {p.value for p in PolicyProfile}
        assert enum_values == set(PROFILE_NAMES)

    def test_enum_default_is_minimal(self) -> None:
        # minimal が enum の先頭（default として最初に列挙される想定）
        assert PolicyProfile.minimal.value == "minimal"

    def test_enum_is_str_subclass(self) -> None:
        """str subclass は typer native choice と f-string 補間に必要."""
        assert issubclass(PolicyProfile, str)
