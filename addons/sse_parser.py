"""SSE (Server-Sent Events) parsers for extracting tool_use from LLM API responses.

Pure Python, no mitmproxy dependency.
BaseSSEParser defines the interface; provider-specific parsers implement it.

Currently supported:
- AnthropicSSEParser: Anthropic API (content_block_start/delta/stop)

Planned:
- OpenAISSEParser: OpenAI API (tool_calls in delta) — see ROADMAP.md
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ToolUse:
    """Provider-agnostic representation of a tool invocation."""
    name: str
    input: str
    input_size: int


class BaseSSEParser(ABC):
    """SSEストリームからtool_useを抽出する共通インターフェース。

    Usage:
        parser = AnthropicSSEParser()  # or OpenAISSEParser()
        parser.feed(chunk)
        for tool_use in parser.drain_completed():
            print(tool_use.name, tool_use.input)
    """

    MAX_LINE_BUF = 1024 * 1024  # 1MB

    def __init__(self):
        self._line_buf = b""
        self._event_lines: list[str] = []
        self._completed: list[ToolUse] = []

    def feed(self, chunk: bytes) -> None:
        """Feed a chunk of SSE data. May contain partial lines."""
        if not chunk:
            return

        self._line_buf += chunk

        if len(self._line_buf) > self.MAX_LINE_BUF:
            logger.warning(f"SSE line buffer exceeded {self.MAX_LINE_BUF} bytes, discarding")
            self._line_buf = b""
            self._event_lines = []

        while b"\n" in self._line_buf:
            line_bytes, self._line_buf = self._line_buf.split(b"\n", 1)
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")

            if line == "":
                self._process_event(self._event_lines)
                self._event_lines = []
            else:
                self._event_lines.append(line)

    def _process_event(self, lines: list[str]) -> None:
        """Parse SSE event lines and dispatch to provider-specific handler."""
        if not lines:
            return

        data_parts = []
        for line in lines:
            if line.startswith(":"):
                continue
            if line.startswith("data: "):
                data_parts.append(line[6:])
            elif line.startswith("data:"):
                data_parts.append(line[5:])

        if not data_parts:
            return

        data_str = "\n".join(data_parts)
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return

        self._handle_data(data)

    @abstractmethod
    def _handle_data(self, data: dict) -> None:
        """Provider-specific: process a parsed SSE data object."""
        ...

    def drain_completed(self) -> list[ToolUse]:
        """Return and clear all completed tool_use extractions."""
        results = self._completed
        self._completed = []
        return results


class AnthropicSSEParser(BaseSSEParser):
    """Anthropic API SSE format parser.

    Events: content_block_start → content_block_delta → content_block_stop
    """

    def __init__(self):
        super().__init__()
        self._active_tools: dict[int, dict] = {}

    def _handle_data(self, data: dict) -> None:
        event_type = data.get("type", "")

        if event_type == "content_block_start":
            block = data.get("content_block", {})
            if block.get("type") == "tool_use":
                index = data.get("index")
                if index is None:
                    return
                self._active_tools[index] = {
                    "name": block.get("name", ""),
                    "id": block.get("id", ""),
                    "partial_json_parts": [],
                }

        elif event_type == "content_block_delta":
            index = data.get("index")
            delta = data.get("delta", {})
            if index is not None and delta.get("type") == "input_json_delta" and index in self._active_tools:
                self._active_tools[index]["partial_json_parts"].append(
                    delta.get("partial_json", "")
                )

        elif event_type == "content_block_stop":
            index = data.get("index")
            if index is not None and index in self._active_tools:
                tool = self._active_tools.pop(index)
                full_json = "".join(tool["partial_json_parts"])
                self._completed.append(
                    ToolUse(
                        name=tool["name"],
                        input=full_json,
                        input_size=len(full_json),
                    )
                )

        elif event_type == "message_stop":
            self._active_tools.clear()


# 後方互換エイリアス
SSEToolUseBuffer = AnthropicSSEParser
