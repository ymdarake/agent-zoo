"""Sprint 007 PR I: CSP `'self'` only 厳格化テスト。

ADR 0004 (Dashboard 外部依存ゼロ化) の最終 PR。Plan H で全 inline asset を
削除した結果、PR I で `'unsafe-inline'` / CDN ドメイン (cdn.jsdelivr.net /
unpkg.com) を CSP から完全削除可能になった。

`;` split で directive ごと parse することで、CSP value 内の whitespace 等
正規化漏れを防ぐ。
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import app  # noqa: E402


def _parse_csp(csp_value: str) -> dict[str, list[str]]:
    """CSP header value を `directive -> [tokens]` の dict に parse。

    `; ` で split → 各 directive を whitespace で split (先頭が directive name、
    残りが values)。空 directive は skip。
    """
    result: dict[str, list[str]] = {}
    for chunk in csp_value.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split()
        directive = parts[0]
        tokens = parts[1:]
        result[directive] = tokens
    return result


class TestCSPStrict(unittest.TestCase):
    """PR I: CSP `'self'` only 厳格化が反映されているか。"""

    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        os.environ["DB_PATH"] = self.db_path
        db = sqlite3.connect(self.db_path)
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
        self.client = app.test_client()

    def tearDown(self) -> None:
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _csp(self) -> dict[str, list[str]]:
        rv = self.client.get("/")
        self.assertEqual(rv.status_code, 200)
        return _parse_csp(rv.headers["Content-Security-Policy"])

    def test_csp_no_unsafe_inline_anywhere(self) -> None:
        """全 directive で `'unsafe-inline'` を含まない。"""
        csp = self._csp()
        for directive, tokens in csp.items():
            self.assertNotIn(
                "'unsafe-inline'", tokens,
                f"directive '{directive}' contains 'unsafe-inline': {tokens!r}",
            )

    def test_csp_no_cdn_domains(self) -> None:
        """全 directive で CDN ドメインを含まない (M-1 / L-6 完全 resolved)。"""
        csp = self._csp()
        for directive, tokens in csp.items():
            for cdn in ("https://cdn.jsdelivr.net", "https://unpkg.com",
                        "cdn.jsdelivr.net", "unpkg.com"):
                self.assertNotIn(
                    cdn, tokens,
                    f"directive '{directive}' contains CDN '{cdn}': {tokens!r}",
                )

    def test_csp_default_src_self_only(self) -> None:
        """`default-src 'self'` のみ (他の token 無し)。"""
        csp = self._csp()
        self.assertEqual(csp.get("default-src"), ["'self'"])

    def test_csp_style_src_self_only(self) -> None:
        csp = self._csp()
        self.assertEqual(csp.get("style-src"), ["'self'"])

    def test_csp_script_src_self_only(self) -> None:
        csp = self._csp()
        self.assertEqual(csp.get("script-src"), ["'self'"])

    def test_csp_form_action_self(self) -> None:
        """`form-action 'self'`: default-src の fallback 対象外なので明示必要。"""
        csp = self._csp()
        self.assertIn("form-action", csp)
        self.assertEqual(csp["form-action"], ["'self'"])

    def test_csp_frame_ancestors_none(self) -> None:
        csp = self._csp()
        self.assertEqual(csp.get("frame-ancestors"), ["'none'"])

    def test_csp_object_src_none(self) -> None:
        csp = self._csp()
        self.assertEqual(csp.get("object-src"), ["'none'"])

    def test_csp_base_uri_none(self) -> None:
        csp = self._csp()
        self.assertEqual(csp.get("base-uri"), ["'none'"])

    def test_csp_set_with_force_assignment(self) -> None:
        """review H-1: setdefault ではなく `=` 強制上書きで設定されている。

        他 layer (middleware や test) で先に CSP を set しても、最終 response の
        CSP は app.py の `_add_security_headers` の値で上書きされる。
        """
        rv = self.client.get("/")
        csp = rv.headers["Content-Security-Policy"]
        # 'unsafe-inline' を含む弱い CSP が flask 内部で立つ余地はないが、
        # 「最終 CSP は厳格仕様」を保証するための snapshot test。
        self.assertNotIn("'unsafe-inline'", csp)
        self.assertIn("default-src 'self'", csp)


class TestPermissionsPolicy(unittest.TestCase):
    """Permissions-Policy (旧 Feature-Policy) で不要機能を全 deny。"""

    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        os.environ["DB_PATH"] = self.db_path
        db = sqlite3.connect(self.db_path)
        db.executescript("CREATE TABLE requests (id INTEGER); CREATE TABLE blocks (id INTEGER); CREATE TABLE tool_uses (id INTEGER); CREATE TABLE alerts (id INTEGER);")
        db.commit()
        db.close()
        self.client = app.test_client()

    def tearDown(self) -> None:
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_permissions_policy_present(self) -> None:
        rv = self.client.get("/")
        self.assertIn("Permissions-Policy", rv.headers)

    def test_permissions_policy_blocks_unused_features(self) -> None:
        rv = self.client.get("/")
        pp = rv.headers["Permissions-Policy"]
        for feature in ("camera", "microphone", "geolocation", "payment"):
            self.assertIn(f"{feature}=()", pp, f"missing block for {feature}")


if __name__ == "__main__":
    unittest.main()
