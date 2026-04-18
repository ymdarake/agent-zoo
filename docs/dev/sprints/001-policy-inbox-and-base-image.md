# Sprint 001: Policy Inbox & Base Image Foundation

| 項目 | 値 |
|---|---|
| 期間 | 2026-04-18（1 day） |
| テーマ | GitHub Open Issues 12 件の grooming + Policy Inbox / Base Image 統合 / Bug Fix / 運用補助 / Docs 多言語化 |
| 完了 issue | 12 件 |
| 完了タスク | A-1〜A-9 / B-1〜B-6 / C-1 / D-1〜D-3 / E-1 / F-1（合計 24） |
| 新規 issue 起票 | #27 cross-agent 統合 → 同 sprint で完了, #28 docs cleanup → 次 sprint へ |

---

## Sprint Goal

GitHub Open Issues 12 件を整理 (grooming) し、Policy Inbox（ADR 0001）の設計・実装・dashboard 統合・migration までを 1 sprint で完遂する。あわせて Base Image 二段化、bash モード、HARNESS_RULES 統合、extra cert 対応、zoo proxy CLI、英語 docs、cross-agent unified イメージまで前進させる。

---

## Closed Issues (12)

| # | タイトル | 担当タスク | 関連 commit |
|---|---|---|---|
| #13 | policy_candidate のダッシュボード表示 | A-6 | fa9ff89 |
| #16 | policy_runtime が read-only | A-7 | 経過観察で再現せず |
| #17 | support extra cert | D-1, D-2 | 02a6098 |
| #18 | claude / codex image 統合 | B-1 | dd12130 |
| #19 | base に各種ツール追加 | B-2 | 02a6098, deb16f5, 8e25205 |
| #20 | Makefile inline python error | C-1 | 78dfb65 |
| #21 | bash モード + AGENTS.md inject | B-4, B-5 | d6045ff |
| #23 | policy_candidate.toml → inbox 移行（親） | A-1〜A-9 | 29e727f, 42e38c4, 4a1c271, fa9ff89, cc93c80 |
| #24 | gemini cli 同梱 | B-3 | c1bfe55, 2936c90 |
| #25 | Multi-lang README/doc | E-1 | e097b5b, df89691 |
| #26 | one-liner proxy command | D-3 | 0256014 |
| #27 | unified image (cross-agent) | F-1 | 2842a68 |

---

## 完了タスク

### Group A: Policy Inbox (P0) — A-1〜A-9 全完了

ADR 0001 ([docs/adr/0001-policy-inbox.md](../adr/0001-policy-inbox.md)) を起点に、`policy_candidate.toml` 単一ファイル → `${WORKSPACE}/.zoo/inbox/` ディレクトリへ移行。

| # | タスク | 成果物 |
|---|---|---|
| A-1 | 設計確定 + ADR 起票 | docs/adr/0001-policy-inbox.md |
| A-2 | `addons/policy_inbox.py` 実装 + 27 tests | atomic O_EXCL + content hash dedup |
| A-3 | docker-compose volume 変更 | inbox bind mount + runner / Makefile 自動 mkdir |
| A-4 | harness テンプレ更新 | inbox 形式へ書換 |
| A-5 | マイグレーション | scripts/migrate_candidates_to_inbox.py + 10 tests / 冪等 |
| A-6 | dashboard Inbox タブ | 9 tests / accept 自動 runtime 反映 + bulk 操作 |
| A-7 | #16 根本検証 | Docker 環境で write 試行 → 成功、再現せず |
| A-8 | docs 更新 | docs/architecture.md に Policy Inbox 章 + README に Inbox/ADR リンク |
| A-9 | テスト整備 + smoke | `make test` All PASS（Allowed/Blocked 403/Isolated/SQLite Logs） |

### Group B: ベースイメージ統合 (P1) — B-1〜B-6 全完了

