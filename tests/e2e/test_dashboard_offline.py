"""Sprint 007 PR I: dashboard が CDN block 状態でも動作することを実証。

ADR 0004 の最終 PR で CDN link を完全削除したため、ブラウザが CDN ホストへ
リクエストすること自体が無いはず。Playwright route で CDN を強制 abort し、
それでも全 UI が描画される (= 自前 CSS/JS のみで完結) ことを smoke check する。

E2E P1 全 7 ケース複製は冗長なので、本ファイルでは smoke 1 ケース + tab 切替
1 ケース + form submit 1 ケース の最小セットで「オフラインで dashboard が
動作可能」を実証する。
"""

from __future__ import annotations

import re

import pytest


_CDN_PATTERN = re.compile(r"https?://(cdn\.jsdelivr\.net|unpkg\.com)/.*")


def _block_cdn(page) -> int:
    """CDN ドメインへの request を全 abort、aborted 件数を返す cell。

    list-of-int を使って lambda 経由で counter を更新する (closure 互換)。
    """
    counter = [0]

    def handler(route):
        counter[0] += 1
        route.abort()

    page.route(_CDN_PATTERN, handler)
    return counter


def test_dashboard_loads_with_cdn_blocked(dashboard, page) -> None:
    """CDN を block しても dashboard root が 200 + Agent Zoo タイトル表示。"""
    blocked = _block_cdn(page)
    page.goto(dashboard)
    page.wait_for_selector("text=Agent Zoo")
    assert page.locator("text=Agent Zoo").count() > 0
    # CDN への request が **そもそも発生していない** (CDN link 完全削除後の正常状態)。
    # block 件数は 0 = link が無く request も飛んでいない、を assert。
    assert blocked[0] == 0, (
        f"unexpected CDN requests: {blocked[0]} (CDN link should be 0 in PR I)"
    )


def test_inbox_tab_works_with_cdn_blocked(dashboard, page) -> None:
    """CDN block 状態で tab 切替 + inbox empty が表示できる。"""
    _block_cdn(page)
    page.goto(dashboard)
    page.click("text=Inbox")
    page.wait_for_selector("text=Inbox Requests")
    assert "未承認のリクエストはありません" in page.content()


def test_inbox_accept_form_works_with_cdn_blocked(
    workspace, dashboard, write_inbox_pending, page
) -> None:
    """CDN block 状態で inbox accept form (data-swap-target + data-json-body) 動作。"""
    write_inbox_pending(value="offline.example.com", fid_suffix="off001")
    _block_cdn(page)
    page.goto(dashboard)
    page.click("text=Inbox")
    page.wait_for_selector("text=offline.example.com")
    page.once("dialog", lambda d: d.accept())
    page.click('form[action*="/accept"] button:has-text("許可")')
    page.wait_for_selector("text=未承認のリクエストはありません")

    import tomllib
    rt_path = workspace / ".zoo" / "policy.runtime.toml"
    rt = tomllib.loads(rt_path.read_text())
    allow_list = rt.get("domains", {}).get("allow", {}).get("list", [])
    assert "offline.example.com" in allow_list
