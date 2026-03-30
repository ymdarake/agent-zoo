"""SSE (Server-Sent Events) parser for extracting tool_use from Anthropic API responses.

Pure Python, no mitmproxy dependency. Designed to process chunked SSE data
from streaming API responses and extract tool_use blocks.

SSE format from Anthropic API:
  event: content_block_start
  data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"...","name":"Bash","input":{}}}

  event: content_block_delta
  data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"..."}}

  event: content_block_stop
  data: {"type":"content_block_stop","index":1}
"""

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ToolUse:
    name: str
    input: str
    input_size: int


class SSEToolUseBuffer:
    """Stateful SSE parser that accumulates chunked data and extracts tool_use blocks.

    Usage:
        buf = SSEToolUseBuffer()
        buf.feed(chunk1)  # bytes from streaming response
        buf.feed(chunk2)
        for tool_use in buf.drain_completed():
            print(tool_use.name, tool_use.input)
    """

    MAX_LINE_BUF = 1024 * 1024  # 1MB

    def __init__(self):
        self._line_buf = b""
        self._event_lines: list[str] = []
        self._completed: list[ToolUse] = []
        # Per-index tracking of active tool_use blocks
        self._active_tools: dict[int, dict] = {}

    def feed(self, chunk: bytes) -> None:
        """Feed a chunk of SSE data. May contain partial lines."""
        if not chunk:
            return

        self._line_buf += chunk

        # バッファサイズ上限チェック（改行なしの巨大データ対策）
        if len(self._line_buf) > self.MAX_LINE_BUF:
            logger.warning(f"SSE line buffer exceeded {self.MAX_LINE_BUF} bytes, discarding")
            self._line_buf = b""
            self._event_lines = []

        # Process complete lines (separated by \n)
        while b"\n" in self._line_buf:
            line_bytes, self._line_buf = self._line_buf.split(b"\n", 1)
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")

            if line == "":
                # Empty line = end of SSE event
                self._process_event(self._event_lines)
                self._event_lines = []
            else:
                self._event_lines.append(line)

    def _process_event(self, lines: list[str]) -> None:
        """Process a complete SSE event (lines between blank lines)."""
        if not lines:
            return

        data_parts = []
        for line in lines:
            if line.startswith(":"):
                continue  # SSE comment
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

        event_type = data.get("type", "")
        self._handle_event(event_type, data)

    def _handle_event(self, event_type: str, data: dict) -> None:
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

    def drain_completed(self) -> list[ToolUse]:
        """Return and clear all completed tool_use extractions."""
        results = self._completed
        self._completed = []
        return results
