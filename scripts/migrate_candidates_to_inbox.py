#!/usr/bin/env python3
"""旧 `policy_candidate.toml` → ADR 0001 inbox ディレクトリへの一回限り migration。

使用例:
    python3 scripts/migrate_candidates_to_inbox.py \
        --candidates policy_candidate.toml \
        --inbox workspace/.zoo/inbox/

冪等性:
    - dedup（policy_inbox.add_request の D6）で重複は skip
    - 元ファイルは `.bak` rename（既存 .bak があれば上書きせず src を残す）
    - 再実行しても重複作成しない
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

# addons を import path に追加
_ADDONS = Path(__file__).resolve().parent.parent / "addons"
if str(_ADDONS) not in sys.path:
    sys.path.insert(0, str(_ADDONS))

from policy_inbox import add_request  # noqa: E402


def _load_candidates(src: Path) -> list[dict]:
    """旧 `policy_candidate.toml` から `[[candidates]]` 配列を取得。"""
    if not src.exists():
        return []
    try:
        with src.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        return []
    return data.get("candidates", []) or []


def migrate(src: Path | str, inbox: Path | str) -> int:
    """元 candidates を inbox へ変換。新規作成件数を返す。"""
    src_path = Path(src)
    inbox_path = Path(inbox)
    candidates = _load_candidates(src_path)
    created = 0
    for c in candidates:
        record = {
            "schema_version": 1,
            "agent": "unknown",
            "type": c.get("type", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain", ""),
            "reason": c.get("reason", ""),
            "status": "pending",
        }
        rid = add_request(inbox_path, record)
        if rid is not None:
            created += 1
    return created


def _backup_source(src: Path) -> bool:
    """元ファイルを `.bak` rename。既存 .bak があれば skip して False。"""
    if not src.exists():
        return False
    bak = src.with_suffix(src.suffix + ".bak")
    if bak.exists():
        return False
    src.rename(bak)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy policy_candidate.toml to inbox directory",
    )
    parser.add_argument(
        "--candidates",
        default="policy_candidate.toml",
        help="Source legacy candidates TOML",
    )
    parser.add_argument(
        "--inbox",
        required=True,
        help="Target inbox directory (ADR 0001)",
    )
    args = parser.parse_args(argv)

    src = Path(args.candidates)
    inbox = Path(args.inbox)
    n = migrate(src, inbox)
    print(f"Migrated {n} candidate(s) to {inbox}")
    if n > 0:
        if _backup_source(src):
            print(f"Renamed {src} → {src}.bak")
        else:
            print(f"Skipped backup ({src}.bak already exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
