"""Streaming parsers for extracting tool_use from LLM API responses.

Pure Python, no mitmproxy dependency.
BaseSSEParser defines the SSE interface; provider-specific parsers implement it.

Currently supported:
- AnthropicSSEParser: Anthropic API (content_block_start/delta/stop)
- OpenAISSEParser: OpenAI API (tool_calls in delta)
- OpenAIResponsesStreamParser: OpenAI Responses semantic events
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

        event_name = ""
        data_parts = []
        for line in lines:
            if line.startswith(":"):
                continue
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("event:"):
                event_name = line[6:]
            elif line.startswith("data: "):
                data_parts.append(line[6:])
            elif line.startswith("data:"):
                data_parts.append(line[5:])

        if not data_parts:
            return

        data_str = "\n".join(data_parts)
        if data_str == "[DONE]":
            self._handle_done(event_name)
            return

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return

        self._handle_data(event_name, data)

    @abstractmethod
    def _handle_data(self, event_name: str, data: dict) -> None:
        """Provider-specific: process a parsed SSE data object.
        event_name: SSEのevent:フィールド（空の場合あり）
        data: パース済みJSONオブジェクト
        """
        ...

    def _handle_done(self, event_name: str) -> None:
        """Provider-specific hook for non-JSON sentinels such as OpenAI's [DONE]."""
        return

    def drain_completed(self) -> list[ToolUse]:
        """Return and clear all completed tool_use extractions."""
        results = self._completed
        self._completed = []
        return results

    def reset(self) -> None:
        """全状態をリセット。ストリーム切断時等に呼び出す。"""
        self._line_buf = b""
        self._event_lines = []
        self._completed = []


class AnthropicSSEParser(BaseSSEParser):
    """Anthropic API SSE format parser.

    Events: content_block_start → content_block_delta → content_block_stop
    """

    def __init__(self):
        super().__init__()
        self._active_tools: dict[int, dict] = {}

    def _handle_data(self, event_name: str, data: dict) -> None:
        # Anthropic APIはdata内のtypeフィールドでイベント種別を判定
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

    def reset(self) -> None:
        super().reset()
        self._active_tools.clear()


class OpenAISSEParser(BaseSSEParser):
    """OpenAI API SSE format parser.

    OpenAI streams tool calls inside `choices[].delta.tool_calls[]` and sends
    `finish_reason == "tool_calls"` once all tool invocations are complete.
    """

    def __init__(self):
        super().__init__()
        self._active_tool_calls: dict[int, dict] = {}

    def _handle_data(self, event_name: str, data: dict) -> None:
        choices = data.get("choices", [])
        if not isinstance(choices, list):
            return

        for choice in choices:
            if not isinstance(choice, dict):
                continue

            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                delta = {}

            tool_calls = delta.get("tool_calls", [])
            if not isinstance(tool_calls, list):
                tool_calls = []

            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue

                index = tool_call.get("index")
                if not isinstance(index, int):
                    continue

                state = self._active_tool_calls.setdefault(
                    index,
                    {"name": "", "arguments_parts": []},
                )

                function = tool_call.get("function", {})
                if not isinstance(function, dict):
                    function = {}

                name = function.get("name")
                if isinstance(name, str) and name:
                    state["name"] = name

                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    state["arguments_parts"].append(arguments)

            if choice.get("finish_reason") == "tool_calls":
                self._complete_active_tool_calls()

    def _handle_done(self, event_name: str) -> None:
        self._active_tool_calls.clear()

    def _complete_active_tool_calls(self) -> None:
        for index in sorted(self._active_tool_calls):
            tool = self._active_tool_calls[index]
            arguments = "".join(tool["arguments_parts"])
            self._completed.append(
                ToolUse(
                    name=tool["name"],
                    input=arguments,
                    input_size=len(arguments),
                )
            )
        self._active_tool_calls.clear()

    def reset(self) -> None:
        super().reset()
        self._active_tool_calls.clear()


def create_sse_parser_for_host(host: str) -> BaseSSEParser:
    """Return the provider-specific SSE parser for the target host."""
    host = (host or "").lower()
    if host == "api.openai.com" or host.endswith(".api.openai.com"):
        return OpenAISSEParser()
    return AnthropicSSEParser()


