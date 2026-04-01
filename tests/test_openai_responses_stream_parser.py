"""Tests for OpenAI Responses streaming event parser."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.sse_parser import OpenAIResponsesStreamParser


class TestOpenAIResponsesStreamParser(unittest.TestCase):
    def test_function_call_stream(self):
        parser = OpenAIResponsesStreamParser()

        parser.feed_event(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": "fc_1",
                    "type": "function_call",
                    "name": "bash",
                    "arguments": "",
                },
            }
        )
        parser.feed_event(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": 0,
                "delta": '{"command":',
            }
        )
        parser.feed_event(
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_1",
                "output_index": 0,
                "name": "bash",
                "arguments": '{"command": "ls -la"}',
            }
        )

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "bash")
        self.assertEqual(results[0].input, '{"command": "ls -la"}')

    def test_mcp_call_stream(self):
        parser = OpenAIResponsesStreamParser()

        parser.feed_event(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": "mcp_1",
                    "type": "mcp_call",
                    "name": "Read",
                    "arguments": "",
                },
            }
        )
        parser.feed_event(
            {
                "type": "response.mcp_call_arguments.delta",
                "item_id": "mcp_1",
                "output_index": 0,
                "delta": '{"file_path": "/tmp/',
            }
        )
        parser.feed_event(
            {
                "type": "response.mcp_call_arguments.done",
                "item_id": "mcp_1",
                "output_index": 0,
                "arguments": '{"file_path": "/tmp/test.txt"}',
            }
        )

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Read")
        self.assertEqual(results[0].input, '{"file_path": "/tmp/test.txt"}')

    def test_output_item_done_fallback(self):
        parser = OpenAIResponsesStreamParser()

        parser.feed_event(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": "fc_2",
                    "type": "function_call",
                    "name": "grep",
                    "arguments": '{"pattern": "TODO"}',
                },
            }
        )

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "grep")
        self.assertEqual(results[0].input, '{"pattern": "TODO"}')

    def test_response_done_fallback(self):
        parser = OpenAIResponsesStreamParser()

        parser.feed_event(
            {
                "type": "response.done",
                "response": {
                    "output": [
                        {
                            "id": "mcp_2",
                            "type": "mcp_call",
                            "name": "Write",
                            "arguments": '{"path": "/tmp/x", "content": "ok"}',
                        }
                    ]
                },
            }
        )

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Write")

    def test_mcp_done_waits_for_name(self):
        parser = OpenAIResponsesStreamParser()

        parser.feed_event(
            {
                "type": "response.mcp_call_arguments.done",
                "item_id": "mcp_3",
                "output_index": 0,
                "arguments": '{"q": "docs"}',
            }
        )
        self.assertEqual(parser.drain_completed(), [])

        parser.feed_event(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": "mcp_3",
                    "type": "mcp_call",
                    "name": "SearchDocs",
                    "arguments": '{"q": "docs"}',
                },
            }
        )

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "SearchDocs")

    def test_duplicate_events_not_duplicated(self):
        parser = OpenAIResponsesStreamParser()

        event = {
            "type": "response.function_call_arguments.done",
            "item_id": "fc_3",
            "output_index": 0,
            "name": "bash",
            "arguments": '{"command": "pwd"}',
        }
        parser.feed_event(event)
        parser.feed_event(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": "fc_3",
                    "type": "function_call",
                    "name": "bash",
                    "arguments": '{"command": "pwd"}',
                },
            }
        )

        results = parser.drain_completed()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "bash")

    def test_reset_clears_state(self):
        parser = OpenAIResponsesStreamParser()
        parser.feed_event(
            {
                "type": "response.output_item.added",
                "item": {
                    "id": "fc_4",
                    "type": "function_call",
                    "name": "bash",
                    "arguments": '{"command":',
                },
            }
        )

        parser.reset()
        self.assertEqual(parser.drain_completed(), [])


if __name__ == "__main__":
    unittest.main()
