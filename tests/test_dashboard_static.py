"""Sprint 007 PR G: dashboard 自前 static (CSS / JS) の Flask 配信テスト。

ADR 0004 (Dashboard 外部依存ゼロ化) の基盤レイヤー。
template への link 追加は PR H で行う。本テストは「ファイルが配信される」
「pseudo-code Critical 要素が抜けていない」を保証する。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import app


class TestStaticAssets(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def test_app_css_served(self) -> None:
        """`/static/app.css` が 200 + text/css MIME で配信される。"""
        rv = self.client.get("/static/app.css")
        self.assertEqual(rv.status_code, 200)
        self.assertTrue(
            rv.headers["Content-Type"].startswith("text/css"),
            rv.headers["Content-Type"],
        )
        # design token が含まれる sanity check
        self.assertIn(b"--color-primary", rv.data)
        self.assertIn(b"--color-text", rv.data)
        self.assertIn(b"--badge-blocked-bg", rv.data)
        self.assertIn(b".layout-container", rv.data)
        self.assertIn(b".status-BLOCKED", rv.data)

    def test_app_js_served(self) -> None:
        """`/static/app.js` が 200 で配信され、Rev.4 Critical 要素が抜けていない。"""
        rv = self.client.get("/static/app.js")
        self.assertEqual(rv.status_code, 200)
        # Plan review (Claude) #1: pseudo-code Critical 要素が抜け落ちた状態で
        # merge されないよう、識別子の含有を assert する。
        for ident in (
            b"data-poll-url",
            b"data-swap-target",
            b"setupPolls",
            b"X-CSRFToken",
            b"MutationObserver",
            b"removedNodes",
            b"_pollTimers",
            b"document.hidden",
            # Plan H 追加: bulk toggle-all delegation + triggerFrom 重複 attach 修正
            b"data-bulk-toggle-all",
            b"_triggerListenersByTarget",
            b"aria-selected",
        ):
            self.assertIn(ident, rv.data, f"missing required identifier: {ident!r}")

    def test_app_js_csrf_helper_reads_meta_each_call(self) -> None:
        """Gemini レビュー G1: CSRF token を毎回 meta から読む実装が含まれる。"""
        rv = self.client.get("/static/app.js")
        # `csrf` 関数 + `meta[name="csrf-token"]` の参照が source に存在
        self.assertIn(b'meta[name="csrf-token"]', rv.data)


if __name__ == "__main__":
    unittest.main()
