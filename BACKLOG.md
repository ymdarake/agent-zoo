# BACKLOG

Active な未完了タスクのみを管理する。完了タスクは sprint 単位で `docs/sprints/` にアーカイブ。

- 元 issue: https://github.com/ymdarake/agent-zoo/issues
- Sprint 履歴: [docs/sprints/](docs/sprints/)

---

## Active Open Issues

| # | タイトル | 担当タスク | 状態 |
|---|---|---|---|
| #3 | OpenAI形式の tool_call ポリシー例 | E-2 | ⏸ 保留（仕様確定待ち、Q8） |
| #28 | Organize & cleanup docs | G-1 | ⏳ #29 実装後に docs 全面刷新（スコープ拡大） |
| #29 | .zoo/ 集約構造への workspace layout refactor | H-1 | ⏳ ADR 0002 起票済み、Sprint 002 で実装 |

---

## Next Up（Sprint 002 候補）

| 優先度 | タスク | アクション |
|---|---|---|
| P0 | **#29 .zoo/ 集約 refactor** | [ADR 0002](docs/adr/0002-dot-zoo-workspace-layout.md): ✅ D8 candidate / ✅ Phase 0-1 / ✅ Phase 2 / ✅ Phase 3-5（後方互換削除、`source = bundle/` `配布 = .zoo/` の命名分離、root → bundle/ git mv、docker-compose の bind mount 新 layout 化、pyproject.toml force-include 更新、tests 全 PASS）。残: docs 刷新（#28）、self-review |
| P1 | **#28 docs 刷新** | #29 完了後、新 layout で docs 全面刷新 |
| ⏸ | **E-2 (#3)** | OpenAI `exec_command` 引数検知の仕様を確定後、ROADMAP に正式登録 → 実装 |

### Sprint 002 のスコープ案
- 中核: #29 (`.zoo/` refactor) + #28 (docs 刷新)
- ~~先行クリーンアップ: policy_candidate.toml 完全削除~~（✅ 2026-04-18 完了、Sprint 002 開始前に実施）
- 任意: ADR 0002 の Open / Future（symlink 戦略 等）

---

## Sprint 履歴

| Sprint | 期間 | テーマ | アーカイブ |
|---|---|---|---|
| 001 | 2026-04-18 | Policy Inbox & Base Image Foundation | [docs/sprints/001-policy-inbox-and-base-image.md](docs/sprints/001-policy-inbox-and-base-image.md) |

---

## Resolved Decisions（過去の意思決定、将来参照用）

| Q | 決定 | 起源 sprint |
|---|---|---|
| Q1 | inbox は **1 リクエスト = 1 TOML ファイル**（案 b） | 001 |
| Q2 | inbox は **`${WORKSPACE}/.zoo/inbox/` の bind mount**（案 c） | 001 |
| Q3 | UID 問題（A-1〜A-5）解消後に経過観察 → 再現せず close | 001 |
| Q4 | gemini-cli は **`@google/gemini-cli`（npm 公式）** | 001 |
| Q5 | **統一テンプレ `HARNESS_RULES.md` + 各 CLI 慣習名で inject** | 001 |
| Q6 | extra cert は **`certs/extra/*.crt` 規約 + `update-ca-certificates`** | 001 |
| Q7 | **ラッパー型 `zoo proxy <agent>`** 形式 | 001 |
| Q8 | OpenAI `exec_command` 引数検知は **保留**（次 sprint 以降） | 001 |
| Q9 | gh 認証は **コンテナ内で 1 回 `gh auth login` + named volume** | 001 |

詳細は各 sprint アーカイブ参照。

---

## ユーザー要動作確認（sprint 001 完了に伴う）

| 優先度 | 項目 |
|---|---|
| 🔴 | claude / codex / gemini それぞれの実 token / API key で `make task` |
| 🔴 | Inbox E2E（agent → inbox → dashboard accept → policy.runtime.toml 反映）|
| 🟡 | unified image での cross-agent smoke（claude → gemini -p） |
| 🟡 | workspace 別 inbox 独立性 |
| 🟡 | `uv tool install .` → `zoo init` / `zoo bash` / `zoo proxy claude` |
| 🟢 | 企業 proxy + extra cert |
| 🟢 | policy.toml hot reload |

---

## 備考

- 本 BACKLOG は **active な未完了タスクのみ**を管理。
- 完了タスクは `docs/sprints/<NNN>-<theme>.md` にアーカイブ。
- 各タスク着手時は `docs/plans/<task-id>.md` を別途切る運用を推奨（Plan エージェント / レビューエージェント連携用）。
- `CLAUDE.md` の開発ワークフロー（Plan → レビュー → TDD → サブエージェントレビュー → Gemini レビュー → docs → ナレッジ → スキル → commit-push）は各タスクで踏襲。
