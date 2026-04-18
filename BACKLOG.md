# BACKLOG

Active な未完了タスクのみを管理する。完了タスクは sprint 単位で `docs/sprints/` にアーカイブ。

- 元 issue: https://github.com/ymdarake/agent-zoo/issues
- Sprint 履歴: [docs/sprints/](docs/sprints/)

---

## Active Open Issues

| # | タイトル | 担当タスク | 状態 |
|---|---|---|---|
| #3 | OpenAI形式の tool_call ポリシー例 | E-2 | ⏸ 保留（仕様確定待ち、Q8） |
| #28 | Organize & cleanup docs | G-1 | ⏳ 新規（zoo init 中心の設計に docs を再整理） |

---

## Next Up

| 優先度 | タスク | アクション |
|---|---|---|
| P2 | **#28 docs cleanup** | `zoo init` で workspace へ展開する設計をベースに、README / docs/architecture.md 等を簡潔化（既存 docs は make 中心の記述が残る可能性） |
| ⏸ | **E-2 (#3)** | OpenAI `exec_command` 引数検知の仕様を確定後、ROADMAP に正式登録 → 実装 |

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
