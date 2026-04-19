"""Sprint 007 PR G: dashboard `ASSET_VERSION` config の default テスト。

ADR 0004 (Dashboard 外部依存ゼロ化) の cache busting 設計。
PR H で template に `?v={{ asset_version }}` を埋め込むため、
default が `""` (空文字) で Jinja UndefinedError を起こさないことを保証する。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import app


class TestAssetVersion(unittest.TestCase):
    def test_default_asset_version_is_empty_string(self) -> None:
        """env 未設定時、`ASSET_VERSION` config は空文字。"""
        # SECRET_KEY と同様の env-driven pattern を採用。
        # default は空文字、PR I で git short sha 等を入れる。
        self.assertEqual(app.config.get("ASSET_VERSION", "MISSING"), "")

    def test_asset_version_can_be_overridden(self) -> None:
        """test 中の上書き → 復元が壊れない (Plan review #6: pop ベース復元)。"""
        had_key = "ASSET_VERSION" in app.config
        old = app.config.get("ASSET_VERSION")
        try:
            app.config["ASSET_VERSION"] = "abc123"
            self.assertEqual(app.config["ASSET_VERSION"], "abc123")
        finally:
            if had_key:
                app.config["ASSET_VERSION"] = old
            else:
                app.config.pop("ASSET_VERSION", None)


if __name__ == "__main__":
    unittest.main()
