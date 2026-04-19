"""Sprint 007 PR H: dashboard template が inline JS / CSS を含まないことを保証。

ADR 0004 (Dashboard 外部依存ゼロ化) の必須要件。PR I の CSP 'self' only
厳格化の前提条件として、全 partial / index.html から:
  - <script>...</script> (inline body 持ち、外部 src のみ許可)
  - <style>...</style> (CDN 経由でも自前でも、element 自体禁止)
  - style="..." 属性 (CSP style-src-attr 'unsafe-inline' を要求)
  - onclick= / onsubmit= 等の inline event handler
を完全に削除する。

raw template grep ではなく Flask test client で render 後の HTML を
BeautifulSoup で parse することで、Jinja コメント等の false positive
を回避する (Plan F Gemini レビュー G4)。
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import app

bs4 = pytest.importorskip("bs4")
BeautifulSoup = bs4.BeautifulSoup


_INLINE_HANDLERS = (
    "onclick",
    "onsubmit",
    "onchange",
    "onload",
    "onerror",
    "onmouseover",
    "onmouseout",
    "onfocus",
    "onblur",
    "oninput",
    "onkeydown",
    "onkeyup",
    "onkeypress",
)


class _BaseInlineAssetsTest(unittest.TestCase):
    """共通: TESTING + minimal DB + inbox dir を fixture 化。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # minimal DB (read-only mount される harness.db を擬似)
        db_path = os.path.join(self._tmp.name, "harness.db")
        db = sqlite3.connect(db_path)
        db.executescript(
            """
            CREATE TABLE requests (id INTEGER PRIMARY KEY, ts TEXT, host TEXT,
                method TEXT, url TEXT, status TEXT, body_size INTEGER);
            CREATE TABLE blocks (id INTEGER PRIMARY KEY, ts TEXT, host TEXT, reason TEXT);
            CREATE TABLE tool_uses (id INTEGER PRIMARY KEY, ts TEXT,
                tool_name TEXT, input TEXT, input_size INTEGER);
            CREATE TABLE alerts (id INTEGER PRIMARY KEY, ts TEXT, type TEXT, detail TEXT);
            """
        )
        db.commit()
        db.close()
        os.environ["DB_PATH"] = db_path

        # minimal policy.toml
        policy_path = os.path.join(self._tmp.name, "policy.toml")
        with open(policy_path, "w") as f:
            f.write("[domains.allow]\nlist = []\n[paths.allow]\n")
        os.environ["POLICY_PATH"] = policy_path

        # inbox dir
        inbox_dir = os.path.join(self._tmp.name, "inbox")
        os.makedirs(inbox_dir)
        os.environ["INBOX_DIR"] = inbox_dir

        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _get_soup(self, path: str) -> "BeautifulSoup":
        rv = self.client.get(path)
        self.assertEqual(rv.status_code, 200, f"GET {path} → {rv.status_code}")
        return BeautifulSoup(rv.data, "html.parser")

    def _assert_no_inline_assets(self, soup: "BeautifulSoup", endpoint: str) -> None:
        # <script> 子要素 (text 含む) は禁止、<script src="..."> は OK
        inline_scripts = []
        for s in soup.find_all("script"):
            text = (s.string or "").strip()
            if text:
                inline_scripts.append(text[:80])
        self.assertEqual(
            inline_scripts, [],
            f"{endpoint}: inline <script> found ({len(inline_scripts)}): "
            f"{inline_scripts!r}",
        )

        # <style> element は完全禁止
        styles = soup.find_all("style")
        self.assertEqual(
            len(styles), 0,
            f"{endpoint}: <style> element found ({len(styles)})",
        )

        # 全要素の style="..." 属性禁止
        with_style = soup.find_all(attrs={"style": True})
        self.assertEqual(
            len(with_style), 0,
            f"{endpoint}: style=\"...\" attr found on {len(with_style)} elements: "
            f"{[el.name for el in with_style[:5]]}",
        )

        # inline event handler 禁止
        for handler in _INLINE_HANDLERS:
            els = soup.find_all(attrs={handler: True})
            self.assertEqual(
                len(els), 0,
                f"{endpoint}: {handler}=\"...\" attr found on {len(els)} elements",
            )

        # data-target= が残っていないこと (whitelist の url-suggest が data-suggest-target に rename)
        with_data_target = soup.find_all(attrs={"data-target": True})
        self.assertEqual(
            len(with_data_target), 0,
            f"{endpoint}: data-target= found on {len(with_data_target)} elements "
            f"(should be data-suggest-target after Sprint 007 PR H rename)",
        )

        # hx-* 属性が残っていないこと (Sprint 007 PR H で完全削除)
        all_attrs_hx = []
        for el in soup.find_all(True):
            for attr in el.attrs:
                if attr.startswith("hx-"):
                    all_attrs_hx.append((el.name, attr))
        self.assertEqual(
            all_attrs_hx, [],
            f"{endpoint}: hx-* attributes found: {all_attrs_hx[:5]!r} (should be 0)",
        )


class TestIndexInlineAssets(_BaseInlineAssetsTest):
    def test_no_inline_assets(self) -> None:
        soup = self._get_soup("/")
        self._assert_no_inline_assets(soup, "/")

    def test_csrf_meta_present(self) -> None:
        soup = self._get_soup("/")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        self.assertIsNotNone(meta, "<meta name=\"csrf-token\"> missing in <head>")
        self.assertTrue(meta.get("content"), "csrf-token content empty")

    def test_self_hosted_static_links_present(self) -> None:
        soup = self._get_soup("/")
        # /static/app.css への link 存在
        links = [l for l in soup.find_all("link", rel="stylesheet")
                 if "/static/app.css" in (l.get("href") or "")]
        self.assertGreater(len(links), 0, "/static/app.css link missing")
        # /static/app.js への script 存在
        scripts = [s for s in soup.find_all("script")
                   if "/static/app.js" in (s.get("src") or "")]
        self.assertGreater(len(scripts), 0, "/static/app.js script missing")


class TestPartialStatsInlineAssets(_BaseInlineAssetsTest):
    def test_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/stats")
        self._assert_no_inline_assets(soup, "/partials/stats")


class TestPartialRequestsInlineAssets(_BaseInlineAssetsTest):
    def test_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/requests")
        self._assert_no_inline_assets(soup, "/partials/requests")


class TestPartialToolUsesInlineAssets(_BaseInlineAssetsTest):
    def test_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/tool-uses")
        self._assert_no_inline_assets(soup, "/partials/tool-uses")


class TestPartialInboxInlineAssets(_BaseInlineAssetsTest):
    def test_no_inline_assets(self) -> None:
        # inbox は空でも items=[] でテンプレ render が通る (else branch)
        soup = self._get_soup("/partials/inbox")
        self._assert_no_inline_assets(soup, "/partials/inbox")


class TestPartialWhitelistInlineAssets(_BaseInlineAssetsTest):
    def test_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/whitelist")
        self._assert_no_inline_assets(soup, "/partials/whitelist")


if __name__ == "__main__":
    unittest.main()
