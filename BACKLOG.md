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
| [#29](https://github.com/ymdarake/agent-zoo/issues/29) | .zoo/ 集約構造への workspace layout refactor | 🟡 実装完了（[Sprint 002 アーカイブ](docs/dev/sprints/002-dot-zoo-workspace-layout.md)）+ bundle/Makefile 撤去で zoo CLI 一本化済。残: #31 user smoke のみ |
| [#31](https://github.com/ymdarake/agent-zoo/issues/31) | user 実機動作確認 (11 項目 smoke) | ⏳ user 環境で実施 |
| [#32](https://github.com/ymdarake/agent-zoo/issues/32) | README dashboard スクショ追加・更新（Inbox タブ含む） | ⏳ user 環境で実施 |
| [#33](https://github.com/ymdarake/agent-zoo/issues/33) | E2E P1 dashboard / P2 proxy 実装 | ✅ [Sprint 003 アーカイブ](docs/dev/sprints/003-e2e-foundation-and-zoo-cli-unification.md) で完了（実装 + `ci.yml` 統合 + PR テンプレ）。GitHub issue は close 可 |
| [#34](https://github.com/ymdarake/agent-zoo/issues/34) | E2E P3 real agent (token + opt-in CI) | ⏳ #33 完了後の次フェーズ |
| [#35](https://github.com/ymdarake/agent-zoo/issues/35) | inbox ファイル作成を決定的に実行できるよう agent 用スクリプト提供 | 🆕 新規。agent が HARNESS_RULES で TOML 手書きする現状を `zoo inbox submit` 等のヘルパに置き換える想定。要 grooming |

---

## Next Up

> 📋 **全体計画書**: [docs/plans/2026-04-18-consolidated-work-breakdown.md](docs/plans/2026-04-18-consolidated-work-breakdown.md)
> Sprint 004〜008 に作業をブレークダウン、依存関係と PR 単位を詳述。以下はその要約。

| 優先度 | Sprint | 内容 | 期間 |
|---|---|---|---|
| 🟢 **P2** | **Sprint 006** Security Hardening | Medium (M-2〜M-8) + サプライチェーン hardening を 3 PR で (PR D = M-2/M-5/M-6/M-7/G3-B1 ✅ 完了 / PR E = M-3/M-4 + Dependabot + pip-audit ✅ 完了 / PR F = M-8 policy_lock 共通化) | 2〜3 日 |
| 🟢 **P2** | **Sprint 007** Dashboard 外部依存ゼロ化 | pico/htmx → 自前 HTML/CSS/JS (ADR 0004) を 4 PR で → **Beta publish 可** | 1〜2 週間 |
| ⚪ **P3** | **Sprint 008** Low Polish | Low 指摘解消 + 1.0 release candidate | 1 日 |
| P1 | **#31 user smoke** | user 環境で 11 項目確認、Sprint 005 alpha 後に実施 | user 依存 |
| ⏸ | **E-2 (#3)** | OpenAI `exec_command` 引数検知の仕様確定後 | 未定 |

---

## ROADMAP（将来の機能）

### セキュリティ

> **⚠ 2026-04-18 包括レビューで Critical/High 多数検出**。詳細: [docs/dev/reviews/2026-04-18-comprehensive-review.md](docs/dev/reviews/2026-04-18-comprehensive-review.md)。
> 「localhost 専用のため認証不要」前提は CSRF / DNS rebinding により破綻していることが判明。下記「ダッシュボード認証」の優先度を上げる。

- [ ] **ダッシュボード CSRF 対策**（包括レビュー H-1）: Flask-WTF CSRFProtect or Origin / Sec-Fetch-Site 検証
- [ ] **mitmproxy addon の fail-closed 化**（包括レビュー C-2 / Gemini 検出）: 全 event handler に top-level try/except + `flow.kill()`
- [ ] **dashboard 認証機構**（旧「Basic 認証 or API キー」）: 起動時生成 token 等で無認証 + CSRF を解消
- [ ] **dashboard を外部依存ゼロの自前 HTML/CSS/vanilla JS に書き直す**（包括レビュー M-1）: 現状 `pico.css` / `htmx.org` を unpkg / jsdelivr から SRI 無しで読込 → CDN 乗っ取り / タンパリングリスク。dashboard は数画面規模なので**自前 CSS（数百行）+ vanilla JS（`fetch` + `form.addEventListener` で HTMX 置換、~50 行）に完全移行**する方が、外部ライブラリを self-host するより long-term simple。依存 0 にすることでサプライチェーン攻撃面消滅 + オフライン動作 + 監査対象縮小。規模見積: テンプレート書換 ~500 行、CSS ~300 行、JS ~50 行
- [ ] **エントロピーチェック**: ペイロード内の高エントロピー文字列検知 (`[payload_rules.advanced] entropy_threshold = 4.5`)
- [ ] **npm CLI 版固定**: `bundle/container/Dockerfile.{codex,gemini,unified}` の `npm install -g @<vendor>/cli` をバージョン pin して bit-for-bit 再現性を担保 (Sprint 006 PR E plan review で defer。詳細: docs/dev/security-notes.md)
- [ ] **`uv.lock` activation in Dockerfile.base / hash 入り requirements.txt**: `uv sync --frozen --locked` および `pip install --require-hashes` で build 時の依存固定を強化 (Sprint 006 PR E plan review で defer)
- [ ] **OpenAI `exec_command` 引数検査の高度化** (#3 / E-2): `exec_command(command="...")` の `command` フィールドを `[tool_use_rules].block_args` でいい感じに検知。仕様確定待ち

### 運用

- [ ] **CoreDNS と policy.toml の自動同期**: allow list 変更時に Corefile を動的生成してリロード
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
| 003 | 2026-04-18 | E2E Test Foundation + zoo CLI 一本化 (#33) | [003-e2e-foundation-and-zoo-cli-unification.md](docs/dev/sprints/003-e2e-foundation-and-zoo-cli-unification.md) |
| 004 | 2026-04-19 | Docs / CI Cleanup (包括レビュー Phase 2) | [004-docs-ci-cleanup.md](docs/dev/sprints/004-docs-ci-cleanup.md) |
| 005 | 2026-04-18〜19 | Critical Security (包括レビュー Phase 1、C-1/C-2/H-1〜H-4) | [005-critical-security.md](docs/dev/sprints/005-critical-security.md) |

過去の Resolved Decisions（Q1〜Q9 / 案 A 採用 / 命名分離 等）は各 sprint アーカイブを参照。

---

## 備考

- 本 BACKLOG は **active な未完了タスク + 将来計画** のみを管理。
- 完了タスクの詳細は `docs/dev/sprints/<NNN>-<theme>.md` にアーカイブ、設計判断は `docs/dev/adr/NNNN-<theme>.md` に記録。
- 各タスク着手時は `docs/plans/<task-id>.md` を別途切る運用を推奨（Plan エージェント / レビューエージェント連携用）。
- `CLAUDE.md` の開発ワークフロー（Plan → レビュー → TDD → サブエージェントレビュー → Gemini レビュー → docs → ナレッジ → スキル → commit-push）は各タスクで踏襲。
