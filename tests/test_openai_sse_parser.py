"""Tests for OpenAI SSE tool call extraction."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.openai_sse_parser import OpenAISSEParser
from addons.sse_parser import BaseSSEParser, create_sse_parser_for_host

def _sse_json(data: dict) -> bytes:
    return f"data: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


SSE_TOOL_CALL_COMPLETE = (
    _sse_json(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": "bash", "arguments": ""},
                            }
                        ]
                    }
                }
            ]
        }
    )
    + _sse_json(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '{"command":'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    + _sse_json(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ' "ls -la"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )
    + b"data: [DONE]\n\n"
)

SSE_MULTI_TOOL_CALLS = (
    _sse_json(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/',
                                },
                            },
                            {
                                "index": 1,
                                "id": "call_2",
                                "type": "function",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"command": "echo ',
                                },
                            },
                        ]
                    }
                }
            ]
        }
    )
    + _sse_json(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": 'a.txt"}'},
                            },
                            {
                                "index": 1,
                                "function": {"arguments": 'hello"}'},
                            },
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )
)

SSE_DONE_ONLY = b"data: [DONE]\n\n"


class TestOpenAISSEParser(unittest.TestCase):
    def test_single_tool_call(self):
        parser = OpenAISSEParser()
        parser.feed(SSE_TOOL_CALL_COMPLETE)

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "bash")
        self.assertEqual(results[0].input, '{"command": "ls -la"}')
        self.assertEqual(results[0].input_size, len('{"command": "ls -la"}'))

    def test_multiple_tool_calls_complete_together(self):
        parser = OpenAISSEParser()
        parser.feed(SSE_MULTI_TOOL_CALLS)

        results = parser.drain_completed()

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].name, "read_file")
        self.assertEqual(results[0].input, '{"path": "/tmp/a.txt"}')
        self.assertEqual(results[1].name, "bash")
        self.assertEqual(results[1].input, '{"command": "echo hello"}')

    def test_chunk_boundary_split(self):
        parser = OpenAISSEParser()
        midpoint = len(SSE_TOOL_CALL_COMPLETE) // 2

        parser.feed(SSE_TOOL_CALL_COMPLETE[:midpoint])
        parser.feed(SSE_TOOL_CALL_COMPLETE[midpoint:])

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "bash")

    def test_byte_by_byte(self):
        parser = OpenAISSEParser()

        for byte in SSE_TOOL_CALL_COMPLETE:
            parser.feed(bytes([byte]))

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].input, '{"command": "ls -la"}')

    def test_done_without_tool_calls(self):
        parser = OpenAISSEParser()
        parser.feed(SSE_DONE_ONLY)

        self.assertEqual(parser.drain_completed(), [])

    def test_malformed_json_no_crash(self):
        parser = OpenAISSEParser()
        parser.feed(
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"oops"}}]}}\n\n'
        )
        parser.feed(SSE_TOOL_CALL_COMPLETE)

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "bash")

    def test_reset_clears_active_state(self):
        parser = OpenAISSEParser()
        parser.feed(
            _sse_json(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "name": "bash",
                                            "arguments": '{"command":',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
        )

        parser.reset()
        parser.feed(SSE_TOOL_CALL_COMPLETE)

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].input, '{"command": "ls -la"}')


class TestParserSelection(unittest.TestCase):
    def test_openai_host_selects_openai_parser(self):
        parser = create_sse_parser_for_host("api.openai.com")
        self.assertIsInstance(parser, OpenAISSEParser)
        self.assertIsInstance(parser, BaseSSEParser)

    def test_non_openai_host_defaults_to_anthropic_parser(self):
        parser = create_sse_parser_for_host("api.anthropic.com")
        self.assertNotIsInstance(parser, OpenAISSEParser)
        self.assertIsInstance(parser, BaseSSEParser)


if __name__ == "__main__":
    unittest.main()
