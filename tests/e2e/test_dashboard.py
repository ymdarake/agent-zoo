"""P1 dashboard UI E2E（Docker 不要、Flask + Playwright）.

ADR 0003 D1: agent はモック（fixture で inbox.toml 直接配置）。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


def test_dashboard_root_loads(dashboard, page) -> None:
    """dashboard root (index.html) が 200 で返り、主要 UI が描画される。"""
    page.goto(dashboard)
    page.wait_for_selector("text=Agent Zoo")
    assert page.locator("text=Agent Zoo").count() > 0


def test_inbox_tab_empty_message(dashboard, page) -> None:
    """inbox が空の時、empty メッセージが表示される。"""
    page.goto(dashboard)
    page.click("text=Inbox")
    page.wait_for_selector("text=Inbox Requests")
    assert "未承認のリクエストはありません" in page.content()


def test_inbox_lists_pending(workspace, dashboard, write_inbox_pending, page) -> None:
    """inbox に pending TOML を配置 → Inbox タブの一覧に行が現れる。"""
    write_inbox_pending(value="needed.example.com", fid_suffix="abc111")
    page.goto(dashboard)
    page.click("text=Inbox")
    page.wait_for_selector("text=needed.example.com")
    assert "needed.example.com" in page.content()


def test_inbox_accept_writes_to_runtime(
    workspace: Path, dashboard, write_inbox_pending, page
) -> None:
    """「許可」ボタン → policy.runtime.toml の domains.allow に追記される。"""
    write_inbox_pending(value="ok.example.com", fid_suffix="def222")
    page.goto(dashboard)
    page.click("text=Inbox")
    page.wait_for_selector("text=ok.example.com")
    # confirm dialog を accept
    page.once("dialog", lambda d: d.accept())
    # form[hx-post=".../accept"] 内の button に絞る（bulk button と区別）
    page.click('form[action*="/accept"] button:has-text("許可")')
    # HTMX swap 完了を待ち、runtime ファイル更新まで余裕
    page.wait_for_selector("text=未承認のリクエストはありません")

    rt_path = workspace / ".zoo" / "policy.runtime.toml"
    rt = tomllib.loads(rt_path.read_text())
    allow_list = rt.get("domains", {}).get("allow", {}).get("list", [])
    assert "ok.example.com" in allow_list


def test_inbox_reject_marks_status_only(
    workspace: Path, dashboard, write_inbox_pending, page
) -> None:
    """「却下」ボタン → status=rejected、policy.runtime.toml は変更されない。"""
    write_inbox_pending(value="reject.example.com", fid_suffix="ghi333")
    page.goto(dashboard)
    page.click("text=Inbox")
    page.wait_for_selector("text=reject.example.com")
    page.click('form[action*="/reject"] button:has-text("却下")')
    page.wait_for_selector("text=未承認のリクエストはありません")

    rt_path = workspace / ".zoo" / "policy.runtime.toml"
    if rt_path.read_text().strip():
        rt = tomllib.loads(rt_path.read_text())
        allow_list = rt.get("domains", {}).get("allow", {}).get("list", [])
        assert "reject.example.com" not in allow_list

    # inbox file の status が rejected に更新される
    inbox_files = list((workspace / ".zoo" / "inbox").glob("*.toml"))
    assert len(inbox_files) == 1
    rec = tomllib.loads(inbox_files[0].read_text())
    assert rec["status"] == "rejected"


def test_inbox_path_accept_writes_to_paths_allow(
    workspace: Path, dashboard, write_inbox_pending, page
) -> None:
    """type=path の許可 → policy.runtime.toml の paths.allow に追記される。"""
    write_inbox_pending(
        type_="path",
        value="/v1/*",
        domain="api.example.com",
        fid_suffix="path001",
    )
    page.goto(dashboard)
    page.click("text=Inbox")
    page.wait_for_selector("text=api.example.com")
    page.once("dialog", lambda d: d.accept())
    # form[hx-post=".../accept"] 内の button に絞る（bulk button と区別）
    page.click('form[action*="/accept"] button:has-text("許可")')
    page.wait_for_selector("text=未承認のリクエストはありません")

    rt = tomllib.loads((workspace / ".zoo" / "policy.runtime.toml").read_text())
    paths_allow = rt.get("paths", {}).get("allow", {})
    assert "/v1/*" in paths_allow.get("api.example.com", [])


def test_inbox_bulk_accept(
    workspace: Path, dashboard, write_inbox_pending, page
) -> None:
    """複数 pending を選択 → 一括許可 → 全て policy.runtime.toml に追記。"""
    write_inbox_pending(value="bulk1.example.com", fid_suffix="bulk001")
    write_inbox_pending(value="bulk2.example.com", fid_suffix="bulk002")
    write_inbox_pending(value="bulk3.example.com", fid_suffix="bulk003")
    page.goto(dashboard)
    page.click("text=Inbox")
    page.wait_for_selector("text=bulk1.example.com")
    # 全選択 (header の checkbox)
    page.check("#inbox-select-all")
    page.once("dialog", lambda d: d.accept())  # bulk confirm
    page.click('button:has-text("選択を一括許可")')
    page.wait_for_selector("text=未承認のリクエストはありません")

    rt = tomllib.loads((workspace / ".zoo" / "policy.runtime.toml").read_text())
    allow_list = rt.get("domains", {}).get("allow", {}).get("list", [])
    for d in ("bulk1.example.com", "bulk2.example.com", "bulk3.example.com"):
        assert d in allow_list, f"{d} not in {allow_list}"
