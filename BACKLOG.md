# BACKLOG

active な未完了タスク + 将来計画 (ROADMAP) を統合管理する。
完了タスクは sprint 単位で `docs/dev/sprints/` にアーカイブ、設計判断は ADR (`docs/dev/adr/`) に記録。

- 元 issue: https://github.com/ymdarake/agent-zoo/issues
- Sprint 履歴: [docs/dev/sprints/](docs/dev/sprints/)
- ADR: [docs/dev/adr/](docs/dev/adr/)

---

## Active Open Issues

| # | タイトル | 状態 |
|---|---|---|
| [#3](https://github.com/ymdarake/agent-zoo/issues/3) | OpenAI形式の tool_call ポリシー例 | ⏸ 仕様確定待ち（ROADMAP 参照） |
| [#28](https://github.com/ymdarake/agent-zoo/issues/28) | Organize & cleanup docs | ✅ Sprint 002 で完了（user/dev 分離 + 新 layout 反映 + codex-integration 削除）|
| [#29](https://github.com/ymdarake/agent-zoo/issues/29) | .zoo/ 集約構造への workspace layout refactor | 🟡 実装完了（[Sprint 002 アーカイブ](docs/dev/sprints/002-dot-zoo-workspace-layout.md)）。残: #31 smoke, #28 docs |
| [#31](https://github.com/ymdarake/agent-zoo/issues/31) | user 実機動作確認 (11 項目 smoke) | ⏳ user 環境で実施 |
| [#32](https://github.com/ymdarake/agent-zoo/issues/32) | README dashboard スクショ追加・更新（Inbox タブ含む） | ⏳ user 環境で実施 |
| [#33](https://github.com/ymdarake/agent-zoo/issues/33) | E2E P1 dashboard / P2 proxy 実装 | 🟡 P1+P2 実装完了（ADR 0003 / Gemini レビュー反映済）、user 実機で `pytest tests/e2e/` 確認待ち |
| [#34](https://github.com/ymdarake/agent-zoo/issues/34) | E2E P3 real agent (token + opt-in CI) | ⏳ #33 完了後の次フェーズ |

---

## Next Up

| 優先度 | タスク | アクション |
|---|---|---|
| P1 | **#31 user smoke** | user 環境で 11 項目を確認、NG があれば fix を別 issue 化 |
| ⏸ | **E-2 (#3)** | OpenAI `exec_command` 引数検知の仕様確定後 |

---

## ROADMAP（将来の機能）

### セキュリティ

- [ ] **ダッシュボード認証**: Basic 認証 or API キー（localhost 専用のため優先度低）
- [ ] **エントロピーチェック**: ペイロード内の高エントロピー文字列検知 (`[payload_rules.advanced] entropy_threshold = 4.5`)
- [ ] **OpenAI `exec_command` 引数検査の高度化** (#3 / E-2): `exec_command(command="...")` の `command` フィールドを `[tool_use_rules].block_args` でいい感じに検知。仕様確定待ち

### 運用

- [ ] **CoreDNS と policy.toml の自動同期**: allow list 変更時に Corefile を動的生成してリロード
- [ ] **`zoo test smoke` の Python 化**: ADR 0002 D5 で Makefile を配布廃止したため `api.test_smoke()` が `bundle/Makefile` 依存（maintainer 用）。配布物でも動くよう Python (`subprocess` + `httpx` 等) で再実装
- [ ] **SSE ストリーミング透過の復元**: mitmproxy 10.x の stream callable 非対応のため保留
- [ ] **ダッシュボード HTMX ローディングインジケータ**

### マルチプロバイダ対応

- [ ] **OpenAI 形式 tool_calls の policy 例追加**: `[tool_use_rules]` 節に Responses API 形式の例。SSE パーサ自体は対応済（OpenAIResponsesStreamParser）

### 将来の拡張（spec 未定）

- LiteLLM 的な設定ファイル認証管理: YAML/TOML でモデル別の認証情報・エンドポイントを一元管理
- エージェントツールテンプレート拡充: Codex CLI / Aider / Cline の推奨設定を `bundle/templates/` に追加
- agentgateway 統合: MCP/A2A プロトコルレベルでの制御
- LlamaFirewall 的な ML 検出: tool_use パターン検出を ML ベースに拡張
- コミュニティ deny リスト共有: ブロックドメイン+理由の匿名集約・公開
- `.zoo/` 内のさらなる細分化（ADR 0002 Open）: `.zoo/cache/` 等
- `policy.toml` の `[[*.rules]]` に `id` 振る案: ADR 0001 `referenced_blocks` の実効性向上

---

## Sprint 履歴

| Sprint | 期間 | テーマ | アーカイブ |
|---|---|---|---|
| 001 | 2026-04-18 | Policy Inbox & Base Image Foundation | [001-policy-inbox-and-base-image.md](docs/dev/sprints/001-policy-inbox-and-base-image.md) |
| 002 | 2026-04-18 | `.zoo/` Workspace Layout Refactor (#29) | [002-dot-zoo-workspace-layout.md](docs/dev/sprints/002-dot-zoo-workspace-layout.md) |

過去の Resolved Decisions（Q1〜Q9 / 案 A 採用 / 命名分離 等）は各 sprint アーカイブを参照。

---

## 備考

- 本 BACKLOG は **active な未完了タスク + 将来計画** のみを管理。
- 完了タスクの詳細は `docs/dev/sprints/<NNN>-<theme>.md` にアーカイブ、設計判断は `docs/dev/adr/NNNN-<theme>.md` に記録。
- 各タスク着手時は `docs/plans/<task-id>.md` を別途切る運用を推奨（Plan エージェント / レビューエージェント連携用）。
- `CLAUDE.md` の開発ワークフロー（Plan → レビュー → TDD → サブエージェントレビュー → Gemini レビュー → docs → ナレッジ → スキル → commit-push）は各タスクで踏襲。
