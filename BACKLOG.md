# BACKLOG

Active な未完了タスク + 将来計画 + 細かい TODO を統合管理する。
完了タスクは sprint 単位で `docs/sprints/` にアーカイブする。

- 元 issue: https://github.com/ymdarake/agent-zoo/issues
- Sprint 履歴: [docs/sprints/](docs/sprints/)

---

## Active Open Issues

| # | タイトル | 担当タスク | 状態 |
|---|---|---|---|
| #3 | OpenAI形式の tool_call ポリシー例 | E-2 | ⏸ 保留（仕様確定待ち、Q8） |
| #28 | Organize & cleanup docs | G-1 | ⏳ #29 実装後に docs 全面刷新 |
| #29 | .zoo/ 集約構造への workspace layout refactor | H-1 | ⏳ Sprint 002 で実装中（DoD のうち unit/設計完了、smoke と docs を残す） |
| #31 | ユーザー実機動作確認: Sprint 001 + 002 完了に伴う smoke チェックリスト | (user) | ⏳ user 環境で実施 |

---

## Next Up（Sprint 002 候補）

| 優先度 | タスク | アクション |
|---|---|---|
| P0 | **#29 .zoo/ 集約 refactor** | [ADR 0002](docs/adr/0002-dot-zoo-workspace-layout.md): ✅ Phase 0-5 + Self-Review 2 段階反映済。残: #31 で user smoke 実機確認、docs 刷新（#28） |
| P1 | **#28 docs 刷新** | #29 完了後、新 layout (bundle/ + .zoo/) に基づき README / docs/* を全面刷新 |
| P1 | **#31 user smoke** | user 環境で 11 項目を確認（実 token, Inbox E2E, unified, etc）|
| ⏸ | **E-2 (#3)** | OpenAI `exec_command` 引数検知の仕様を確定後、ROADMAP セクション参照 → 実装 |

---

## ROADMAP（将来の機能）

実装着手順序や具体的な spec は未定。issue 化の際にここから抜粋する。

### セキュリティ

- [ ] **ダッシュボード認証**: Basic 認証 or API キー（localhost 専用のため優先度低）
- [ ] **エントロピーチェック**: ペイロード内の高エントロピー文字列を検知。`[payload_rules.advanced] entropy_threshold = 4.5`
- [ ] **OpenAI `exec_command` 引数検査の高度化**（#3 / E-2 に対応）: `exec_command(command="...")` の `command` フィールドを `[tool_use_rules].block_args` でいい感じに検知。仕様確定待ち。

### 運用

- [ ] **CoreDNS と policy.toml の自動同期**: allow list 変更時に Corefile を動的生成してリロード
- [ ] **`zoo test smoke` の Python 化**: ADR 0002 D5 で Makefile を配布廃止したため、現状 `api.test_smoke()` は `bundle/Makefile` 依存（maintainer 用）。配布物でも動くよう Python (`subprocess` + `httpx` 等) で再実装
- [ ] **SSE ストリーミング透過の復元**: mitmproxy 10.x の stream callable 非対応のため保留
- [ ] **ダッシュボード HTMX ローディングインジケータ**

### マルチプロバイダ対応

- [ ] **OpenAI 形式 tool_calls の policy 例追加**: `[tool_use_rules]` 節に Responses API 形式の例。SSE パーサ自体は対応済（OpenAIResponsesStreamParser）

### 将来の拡張（spec 未定）

- **LiteLLM 的な設定ファイル認証管理**: YAML/TOML でモデル別の認証情報・エンドポイントを一元管理
- **エージェントツールテンプレート拡充**: Codex CLI、Aider、Cline の推奨設定を `bundle/templates/` に追加
- **agentgateway 統合**: MCP/A2A プロトコルレベルでの制御
- **LlamaFirewall 的な ML 検出**: tool_use パターン検出を ML ベースに拡張
- **コミュニティ deny リスト共有**: ブロックドメイン+理由の匿名集約・公開
- **`.zoo/` 内のさらなる細分化**（ADR 0002 Open）: `.zoo/cache/` 等
- **`policy.toml` の `[[*.rules]]` に `id` 振る案**: ADR 0001 `referenced_blocks` の実効性向上

---

## Sprint 履歴

| Sprint | 期間 | テーマ | アーカイブ |
|---|---|---|---|
| 001 | 2026-04-18 | Policy Inbox & Base Image Foundation | [docs/sprints/001-policy-inbox-and-base-image.md](docs/sprints/001-policy-inbox-and-base-image.md) |
| 002 | 2026-04-18 | .zoo/ Workspace Layout refactor (#29) — 進行中 | （完了後アーカイブ） |

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
| (002) | リリース前のため後方互換不要、命名は **source = `bundle/` / 配布 = `.zoo/`** で分離 | 002 |
| (002) | `policy_candidate.toml` は完全削除（ADR 0002 D8 先行） | 002 |
| (002) | source repo で `zoo` CLI は動かない設計（D7、`bundle/` で `make` を直接叩く or 別 dir で `zoo init`）| 002 |

詳細は各 sprint アーカイブ参照。

---

## 備考

- 本 BACKLOG は **active な未完了タスク + 将来計画 + 細かい TODO** を統合管理する。
- 完了タスクは `docs/sprints/<NNN>-<theme>.md` にアーカイブ。
- 各タスク着手時は `docs/plans/<task-id>.md` を別途切る運用を推奨（Plan エージェント / レビューエージェント連携用）。
- `CLAUDE.md` の開発ワークフロー（Plan → レビュー → TDD → サブエージェントレビュー → Gemini レビュー → docs → ナレッジ → スキル → commit-push）は各タスクで踏襲。
