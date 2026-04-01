"""Compatibility wrapper for the OpenAI SSE parser."""

try:
    from addons.sse_parser import OpenAISSEParser
except ImportError:  # pragma: no cover - mitmproxy path import
    from sse_parser import OpenAISSEParser

__all__ = ["OpenAISSEParser"]
