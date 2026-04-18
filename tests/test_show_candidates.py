"""scripts/show_candidates.py のユニットテスト。

将来 A-3 で inbox 形式に置き換える際、load_candidates / format_candidates
を再利用する想定で関数分割している。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "scripts")
)
from show_candidates import format_candidates, load_candidates, main  # noqa: E402


# === load_candidates ===


def test_load_empty_file_returns_no_candidates(tmp_path: Path) -> None:
    p = tmp_path / "empty.toml"
    p.write_text("")
    assert load_candidates(p) == []


def test_load_file_without_candidates_table(tmp_path: Path) -> None:
    p = tmp_path / "no_candidates.toml"
    p.write_text("[other]\nkey = 'value'\n")
    assert load_candidates(p) == []


def test_load_multiple_candidates(tmp_path: Path) -> None:
    p = tmp_path / "multi.toml"
    p.write_text(
        '[[candidates]]\n'
        'type = "domain"\n'
        'value = "example.com"\n'
        'reason = "test"\n'
        '\n'
        '[[candidates]]\n'
        'type = "path"\n'
        'domain = "registry.npmjs.org"\n'
        'value = "/foo/*"\n'
        'reason = "deps"\n'
    )
    candidates = load_candidates(p)
    assert len(candidates) == 2
    assert candidates[0]["type"] == "domain"
    assert candidates[0]["value"] == "example.com"
    assert candidates[1]["type"] == "path"
    assert candidates[1]["value"] == "/foo/*"


# === format_candidates ===


def test_format_zero_candidates() -> None:
    assert format_candidates([]) == "0 candidate(s)"


def test_format_single_candidate() -> None:
    out = format_candidates(
        [{"type": "domain", "value": "example.com", "reason": "test"}]
    )
    assert "1 candidate(s)" in out
    assert "[domain] example.com - test" in out


def test_format_with_missing_fields_uses_question_mark() -> None:
    out = format_candidates([{"value": "x"}])
    assert "1 candidate(s)" in out
    assert "[?] x" in out


def test_format_omits_trailing_dash_when_reason_empty() -> None:
    out = format_candidates([{"type": "domain", "value": "x.com", "reason": ""}])
    assert "[domain] x.com" in out
    assert "x.com - " not in out


def test_format_preserves_order() -> None:
    out = format_candidates(
        [
            {"type": "domain", "value": "a.com", "reason": "1"},
            {"type": "path", "value": "/x", "reason": "2"},
        ]
    )
    lines = out.splitlines()
    assert "a.com" in lines[1]
    assert "/x" in lines[2]


# === main (CLI) ===


def test_main_file_not_found_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--file", str(tmp_path / "nonexistent.toml")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "not found" in captured.err


def test_main_parse_error_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "bad.toml"
    p.write_text("not = valid = toml")
    rc = main(["--file", str(p)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Parse error" in captured.err


def test_main_success_prints_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "ok.toml"
    p.write_text(
        '[[candidates]]\n'
        'type = "domain"\n'
        'value = "example.com"\n'
        'reason = "demo"\n'
    )
    rc = main(["--file", str(p)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "1 candidate(s)" in captured.out
    assert "[domain] example.com - demo" in captured.out


def test_main_empty_candidates_returns_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "empty.toml"
    p.write_text("")
    rc = main(["--file", str(p)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "0 candidate(s)" in captured.out


def test_load_rejects_non_list_candidates(tmp_path: Path) -> None:
    p = tmp_path / "wrong_type.toml"
    p.write_text('candidates = "not-a-list"\n')
    with pytest.raises(ValueError, match="must be a list"):
        load_candidates(p)


def test_main_directory_path_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--file", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "Read error" in captured.err