class OpenAIResponsesStreamParser:
    """Parser for OpenAI Responses semantic streaming events.

    Codex on chatgpt.com currently streams over WebSockets and emits the same
    typed response events documented for the Responses API.
    """

    def __init__(self):
        self._active_tool_calls: dict[str, dict] = {}
        self._completed_ids: set[str] = set()
        self._completed: list[ToolUse] = []

    def feed_event(self, event: dict) -> None:
        if not isinstance(event, dict):
            return

        event_type = event.get("type", "")

        if event_type == "response.output_item.added":
            self._remember_item(event.get("item", {}))

        elif event_type == "response.function_call_arguments.delta":
            self._append_delta(event.get("item_id"), event.get("delta", ""))

        elif event_type == "response.function_call_arguments.done":
            self._complete_item(
                item_id=event.get("item_id"),
                name=event.get("name"),
                arguments=event.get("arguments", ""),
            )

        elif event_type == "response.mcp_call_arguments.delta":
            self._append_delta(event.get("item_id"), event.get("delta", ""))

        elif event_type == "response.mcp_call_arguments.done":
            item_id = event.get("item_id")
            if not isinstance(item_id, str) or not item_id:
                return
            state = self._active_tool_calls.setdefault(
                item_id,
                {"name": "", "arguments": ""},
            )
            arguments = event.get("arguments", "")
            if isinstance(arguments, str):
                state["arguments"] = arguments
            if state["name"]:
                self._complete_item(
                    item_id=item_id,
                    name=state["name"],
                    arguments=state["arguments"],
                )

        elif event_type == "response.output_item.done":
            item = event.get("item", {})
            self._remember_item(item)
            self._complete_from_item(item)

        elif event_type in ("response.completed", "response.done"):
            response = event.get("response", {})
            if isinstance(response, dict):
                for item in response.get("output", []):
                    self._remember_item(item)
                    self._complete_from_item(item)
            self._active_tool_calls.clear()

    def _remember_item(self, item: dict) -> None:
        if not isinstance(item, dict):
            return

        item_type = item.get("type", "")
        if item_type not in ("function_call", "mcp_call"):
            return

        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            return

        state = self._active_tool_calls.setdefault(
            item_id,
            {"name": "", "arguments": ""},
        )

        name = item.get("name")
        if isinstance(name, str) and name:
            state["name"] = name

        arguments = item.get("arguments")
        if isinstance(arguments, str):
            state["arguments"] = arguments

    def _append_delta(self, item_id: str | None, delta: str) -> None:
        if not isinstance(item_id, str) or not item_id:
            return
        if not isinstance(delta, str):
            return

        state = self._active_tool_calls.setdefault(
            item_id,
            {"name": "", "arguments": ""},
        )
        state["arguments"] += delta

    def _complete_from_item(self, item: dict) -> None:
        if not isinstance(item, dict):
            return

        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            return

        item_type = item.get("type", "")
        if item_type not in ("function_call", "mcp_call"):
            return

        self._complete_item(
            item_id=item_id,
            name=item.get("name"),
            arguments=item.get("arguments", ""),
        )

    def _complete_item(
        self,
        item_id: str | None,
        name: str | None,
        arguments: str | None,
    ) -> None:
        if not isinstance(item_id, str) or not item_id:
            return
        if item_id in self._completed_ids:
            return

        state = self._active_tool_calls.setdefault(
            item_id,
            {"name": "", "arguments": ""},
        )

        if isinstance(name, str) and name:
            state["name"] = name
        if isinstance(arguments, str):
            state["arguments"] = arguments

        if not state["name"]:
            return

        self._completed.append(
            ToolUse(
                name=state["name"],
                input=state["arguments"],
                input_size=len(state["arguments"]),
            )
        )
        self._completed_ids.add(item_id)
        self._active_tool_calls.pop(item_id, None)

    def drain_completed(self) -> list[ToolUse]:
        results = self._completed
        self._completed = []
        return results

    def reset(self) -> None:
        self._active_tool_calls = {}
        self._completed_ids = set()
        self._completed = []
