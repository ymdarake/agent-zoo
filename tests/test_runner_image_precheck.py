"""Tests for ``zoo.runner.ensure_agent_images_built``.

`zoo run` / `zoo up` / `zoo task` が docker compose を叩く前に、
local build 済の agent-zoo image が存在するか pre-check し、
無ければ English hint で `zoo build --agent <agent>` を案内する。

compose が registry pull を試みて cryptic error で落ちる前に
fail-fast するのが目的。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from zoo.runner import ensure_agent_images_built


def _mock_result(returncode: int = 0):
    m = MagicMock()
    m.returncode = returncode
    return m


def test_passes_when_all_images_exist():
    """base + agent image 両方が local に存在すれば silent に通る。"""
    with patch("zoo.runner.subprocess.run", return_value=_mock_result(0)):
        ensure_agent_images_built(["claude"])


def test_raises_system_exit_when_base_image_missing(capsys):
    """agent-zoo-base:latest が無い時 SystemExit + English hint。"""
    with patch("zoo.runner.subprocess.run", return_value=_mock_result(1)):
        with pytest.raises(SystemExit):
            ensure_agent_images_built(["claude"])
    err = capsys.readouterr().err
    assert "agent-zoo-base:latest" in err
    assert "zoo build" in err
    # English hint (ユーザー環境の日本語 locale に依存しない)
    assert "not found" in err.lower()


def test_hint_includes_agent_name_from_services(capsys):
    """hint の `zoo build --agent <name>` に requested agent 名が入る。"""
    with patch("zoo.runner.subprocess.run", return_value=_mock_result(1)):
        with pytest.raises(SystemExit):
            ensure_agent_images_built(["codex"])
    err = capsys.readouterr().err
    assert "zoo build --agent codex" in err


def test_skips_non_agent_services():
    """services 内の proxy / dashboard / dns 等は external image なので check 対象外。
    agent が services に含まれない場合は base image のみ check する (dashboard-only 起動等)。"""
    with patch("zoo.runner.subprocess.run", return_value=_mock_result(0)) as mock_run:
        ensure_agent_images_built(["proxy", "dashboard"])
    # subprocess.run が呼ばれたが、agent-zoo-proxy 等を inspect してないこと
    for call in mock_run.call_args_list:
        args = call[0][0]
        assert "agent-zoo-proxy:latest" not in args
        assert "agent-zoo-dashboard:latest" not in args


def test_docker_inspect_called_with_correct_images():
    """base と agent image 両方を inspect する (command は正確)。"""
    with patch("zoo.runner.subprocess.run", return_value=_mock_result(0)) as mock_run:
        ensure_agent_images_built(["gemini"])
    called_images = {call[0][0][-1] for call in mock_run.call_args_list}
    assert "agent-zoo-base:latest" in called_images
    assert "agent-zoo-gemini:latest" in called_images


def test_raises_when_agent_image_exists_but_base_missing(capsys):
    """base が無いが agent image がある edge case (`zoo build --agent X` の途中で cancel 等)。
    base が無ければ compose は結局 fail するので fail-fast する。"""
    def _run(cmd, *args, **kwargs):
        # inspect の対象 image によって返り値を変える
        img = cmd[-1]
        if "agent-zoo-base" in img:
            return _mock_result(1)  # base 無し
        return _mock_result(0)      # agent あり

    with patch("zoo.runner.subprocess.run", side_effect=_run):
        with pytest.raises(SystemExit):
            ensure_agent_images_built(["claude"])
    err = capsys.readouterr().err
    assert "agent-zoo-base" in err
