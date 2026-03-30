"""Tests for addons/sse_parser.py - SSE tool_use extraction state machine."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addons.sse_parser import SSEToolUseBuffer

# Anthropic API の実際のSSEフォーマットに基づくテストデータ
SSE_TOOL_USE_COMPLETE = (
    b'event: content_block_start\n'
    b'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_01ABC","name":"Bash","input":{}}}\n'
    b'\n'
    b'event: content_block_delta\n'
    b'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"command\\": \\"ls -la\\"}"}}\n'
    b'\n'
    b'event: content_block_stop\n'
    b'data: {"type":"content_block_stop","index":1}\n'
    b'\n'
)

SSE_TEXT_BLOCK = (
    b'event: content_block_start\n'
    b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n'
    b'\n'
    b'event: content_block_delta\n'
    b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello world"}}\n'
    b'\n'
    b'event: content_block_stop\n'
    b'data: {"type":"content_block_stop","index":0}\n'
    b'\n'
)

SSE_MULTI_DELTA = (
    b'event: content_block_start\n'
    b'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_02DEF","name":"Read","input":{}}}\n'
    b'\n'
    b'event: content_block_delta\n'
    b'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"file_path\\": \\"/"}}\n'
    b'\n'
    b'event: content_block_delta\n'
    b'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"tmp/test.txt\\"}"}}\n'
    b'\n'
    b'event: content_block_stop\n'
    b'data: {"type":"content_block_stop","index":1}\n'
    b'\n'
)


class TestSSEToolUseComplete(unittest.TestCase):
    def test_single_tool_use(self):
        """完全なtool_useイベントシーケンスで1件取得"""
        buf = SSEToolUseBuffer()
        buf.feed(SSE_TOOL_USE_COMPLETE)
        results = buf.drain_completed()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Bash")
        self.assertIn("ls -la", results[0].input)

    def test_text_block_ignored(self):
        """type=textのcontent_blockは無視される"""
        buf = SSEToolUseBuffer()
        buf.feed(SSE_TEXT_BLOCK)
        results = buf.drain_completed()
        self.assertEqual(len(results), 0)

    def test_multiple_tool_uses(self):
        """テキストブロック + tool_useの連続"""
        buf = SSEToolUseBuffer()
        buf.feed(SSE_TEXT_BLOCK + SSE_TOOL_USE_COMPLETE)
        results = buf.drain_completed()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Bash")

    def test_multi_delta_accumulation(self):
        """input_json_deltaが複数チャンクに分割されたtool_use"""
        buf = SSEToolUseBuffer()
        buf.feed(SSE_MULTI_DELTA)
        results = buf.drain_completed()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Read")
        self.assertIn("/tmp/test.txt", results[0].input)


class TestChunkBoundary(unittest.TestCase):
    def test_split_across_chunks(self):
        """SSEデータがチャンク境界を跨いで分割される"""
        buf = SSEToolUseBuffer()
        data = SSE_TOOL_USE_COMPLETE
        mid = len(data) // 2
        buf.feed(data[:mid])
        buf.feed(data[mid:])
        results = buf.drain_completed()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Bash")

    def test_byte_by_byte(self):
        """1バイトずつ送っても正しくパースできる"""
        buf = SSEToolUseBuffer()
        for byte in SSE_TOOL_USE_COMPLETE:
            buf.feed(bytes([byte]))
        results = buf.drain_completed()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Bash")

    def test_empty_chunk(self):
        """空チャンクでエラーにならない"""
        buf = SSEToolUseBuffer()
        buf.feed(b"")
        results = buf.drain_completed()
        self.assertEqual(len(results), 0)


class TestEdgeCases(unittest.TestCase):
    def test_malformed_json_no_crash(self):
        """JSONパース失敗でもクラッシュしない"""
        data = (
            b'event: content_block_start\n'
            b'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_bad","name":"Bash","input":{}}}\n'
            b'\n'
            b'event: content_block_delta\n'
            b'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{broken json"}}\n'
            b'\n'
            b'event: content_block_stop\n'
            b'data: {"type":"content_block_stop","index":1}\n'
            b'\n'
        )
        buf = SSEToolUseBuffer()
        buf.feed(data)
        results = buf.drain_completed()
        # パース失敗でも結果は返る（inputは生のpartial_json文字列）
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Bash")

    def test_message_stop_resets_state(self):
        """message_stopでステートがリセットされる"""
        data = (
            SSE_TOOL_USE_COMPLETE
            + b'event: message_stop\n'
            b'data: {"type":"message_stop"}\n'
            b'\n'
        )
        buf = SSEToolUseBuffer()
        buf.feed(data)
        results = buf.drain_completed()
        self.assertEqual(len(results), 1)

        # 次のメッセージでも正常動作
        buf.feed(SSE_TOOL_USE_COMPLETE)
        results = buf.drain_completed()
        self.assertEqual(len(results), 1)

    def test_drain_clears_queue(self):
        """drain_completed()後はキューが空になる"""
        buf = SSEToolUseBuffer()
        buf.feed(SSE_TOOL_USE_COMPLETE)
        results1 = buf.drain_completed()
        self.assertEqual(len(results1), 1)
        results2 = buf.drain_completed()
        self.assertEqual(len(results2), 0)

    def test_input_size_tracked(self):
        """tool_useのinput_sizeが記録される"""
        buf = SSEToolUseBuffer()
        buf.feed(SSE_TOOL_USE_COMPLETE)
        results = buf.drain_completed()
        self.assertGreater(results[0].input_size, 0)

    def test_comment_lines_ignored(self):
        """SSEコメント行（:で始まる）は無視される"""
        data = (
            b': this is a comment\n'
            b'\n'
            + SSE_TOOL_USE_COMPLETE
        )
        buf = SSEToolUseBuffer()
        buf.feed(data)
        results = buf.drain_completed()
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
