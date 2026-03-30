"""Policy engine for agent-harness. Pure logic, no mitmproxy dependency."""

import logging
import re
import time
import tomllib
from collections import deque
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    type: str
    detail: str


class PolicyEngine:
    def __init__(self, policy_path: str):
        self.policy_path = Path(policy_path)
        self._mtime: float = 0.0
        self.allow_list: list[str] = []
        self.deny_list: list[str] = []
        self.db_path: str = ""
        self.rate_limits: dict[str, dict] = {}
        self.block_patterns: list[re.Pattern] = []
        self.secret_patterns: list[re.Pattern] = []
        self.suspicious_tools: list[str] = []
        self.suspicious_args: list[str] = []
        self.tool_arg_size_alert: int = 0
        # レート制限の内部状態（ホットリロードでもリセットしない）
        self._rate_windows: dict[str, deque] = {}
        self._burst_windows: dict[str, deque] = {}
        self._load()

    def _load(self):
        with open(self.policy_path, "rb") as f:
            policy = tomllib.load(f)
        self._mtime = self.policy_path.stat().st_mtime

        domains = policy.get("domains", {})
        self.allow_list = domains.get("allow", {}).get("list", [])
        self.deny_list = domains.get("deny", {}).get("list", [])
        self.db_path = policy.get("general", {}).get("log_db", "/data/harness.db")

        # レート制限
        self.rate_limits = policy.get("rate_limits", {})

        # ペイロードルール
        payload_rules = policy.get("payload_rules", {})
        self.block_patterns = self._compile_patterns(
            payload_rules.get("block_patterns", [])
        )
        self.secret_patterns = self._compile_patterns(
            payload_rules.get("secret_patterns", [])
        )

        # アラート設定
        alerts_config = policy.get("alerts", {})
        self.suspicious_tools = alerts_config.get("suspicious_tools", [])
        self.suspicious_args = alerts_config.get("suspicious_args", [])
        self.tool_arg_size_alert = alerts_config.get("tool_arg_size_alert", 0)

    @staticmethod
    def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(p))
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{p}': {e}")
        return compiled

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

    def check_rate_limit(self, host: str) -> tuple[bool, str]:
        """ドメインのレート制限をチェックする。
        2段階ウィンドウ: 60秒RPM + 1秒burst。
        (True, "") = 許可, (False, reason) = ブロック。
        """
        config = self.rate_limits.get(host)
        if not config:
            return True, ""

        now = time.time()
        rpm = config.get("rpm", 60)
        burst = config.get("burst", rpm)

        # RPMウィンドウ（60秒）
        if host not in self._rate_windows:
            self._rate_windows[host] = deque()
        rpm_window = self._rate_windows[host]

        # 60秒より古いエントリを除去
        while rpm_window and rpm_window[0] < now - 60:
            rpm_window.popleft()

        if len(rpm_window) >= rpm:
            return False, f"rate limit exceeded: {len(rpm_window)}/{rpm} rpm for {host}"

        # Burstウィンドウ（1秒）
        if host not in self._burst_windows:
            self._burst_windows[host] = deque()
        burst_window = self._burst_windows[host]

        while burst_window and burst_window[0] < now - 1:
            burst_window.popleft()

        if len(burst_window) >= burst:
            return False, f"burst limit exceeded: {len(burst_window)}/{burst} per second for {host}"

        # 両方のウィンドウに記録
        rpm_window.append(now)
        burst_window.append(now)
        return True, ""

    def check_payload(self, body: bytes | None) -> tuple[bool, str]:
        """リクエストボディに危険パターンや機密情報が含まれていないかチェックする。
        (True, reason) = ブロック, (False, "") = 通過。
        """
        if not body:
            return False, ""

        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return False, ""

        for pattern in self.block_patterns:
            if pattern.search(text):
                return True, f"block_pattern matched: {pattern.pattern}"

        for pattern in self.secret_patterns:
            if pattern.search(text):
                return True, f"secret_pattern matched: {pattern.pattern}"

        return False, ""

    def check_tool_use(
        self, tool_name: str, input_str: str, input_size: int
    ) -> list[Alert]:
        """tool_useに対してアラートチェックを行う。"""
        if not self.suspicious_tools and not self.suspicious_args and not self.tool_arg_size_alert:
            return []

        alerts: list[Alert] = []

        if self.tool_arg_size_alert and input_size > self.tool_arg_size_alert:
            alerts.append(
                Alert("tool_arg_size", f"{tool_name}: input_size={input_size} > {self.tool_arg_size_alert}")
            )

        if tool_name in self.suspicious_tools:
            alerts.append(
                Alert("suspicious_tool", f"suspicious tool: {tool_name}")
            )

        for pattern in self.suspicious_args:
            if pattern in input_str:
                alerts.append(
                    Alert("suspicious_arg", f"suspicious arg '{pattern}' in {tool_name}")
                )

        return alerts