| # | タスク | 成果物 |
|---|---|---|
| B-1 | Dockerfile.base 切出し | 二段ビルド agent-zoo-base + agent別 |
| B-2 | base にツール群追加 | python3 / jq / less / ripgrep + gh 2.90.0 + glab 1.92.1 |
| B-3 | gemini-cli 追加 | Dockerfile.gemini + compose + Makefile/runner に AGENT=gemini 統合（`--yolo` for dangerous, `-p` for task） |
| B-4 | bash モード | `make bash` + `zoo bash` で対話 shell |
| B-5 | HARNESS_RULES.md 統合 | templates/HARNESS_RULES.md 統合 + entrypoint で慣習名 inject (CLAUDE/AGENTS/GEMINI.md) |
| B-6 | docs 更新 | A-8 と統合扱い |

### Group C: 単発バグ修正 (P0)

| # | タスク | 成果物 |
|---|---|---|
| C-1 | `make candidates` SyntaxError 解消 | scripts/show_candidates.py 切出し / 14 tests |

### Group D: 運用補助 (P1) — D-1〜D-3 全完了 + 実環境動作確認

| # | タスク | 成果物 |
|---|---|---|
| D-1 | docker build 時 extra CA | certs/extra/*.crt 規約 + Dockerfile.base で update-ca-certificates / 自己署名 CA で動作確認 |
| D-2 | mitmproxy runtime extra CA | bundle.pem があれば `--set ssl_verify_upstream_trusted_ca` / docker top で args 反映確認 |
| D-3 | one-liner proxy command | `zoo proxy <agent>` ラッパー / TestProxy 2 ケース |

### Group E: ドキュメント (P2)

| # | タスク | 成果物 |
|---|---|---|
| E-1 | README/docs 英語版 | README.en.md + docs/{architecture,security,policy-reference,codex-integration}.en.md / 双方向リンク完備 |
| E-2 | OpenAI exec_command 引数検知 | ⏸ 保留（仕様確定待ち、Q8） |

### Group F: Cross-agent (#27)

| # | タスク | 成果物 |
|---|---|---|
| F-1 | unified image | Dockerfile.unified + compose service profile=unified + entrypoint で 3 *.md inject / 実機 `which claude codex gemini` 全 OK |

---

## Verification

| 項目 | 結果 |
|---|---|
| Unit tests | 197 → **255 PASS**（+58） |
| Docker smoke (`make test`) | **All PASS**（Allowed / Blocked 403 / Isolated / SQLite Logs ALLOWED 468 BLOCKED 43） |
| D-1 build-time extra CA | 自己署名 CA で動作確認: `/etc/ssl/certs/test-ca.pem` symlink 作成済 |
| D-2 mitmproxy runtime CA | `docker top` で `mitmdump --set ssl_verify_upstream_trusted_ca=...` 反映確認 |
| B-2 gh / glab | `docker run` で `gh 2.90.0` / `glab 1.92.1` 出力確認 |
| F-1 unified | `docker run` で `which claude codex gemini` 全 success |

---

## Resolved Decisions（user 回答日: 2026-04-18）

| Q | 決定 | 影響範囲 |
|---|---|---|
| Q1 | inbox は **1 リクエスト = 1 TOML ファイル**（案 b） | A-1, A-2 |
| Q2 | inbox は **`${WORKSPACE}/.zoo/inbox/` の bind mount**（案 c） | A-3 |
| Q3 | UID 問題（A-1〜A-5）解消後に経過観察 → 再現せず close | A-7 |
| Q4 | gemini-cli は **`@google/gemini-cli`（npm 公式）** | B-3 |
| Q5 | **統一テンプレ `HARNESS_RULES.md` + 各 CLI 慣習名で inject** | B-5 |
| Q6 | extra cert は **`certs/extra/*.crt` 規約 + `update-ca-certificates`** | D-1 |
| Q7 | **ラッパー型 `zoo proxy <agent>`** 形式 | D-3 |
| Q8 | OpenAI `exec_command` 引数検知は **保留**（次 sprint 以降） | E-2 |
| Q9 | gh 認証は **コンテナ内で 1 回 `gh auth login` + named volume** | B-2 |

---

## Commit Log（21 commits）

```
fcdb5fd :memo: BACKLOG.md: #27 完了マーク + #28 新規反映 + 進捗サマリ最新化
2842a68 :sparkles: Dockerfile.unified: 3 CLI 統合イメージ（#27、cross-agent 呼び出し）
df89691 :memo: docs/* 英訳 4 ファイル + 双方向言語切替リンク（E-1 完全完了、#25）
8e25205 :sparkles: Dockerfile.base: glab CLI 1.92.1 追加（B-2 完全完了、#19）
2936c90 :sparkles: AGENT=gemini を Makefile/runner.py に統合（B-3 完了、#24）
deb16f5 :sparkles: Dockerfile.base: gh CLI 追加（B-2 続編、#19）
85197c9 :white_check_mark: BACKLOG: A-7/A-9 完了マーク + D-1/D-2 動作確認補足（Wave 6 ✅）
edbc358 :memo: Dockerfile: agent-zoo-base:latest がローカルビルド前提である旨を注記
b4b33d0 :memo: BACKLOG.md: Next Up に #27 cross-agent 統合イメージを追加
2d7a052 :memo: BACKLOG.md: Wave 表 / issue 対応表 / Next Up を進捗反映
e097b5b :memo: README.en.md 追加 + 言語切替リンク（E-1 部分完了）
c1bfe55 :sparkles: gemini-cli の最小雛形（B-3 部分完了）
cc93c80 :memo: docs: Policy Inbox 章追加 + ADR リンク（A-8 完了）
0256014 :sparkles: zoo proxy: ホスト CLI へ proxy 環境注入する wrapper（D-3 完了）
d6045ff :sparkles: bash モード + HARNESS_RULES.md 統合（B-4/B-5 完了）
02a6098 :sparkles: base+extra-cert: ツール拡張と企業proxy対応（B-2/D-1/D-2 完了）
dd12130 :sparkles: container: 二段ビルド構成（agent-zoo-base + agent別）（B-1 完了）
fa9ff89 :sparkles: dashboard: ADR 0001 Inbox タブ実装（A-6 完了）
4a1c271 :sparkles: ADR 0001 inbox の compose/templates/migration 整備（A-3/A-4/A-5 完了）
42e38c4 :sparkles: addons/policy_inbox.py: ADR 0001 Policy Inbox 実装（A-2 完了）
29e727f :memo: docs/adr/0001-policy-inbox.md 起票（A-1 完了）
a57d6da :memo: BACKLOG.md: C-1 完了マーク
78dfb65 :bug: candidates: scripts/show_candidates.py へ切り出し SyntaxError 解消
74b57f0 :memo: BACKLOG.md: Update resolved decisions and clarify task dependencies
ed48295 :memo: BACKLOG.md: GitHub Open Issues 12件の grooming と詳細プラン整理
```

---

## 次 sprint へ繰り越し

| # | タスク | 状態 |
|---|---|---|
| #28 | Organize & cleanup docs（zoo init 中心の設計に整理） | ⏳ 新規 |
| #3 | OpenAI exec_command 引数検知 (E-2) | ⏸ 保留（Q8 仕様確定待ち） |

---

## ユーザー要動作確認（次 sprint 開始前推奨）

| 優先度 | 項目 |
|---|---|
| 🔴 | claude / codex / gemini それぞれの実 token / API key で `make task` |
| 🔴 | Inbox E2E（agent → inbox → dashboard accept → policy.runtime.toml 反映）|
| 🟡 | unified image での cross-agent smoke（claude → gemini -p） |
| 🟡 | workspace 別 inbox 独立性 |
| 🟡 | `uv tool install .` → `zoo init` / `zoo bash` / `zoo proxy claude` |
| 🟢 | 企業 proxy + extra cert |
| 🟢 | policy.toml hot reload |
