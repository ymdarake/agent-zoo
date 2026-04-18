#!/usr/bin/env python3
"""policy_candidate.toml の中身を簡潔に表示する CLI。

将来 A-3（policy inbox 化）で複数ファイルを glob して表示する際、
load_candidates / format_candidates を再利用する想定。
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path


def load_candidates(path: Path) -> list[dict]:
    """TOML から `[[candidates]]` 配列を読み込む。

    `candidates` キーが list 以外なら ValueError を投げる（スキーマ違反）。
    """
    with path.open("rb") as f:
        data = tomllib.load(f)
    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError(
            f"'candidates' must be a list, got {type(candidates).__name__}"
        )
    return candidates


def format_candidates(candidates: list[dict]) -> str:
    """候補リストをヒトに読みやすい複数行文字列へ整形する。"""
    lines = [f"{len(candidates)} candidate(s)"]
    for c in candidates:
        t = c.get("type", "?")
        v = c.get("value", "?")
        r = c.get("reason", "")
        if r:
            lines.append(f"  [{t}] {v} - {r}")
        else:
            lines.append(f"  [{t}] {v}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show policy_candidate.toml contents",
    )
    parser.add_argument(
        "--file",
        default="policy_candidate.toml",
        help="Path to candidates TOML (default: policy_candidate.toml)",
    )
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"{path} not found", file=sys.stderr)
        return 1
    try:
        candidates = load_candidates(path)
    except (tomllib.TOMLDecodeError, ValueError) as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Read error: {e}", file=sys.stderr)
        return 1
    print(format_candidates(candidates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
