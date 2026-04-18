# ADR 0003: E2E Test Strategy

## Status
Accepted (2026-04-18)

## Context

現状の自動テストは **unit test (234 件、subprocess mock 多用)** に限定。Sprint 002 では mock がほぼ全 runtime path を覆い隠していたため、`repo_root()` 残骸（ADR 0002 で削除した関数）への参照が unit PASS のまま残り、**実 CLI 全壊状態を Self-Review (Phase 1) まで検知できなかった**。

加えて:

- dashboard UI / Inbox flow / policy.runtime.toml への反映フローは unit ではカバー困難
- `#31` user 実機 smoke チェックリストは手動依存、CI で回せない
- agent の確率的応答を含む E2E は flaky リスク高、CI コスト増

## Decision

**3 段階の E2E 戦略**を採用し、自動化の現実性とコストでスコープを分離する。

### D1. P1: dashboard UI E2E (Docker 不要)

- `bundle/dashboard/app.py` を **Flask 直起動** (subprocess.Popen)
- `pytest-playwright` で UI 操作
- agent はモック: agent が submit する `inbox/*.toml` を **fixture で直接配置**
- tmp workspace + 最小 `.zoo/` (policy.toml, policy.runtime.toml, inbox/, data/harness.db schema)

**CI: 毎 PR**、Docker 不要、~30 秒/run

### D2. P2: proxy ブロック疎通 E2E (Docker 必要)

- `docker compose up -d proxy [+ agent]` → コンテナ内 `curl` で:
  - 許可ドメイン → 200/404
  - 未許可 → 403
  - direct (proxy バイパス) → 接続失敗
- 従来 `bundle/Makefile` の smoke test と重複するが pytest 統合で reporting 統一（Makefile 自体は後日撤去、ADR 0002 Follow-up 参照）

**CI: Docker runner、PR or nightly**、~2 分/run

### D3. P3: 実 agent E2E (Docker + token, opt-in)

- token (`CLAUDE_CODE_OAUTH_TOKEN` / `OPENAI_API_KEY` / `GEMINI_API_KEY`) を CI secret に設定
- 固定 prompt で agent に "Bash で curl ブロック対象 → inbox 提出" を厳密実行させる
- inbox 提出を assert、続けて dashboard accept → 再投入で通る確認
- 確率的応答リスク → retry 1 回 + `pytest.mark.flaky` 許容

**CI: weekly cron or `[agents-realtime]` PR label**、token cost が発生するため opt-in

### D4. ツール選定: Playwright (Python)

| 候補 | 評価 |
|---|---|
| **Playwright (pytest-playwright)** | ✅ CI 公式 Action、安定、本決定 |
| chrome-devtools MCP | ❌ Claude Code 専用、CI 不可 |
| Selenium | △ 古い、エコシステム弱い |

### D5. agent モック戦略 (P1)

P1 では agent コンテナを起動せず、**agent が submit する状態 = `inbox/*.toml` を fixture で配置** することで dashboard / policy_inbox の機能を完全テスト可能にする。実 agent 動作は P3 で別途。

### D6. ディレクトリ layout

```
tests/e2e/
  conftest.py            # workspace / dashboard fixture (Flask 直起動)
  test_dashboard.py      # P1: UI 操作 + policy.runtime.toml 反映 assert
  test_proxy_block.py    # P2: Docker 必要、proxy 疎通
  test_real_agent.py     # P3: token 必要、@pytest.mark.skipif で opt-in
  README.md              # 実行手順
```

### D7. 依存追加

`pyproject.toml`:
```toml
[project.optional-dependencies]
e2e = ["playwright>=1.40", "pytest-playwright>=0.4"]
```

初回 setup:
```bash
uv pip install -e ".[e2e]"
playwright install chromium    # ~150MB
```

### D8. CI 戦略

- **P1**: GitHub Actions の既存 `ci.yml` に `e2e-dashboard` job を追加 (Docker 不要、軽量、毎 PR)
- **P2**: 同 `ci.yml` に `e2e-proxy` job を追加 (Docker サービス利用、毎 PR or nightly)
- **P3**: `agents-realtime.yml` を新設、weekly cron + PR label `[agents-realtime]` で opt-in 実行

## Consequences

### Positive
- Sprint 002 で発生した「unit PASS でも CLI 全壊」型バグの自動検知
- dashboard リグレッション (Inbox / Whitelist 等) の即時検知
- `#31` user smoke の自動化可能部分を吸収（手動依存を縮小）
- P1 は Docker 不要なため、軽量 CI で頻繁に回せる

### Negative / Trade-offs
- CI 時間増加: P1 ~30s / P2 ~2min / P3 ~5min+
- Playwright バイナリ ~150MB（CI cache で対処）
- P3 の token cost / 確率的応答による flaky リスク
- E2E メンテコスト（UI 変更時に test 修正必要）

## Open / Future

- スクショ自動取得 (#32) を P1 fixture から派生させる案（screenshot を `docs/images/` に書き出す pytest plugin）
- Lighthouse 監査の追加（dashboard performance 指標）
- agent 種別 matrix（P3 で claude/codex/gemini を並列実行、cost 倍増）

## References

- #33: P1 + P2 実装 issue
- #34: P3 real agent E2E（別 issue として起票予定）
- ADR 0001 Policy Inbox（Inbox flow テスト対象）
- ADR 0002 Workspace Layout（fixture が `.zoo/` 構造を生成）
- Sprint 002 アーカイブ: mock 限界の実例（Self-Review Phase 1 で発見した H1-H5）
