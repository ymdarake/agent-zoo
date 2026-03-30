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
        self.alert_rules: list[dict] = []
        self.max_tool_input_store: int = 0
        self.log_retention_days: int = 0
        self.tool_use_block_tools: list[str] = []
        self.tool_use_block_args: list[str] = []
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
            payload_rules.get("secret_patterns", []), flags=re.IGNORECASE
        )

        # アラート設定
        alerts_config = policy.get("alerts", {})
        self.suspicious_tools = alerts_config.get("suspicious_tools", [])
        self.suspicious_args = alerts_config.get("suspicious_args", [])
        self.tool_arg_size_alert = alerts_config.get("tool_arg_size_alert", 0)
        self.alert_rules = alerts_config.get("rules", [])
        self.max_tool_input_store = policy.get("general", {}).get("max_tool_input_store", 0)
        self.log_retention_days = policy.get("general", {}).get("log_retention_days", 0)

        # tool_useブロックルール
        tool_use_rules = policy.get("tool_use_rules", {})
        self.tool_use_block_tools = tool_use_rules.get("block_tools", [])
        self.tool_use_block_args = tool_use_rules.get("block_args", [])

    @staticmethod
    def _compile_patterns(
        patterns: list[str], flags: int = 0
    ) -> list[re.Pattern]:
        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, flags))
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
        host = host.lower()
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
        平文チェック後、URLデコード→Base64デコードの順で再検査する（1段階のみ）。
        """
        if not body:
            return False, ""

        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            logger.debug("Payload is not UTF-8, skipping text pattern check")
            return False, ""

        # 1. 平文チェック
        result = self._match_patterns(text)
        if result:
            return True, result

        # 2. URLデコード → 再検査
        url_decoded = self._try_url_decode(text)
        if url_decoded and url_decoded != text:
            result = self._match_patterns(url_decoded)
            if result:
                return True, f"decoded(url): {result}"

        # 3. Base64デコード → 再検査（URLデコード後のテキストから検出）
        source = url_decoded or text
        for decoded in self._extract_base64(source):
            result = self._match_patterns(decoded)
            if result:
                return True, f"decoded(base64): {result}"

        return False, ""

    def _match_patterns(self, text: str) -> str:
        """block_patterns/secret_patternsに対してマッチングし、マッチしたら理由を返す。"""
        for pattern in self.block_patterns:
            if pattern.search(text):
                return f"block_pattern matched: {pattern.pattern}"
        for pattern in self.secret_patterns:
            if pattern.search(text):
                return f"secret_pattern matched: {pattern.pattern}"
        return ""

    @staticmethod
    def _try_url_decode(text: str) -> str | None:
        """URLエンコードされた文字列をデコードする。変化がなければNone。"""
        from urllib.parse import unquote
        try:
            decoded = unquote(text)
            return decoded if decoded != text else None
        except Exception:
            return None

    @staticmethod
    def _extract_base64(text: str) -> list[str]:
        """テキスト内のBase64候補文字列をデコードして返す。"""
        import base64 as b64mod
        results = []
        # Base64候補を検出: 境界（引用符/スペース/行頭行末）で区切られた16文字以上
        # 誤検知防止のため上限10候補まで
        count = 0
        for match in re.finditer(r'(?:^|[\s"\'=:,])([A-Za-z0-9+/]{16,}={0,2})(?:$|[\s"\'=:,])', text):
            candidate = match.group(1)
            try:
                decoded_bytes = b64mod.b64decode(candidate, validate=True)
                decoded_str = decoded_bytes.decode("utf-8")
                results.append(decoded_str)
            except Exception:
                continue
            count += 1
            if count >= 10:
                break
        return results

    def check_tool_use(
        self, tool_name: str, input_str: str, input_size: int
    ) -> list[Alert]:
        """tool_useに対してアラートチェックを行う。"""
        if not self.suspicious_tools and not self.suspicious_args and not self.tool_arg_size_alert and not self.alert_rules:
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
            if self._match_word_boundary(pattern, input_str):
                alerts.append(
                    Alert("suspicious_arg", f"suspicious arg '{pattern}' in {tool_name}")
                )

        # 組み合わせ条件ルール（各ルール内はAND、ルール間はOR）
        for rule in self.alert_rules:
            rule_name = rule.get("name", "unnamed")
            tools = rule.get("tools") or []
            args = rule.get("args") or []
            min_size = rule.get("min_size")

            # 条件が1つもないルールはスキップ（無条件発火を防止）
            if not tools and not args and min_size is None:
                continue

            # tools条件（空=全ツール対象、非空=いずれかにマッチ）
            if tools and tool_name not in tools:
                continue

            # min_size条件（超過で発火）
            if min_size is not None and input_size <= min_size:
                continue

            # args条件（空=引数条件なし、非空=いずれかにワード境界マッチ）
            if args and not self._match_any_word_boundary(args, input_str):
                continue

            # 全条件にマッチ
            alerts.append(
                Alert("rule_match", f"Rule '{rule_name}' matched for {tool_name}")
            )

        return alerts

    @staticmethod
    def _match_word_boundary(pattern: str, text: str) -> bool:
        """パターンがテキスト内にワード境界付きで存在するか。"""
        escaped = re.escape(pattern)
        return bool(re.search(rf'(?:^|[^a-zA-Z0-9_]){escaped}(?:$|[^a-zA-Z0-9_])', text))

    @staticmethod
    def _match_any_word_boundary(patterns: list[str], text: str) -> bool:
        """パターンリストのいずれかがワード境界付きでマッチするか。"""
        for pattern in patterns:
            escaped = re.escape(pattern)
            if re.search(rf'(?:^|[^a-zA-Z0-9_]){escaped}(?:$|[^a-zA-Z0-9_])', text):
                return True
        return False

    def should_block_tool_use(self, tool_name: str, input_str: str) -> tuple[bool, str]:
        """tool_useをブロックすべきか判定する。
        (True, reason) = ブロック, (False, "") = 通過。
        """
        if not self.tool_use_block_tools and not self.tool_use_block_args:
            return False, ""

        if tool_name in self.tool_use_block_tools:
            return True, f"tool blocked: {tool_name}"

        for pattern in self.tool_use_block_args:
            if pattern in input_str:
                return True, f"tool_use arg blocked: '{pattern}' in {tool_name}"

        return False, ""
