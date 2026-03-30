"""Policy engine for agent-harness. Pure logic, no mitmproxy dependency."""

import logging
import tomllib
from fnmatch import fnmatch
from pathlib import Path

logger = logging.getLogger(__name__)


class PolicyEngine:
    def __init__(self, policy_path: str):
        self.policy_path = Path(policy_path)
        self._mtime: float = 0.0
        self.allow_list: list[str] = []
        self.deny_list: list[str] = []
        self.db_path: str = ""
        self._load()

    def _load(self):
        with open(self.policy_path, "rb") as f:
            policy = tomllib.load(f)
        self._mtime = self.policy_path.stat().st_mtime

        domains = policy.get("domains", {})
        self.allow_list = domains.get("allow", {}).get("list", [])
        self.deny_list = domains.get("deny", {}).get("list", [])
        self.db_path = policy.get("general", {}).get("log_db", "/data/harness.db")

    def maybe_reload(self) -> bool:
        """policy.tomlが更新されていたらリロードする。
        不正なTOMLの場合は旧ポリシーを維持してFalseを返す。
        """
        try:
            mtime = self.policy_path.stat().st_mtime
            if mtime > self._mtime:
                self._load()
                return True
        except (OSError, tomllib.TOMLDecodeError, KeyError) as e:
            logger.warning(f"Policy reload failed, keeping previous policy: {e}")
        return False

    def is_allowed(self, host: str) -> tuple[bool, str]:
        """ホスト名がポリシーで許可されているか判定する。
        deny list → allow list → default deny の順で評価。
        ホスト名は小文字に正規化してからマッチする（DNSはcase-insensitive）。
        """
        host = host.lower()

        for pattern in self.deny_list:
            p = pattern.lower()
            if fnmatch(host, p) or (p.startswith("*.") and host == p[2:]):
                return False, f"denied by pattern: {pattern}"

        for pattern in self.allow_list:
            p = pattern.lower()
            if fnmatch(host, p) or (p.startswith("*.") and host == p[2:]):
                return True, ""

        return False, "not in allow list"
