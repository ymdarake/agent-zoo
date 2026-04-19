"""Tests for `addons._status_constants` (Sprint 006 PR D self-review H-1).

新しい block 系 status (`URL_SECRET_BLOCKED`, `BODY_TOO_LARGE`) を policy_enforcer
と dashboard 集計の両方で確実に「ブロック扱い」する中央集権定数。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle"))

from addons._status_constants import (  # noqa: E402
    BLOCK_STATUSES,
    block_statuses_sql_placeholders,
)


class TestBlockStatuses:
    def test_url_secret_blocked_in_set(self):
        # M-2 の新 status が漏れていないこと
        assert "URL_SECRET_BLOCKED" in BLOCK_STATUSES

    def test_body_too_large_in_set(self):
        # M-6 の新 status が漏れていないこと
        assert "BODY_TOO_LARGE" in BLOCK_STATUSES

    def test_legacy_statuses_still_present(self):
        for legacy in ("BLOCKED", "RATE_LIMITED", "PAYLOAD_BLOCKED"):
            assert legacy in BLOCK_STATUSES

    def test_no_duplicates(self):
        assert len(BLOCK_STATUSES) == len(set(BLOCK_STATUSES))

    def test_placeholder_count_matches(self):
        sql = block_statuses_sql_placeholders()
        assert sql.count("?") == len(BLOCK_STATUSES)
