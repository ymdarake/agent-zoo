# BACKLOG

GitHub Open Issues (12件) を 5 グループに分類し、実行可能な粒度のタスクへ分解した整理ドキュメント。
詳細プランは Plan エージェント / Gemini レビューに渡せるレベルまで具体化している。

- 元issue: https://github.com/ymdarake/agent-zoo/issues
- 整理日: 2026-04-18
- 整理対象 issue: #3, #13, #16, #17, #18, #19, #20, #21, #23, #24, #25, #26

---

## ⚠️ Open Questions（着手前に確認が必要な事項・エスカレーション）

優先度順。**着手前に user に判断を仰ぐ**。回答待ちの間に並行可能なタスクは「⏩ 並行可」で示す。

### Q1. policy inbox のファイル形式（Group A の根幹設計）

`policy_candidate.toml` の代替として「inbox ディレクトリ」を採用するが、以下のどれが望ましいか？

| 案 | 形式 | 利点 | 欠点 |
|---|---|---|---|
| **a. 1 リクエスト = 1 JSON ファイル** | `inbox/2026-04-18T10-23-45-abc123.json` | 並行書込安全、削除が簡単 | TOML 統一性が崩れる |
| **b. 1 リクエスト = 1 TOML ファイル** | `inbox/2026-04-18T10-23-45-abc123.toml` | プロジェクト内 TOML 統一 | flock 不要だが parse コスト増 |
| **c. 単一 TOML への追記**（現状維持） | `inbox/requests.toml` | 既存テンプレ流用 | flock 必須、conflict 処理必要 |

**推奨: 案b**（TOML 統一 + atomic write 自然対応）。要 user 確認。

### Q2. inbox の workspace 別 named volume 命名規則

`docker-compose.yml` で `WORKSPACE` 変数からどう volume 名を導出するか？

- 案 A: `policy-inbox-${WORKSPACE_HASH}`（hash は SHA1 短縮）
- 案 B: `policy-inbox-default`（workspace 識別を諦め単一 volume）
- 案 C: ディレクトリ bind mount を `${WORKSPACE}/.zoo/inbox/` に置く（workspace と一蓮托生）

**推奨: 案 C**（workspace 削除時に自動消滅、ユーザーが grep/編集しやすい）。要 user 確認。

### Q3. issue #16「policy_runtime が read-only になっている」の再現条件

`docker-compose.yml` を読む限り、`policy.runtime.toml` は dashboard では writeable (`L92`)、proxy では `:ro` (`L76`) と適切に分かれている。

- どの操作で「read-only」エラーが出たか？（dashboard 経由 / 手動編集 / 別経路？）
- 「maybe same root as #23」とコメントされているが、policy_candidate.toml の write 失敗と同根（UID 不一致）か？

**着手前に user から再現手順 or エラーログが欲しい**。⏩ 推測の範囲で Group A 設計に取り込む（runtime も inbox 同様に bind mount + UID 整合）形で進めることは可能。

### Q4. ベースイメージ統合での gemini-cli パッケージ名（#24）

- `@google/gemini-cli` (npm 公式) で確定？
- それとも `pip install google-generativeai` 系の CLI？
- 認証方式は OAUTH か API key か（base イメージの ENV 設計に影響）？

⏩ 確認待ちで Group B のファイル分割（#18）は先行可能。

### Q5. AGENTS.md の扱い（#21）

OpenAI Codex CLI は `AGENTS.md`、Claude Code は `CLAUDE.md`、Gemini CLI は `GEMINI.md` を慣習的に読む。

- Group B で base + agent 二段化する際、各エージェント用の `*.harness.md` を全て同じ内容で配布するか？
- または「統一 `HARNESS_RULES.md` + 各 CLI 向け shim」形式にするか？

**推奨: 統一テンプレ `templates/HARNESS_RULES.md` を base イメージに配置 → entrypoint で各エージェントの慣習名にコピー**。要 user 確認。

### Q6. extra cert の入手規約（#17）

企業 proxy 配下での apt 失敗を救う仕組み。

- 案 a: `certs/extra/*.crt` ディレクトリを規約化、Dockerfile が `update-ca-certificates` で取り込む
- 案 b: 環境変数 `EXTRA_CA_BUNDLE_PATH` を bind mount で受ける
- mitmproxy runtime 側は `--set ssl_verify_upstream_trusted_ca=...` で指定可能

**推奨: 案 a**（規約のほうがオンボーディングが楽）。要 user 確認。

### Q7. one-liner proxy コマンドのインターフェース（#26）

- `eval "$(zoo proxy on)"` で現シェルに `HTTPS_PROXY` 等を export？
- それとも `zoo wrap claude ...` のようにラッパー実行？
- Claude Code 固有 `srt-settings.json` の自動書き換えも含めるか？

⏩ 設計議論あり。Group D は他に依存しないので最後でよい。

### Q8. issue #3 のスコープ

ROADMAP では「OpenAI 形式 tool_calls 対応」が未実装と記載されているが、実コードには `OpenAIResponsesStreamParser` / `extract_tool_uses_from_openai_response_data` と test_openai_*.py 2 ファイルが存在。

- Issue #3 は **既に実装済みなので、policy.toml に OpenAI 用例セクションを足し、ROADMAP を更新するだけで close 可能**と判断。
- それでよいか確認。

### Q9. ベースイメージの非 root 化と gh/glab の認証伝播

`#19` で `gh` を base に入れた場合、認証情報の引き継ぎ:

- ホスト `~/.config/gh/hosts.yml` を bind mount？
- 環境変数 `GITHUB_TOKEN` のみ受ける？
- Network 隔離下で `api.github.com` を allow list に追加するか（現状 `github.com /anthropics/*` のみ allow）？

⏩ 仕様策定タスクとして Group B-2.2 内に内包。

---

## グループ A: Policy 永続化の根本不具合（P0・最優先）

> **関連 issue**: #23（親）, #16（同根の可能性）, #13（dashboard 表示の追加要求、#23 へマージ指示済）
>
> **背景**: 現状 `policy_candidate.toml` は単一ファイルで bind mount。コンテナ内 `claude` ユーザー（HOST_UID）が write するが、ベースイメージを別ワークスペースで再利用すると build 時の UID が固定され、別 host UID とずれて write 失敗する。さらに dashboard には candidate 表示画面が無い（whitelist タブは blocks テーブルベース）。
>
> **目標**: workspace 別 inbox ディレクトリへ移行し、UID 固定問題と並行書込問題を構造的に解消、dashboard で human-in-the-loop の確認 UI を提供。

### A-1: 設計確定 & ADR 起票

- **目的**: Q1, Q2, Q3 を解消し設計を凍結
- **成果物**:
  - `docs/adr/0001-policy-inbox.md`（採用案、ファイル形式、命名、ライフサイクル）
  - inbox レコード schema 定義
- **完了条件**: ADR が user レビュー通過
- **見積**: S（半日）
- **依存**: Q1, Q2, Q3 回答

#### inbox レコード schema（推奨案）
```toml
# inbox/{ISO8601}-{shortid}.toml
schema_version = 1
created_at = "2026-04-18T10:23:45Z"
agent = "claude"            # or "codex" / "gemini"
type = "domain"             # or "path" / "tool_use_unblock"
value = "registry.npmjs.org"
domain = ""                 # type="path" の時のみ
reason = "npm install で xxx を取得するため"
referenced_blocks = [123, 456]  # 任意: blocks.id の参照（ある場合）
status = "pending"          # pending / accepted / rejected / expired
```

### A-2: `addons/policy_inbox.py` 新規実装（pure logic）

- **目的**: inbox の書込み・読込・状態遷移 API を mitmproxy/Flask 非依存で提供
- **API（最低限）**:
  - `add_request(inbox_dir: str, record: dict) -> str`（ファイル名返却）
  - `list_requests(inbox_dir: str, status: str | None = None) -> list[dict]`
  - `mark_status(inbox_dir: str, record_id: str, status: str) -> None`
  - `cleanup_expired(inbox_dir: str, days: int) -> int`
- **TDD**:
  - `tests/test_policy_inbox.py` を Red から書く（add → list → mark → cleanup の各ハッピー/エラーパス）
- **見積**: M（1 日）
- **依存**: A-1

### A-3: docker-compose.yml の volume 構成変更

- **対象**: `docker-compose.yml` の claude/codex/dashboard サービス
- **変更**:
  - `./policy_candidate.toml:/harness/policy_candidate.toml` を削除
  - `${WORKSPACE:-./workspace}/.zoo/inbox:/harness/inbox`（claude/codex 共通）を追加
  - dashboard 側にも同 path を `:ro` でマウント
- **互換性**: 旧 `policy_candidate.toml` が存在する場合のマイグレーションは A-5 で実施
- **見積**: S（半日）
- **依存**: A-1, A-2

### A-4: harness テンプレ更新

- **対象**: `templates/CLAUDE.harness.md`, `templates/CODEX.harness.md`（後者は A-1 / Group B Q5 と整合）
- **変更**: 「`/harness/policy_candidate.toml` に追記してください」→「`/harness/inbox/<ISO日時>-<shortid>.toml` に新規ファイルを作成してください（テンプレと例を併記）」
- **見積**: S
- **依存**: A-1, A-3

### A-5: マイグレーションスクリプト

- **対象**: `scripts/migrate_candidates_to_inbox.py`（新規）
- **挙動**: 既存 `policy_candidate.toml` の `[[candidates]]` 配列を読み、各要素を inbox の個別ファイルへ変換、`policy_candidate.toml` を `.bak` へ rename
- **見積**: S
- **依存**: A-2

### A-6: dashboard に `Inbox` タブ追加（#13 を解消）

- **対象**: `dashboard/app.py`, `dashboard/templates/index.html`, 新規 `dashboard/templates/partials/inbox.html`
- **エンドポイント**:
  - `GET /partials/inbox`（pending 一覧 + 関連 block 件数表示）
  - `POST /api/inbox/accept`（→ A-2 の `mark_status` + `add_to_allow_list` / `add_to_paths_allow` 呼出）
  - `POST /api/inbox/reject`（→ `add_to_dismissed` + `mark_status`）
- **TDD**: `tests/test_dashboard.py` に inbox タブのテスト追加
- **見積**: M
- **依存**: A-2, A-3

### A-7: issue #16 の根本検証

- **目的**: Q3 確認後、`policy.runtime.toml` の write 失敗が UID 起因か別原因か特定
- **成果物**:
  - 再現手順を `docs/troubleshooting.md` に追記、または #16 を「再現せず・close」とする判定文書
- **見積**: S（調査）
- **依存**: Q3 回答

### A-8: ドキュメント更新

- **対象**: `docs/architecture.md` の「ホワイトリスト育成」節、`docs/policy-reference.md`、`README.md` の該当箇所
- **見積**: S
- **依存**: A-1〜A-6 完了

### A-9: ユニットテスト整備 + CI 確認

- **対象**: A-2/A-6 で増えたテストが `make unit` で全 PASS、Docker smoke `make test` 通過
- **見積**: S
- **依存**: A-2, A-6

---

## グループ B: ベースイメージ統合・拡張（P1）

> **関連 issue**: #18（claude/codex Dockerfile 統合）, #19（base に python3/gh/glab 追加）, #24（gemini-cli 追加）, #21（bash モード + AGENTS.md inject）
>
> **背景**: 現状 `Dockerfile` と `Dockerfile.codex` は npm install パッケージ名と useradd 名以外ほぼ同一（diff < 10 行）。base 共通化で重複削除し、後続のツール追加を一箇所で完結させる。
>
> **目標**: `Dockerfile.base`（共通ツール群）+ `Dockerfile.{claude,codex,gemini}`（CLI 個別レイヤ）の二段構成。

### B-1: `container/Dockerfile.base` 切り出し（#18）

- **対象**: 新規 `container/Dockerfile.base`
- **内容**:
  - `FROM node:20-slim`
  - `apt install ca-certificates git sqlite3 curl` + （B-2 で追加: python3, gh, glab, jq, less）
  - `useradd -m -u ${HOST_UID} agent`（user 名を `agent` に統一、`/home/agent` を作成）
  - `entrypoint.sh` の COPY
  - `WORKDIR /workspace`
- **既存 `Dockerfile` / `Dockerfile.codex`**:
  - `FROM agent-zoo/base:latest` に書き換え、それぞれ `npm i -g @anthropic-ai/claude-code` / `@openai/codex` のみ追加
- **build 順序**: `make build` で base → 各 agent の順にビルド
- **互換性**: 既存ボリューム名 `claude-auth` / `codex-auth` を維持。HOME ディレクトリは `/home/agent` 統一に伴い `claude-auth:/home/agent/.claude` 等に bind 先変更（既存 volume 内容は手動退避が必要 → Q として user 確認）
- **見積**: M
- **依存**: なし
- **TDD**: smoke `make test` の通過確認

### B-2: base にツール群追加（#19）

- **対象**: `container/Dockerfile.base`
- **追加**: `python3`, `python3-pip`, `gh`, `glab`, `jq`, `less`, `ripgrep`
- **gh の認証**: 環境変数 `GITHUB_TOKEN` を `agent-env` 経由で受ける（docker-compose.yml の `x-agent-env` に追加）
- **policy.toml への追記**: `api.github.com` `gitlab.com` を `domains.allow` に検討（user 判断）
- **見積**: S
- **依存**: B-1

### B-3: gemini-cli 追加 + gemini プロファイル（#24）

- **対象**: 新規 `container/Dockerfile.gemini`, `docker-compose.yml` に `gemini` service 追加, `Makefile` に `AGENT=gemini` 対応追加
- **不明点**: Q4（パッケージ名・認証）回答後に確定
- **policy.toml**: `generativelanguage.googleapis.com`, `oauth2.googleapis.com` を allow 検討
- **見積**: M
- **依存**: B-1, Q4

### B-4: bash モード（#21）

- **対象**: `Makefile` に `bash` ターゲット追加 + `entrypoint.sh` 拡張
- **新ターゲット**:
  ```makefile
  .PHONY: bash
  bash: certs
  	HOST_UID=$(HOST_UID) docker compose up -d $(AGENT) dashboard
  	docker compose exec $(AGENT) bash
  ```
- **`zoo bash` CLI コマンドも追加**（src/ 配下の CLI 実装にあわせる）
- **見積**: S
- **依存**: B-1

### B-5: AGENTS.md / HARNESS_RULES.md inject（#21）

- **対象**: `templates/HARNESS_RULES.md` を新規作成（CLAUDE.harness.md / CODEX.harness.md を統合）、`entrypoint.sh` で `/workspace` ルートに `cp` する仕組み
- **挙動**: 起動時に `/workspace/AGENTS.md`, `/workspace/CLAUDE.md`, `/workspace/GEMINI.md` のいずれかが既存ならスキップ、無ければ `HARNESS_RULES.md` の内容を書き込む（または symlink）
- **不明点**: Q5（テンプレ統一の方針）回答必須
- **見積**: M
- **依存**: B-1, Q5

### B-6: ドキュメント更新

- **対象**: `docs/codex-integration.md`, 新規 `docs/gemini-integration.md`, `README.md` のクイックスタート
- **見積**: S
- **依存**: B-1〜B-5

---

## グループ C: 単発バグ修正（P0）

### C-1: `make candidates` の SyntaxError 解消（#20）

- **再現確認済み**: `make candidates` 実行で `SyntaxError: invalid syntax`（Python 3.14 の inline `try:` が parse 不能）
- **対象**:
  - 新規 `scripts/show_candidates.py`（純粋 Python、tomllib）
  - `Makefile` の `candidates` ターゲットを `python3 scripts/show_candidates.py` 呼出に置換
- **後続**: A-3 完了後は inbox 一覧表示に書き換え（C-1 → A-3 の順）
- **TDD**: `tests/test_show_candidates.py` で空ファイル、複数候補、parse error の各ケース
- **見積**: S（< 1 時間）
- **依存**: なし（即着手可能）

---

## グループ D: 運用補助（P1）

### D-1: docker build 時の extra CA 対応（#17 build-time）

- **目的**: 企業 proxy 配下で `apt update` の gpg 検証失敗を救う
- **対象**: `container/Dockerfile.base`
- **方式**:
  - `certs/extra/` 配下に `*.crt` を置く規約（Q6 確認後確定）
  - Dockerfile で `COPY certs/extra/*.crt /usr/local/share/ca-certificates/ && update-ca-certificates` を `apt update` の**前**に実行
  - `certs/extra/.gitkeep` のみ commit、`*.crt` は gitignore
- **見積**: S
- **依存**: Q6, B-1

### D-2: mitmproxy runtime の上流 CA マウント（#17 runtime）

- **対象**: `docker-compose.yml` proxy service, `host/setup.sh`
- **方式**:
  - `certs/extra/` を proxy にも `:ro` mount
  - mitmproxy 起動 args に `--set ssl_verify_upstream_trusted_ca=/certs/extra/bundle.pem`（or 個別ファイル列挙）
- **見積**: S
- **依存**: D-1

### D-3: one-liner proxy コマンド（#26）

- **目的**: ホスト側 claude/codex CLI を一発で zoo proxy 経由にする
- **不明点**: Q7（インターフェース選定）
- **候補設計**:
  - `zoo proxy on` → 標準出力に `export HTTPS_PROXY=...; export NODE_EXTRA_CA_CERTS=...` を出力 → ユーザーは `eval "$(zoo proxy on)"`
  - `zoo proxy on --write-srt` → Claude Code の `~/.claude/srt-settings.json` の `customProxy` を upsert
- **対象**: `src/` 配下の CLI 実装
- **見積**: M
- **依存**: Q7

---

## グループ E: ドキュメント / サンプル拡充（P2）

### E-1: README/docs 英語版（#25）

- **対象**: `README.en.md`, `docs/architecture.en.md`, `docs/security.en.md`, `docs/policy-reference.en.md`, `docs/codex-integration.en.md`
- **方針**: 元日本語版を base に翻訳、相互リンク（README 冒頭に `English | 日本語` toggle）
- **スコープ判断**: Q が立つ場合は user 確認（全 docs か、README+architecture のみか）
- **見積**: M（翻訳量に依存、日 +1）
- **依存**: なし（最後にまとめて）

### E-2: OpenAI tool_calls の policy 例セクション追加（#3）

- **前提**: Q8 で「実装済み」確認済み想定
- **対象**:
  - `docs/policy-reference.md` の `[tool_use_rules]` 節に OpenAI Responses 形式の例を追記
  - `policy.toml` のコメントにも一行例を追加
  - `ROADMAP.md` の「OpenAI 形式 tool_calls 対応」を「実装済み」へ移動
- **見積**: S
- **依存**: Q8

---

## 依存関係マップ

```
C-1 ─────────────────── (即着手)
                                                                     
A-1 ── A-2 ── A-3 ── A-4
              │      │
              ├──── A-5 (migration)
              │
              └──── A-6 (dashboard inbox UI)
                                          ── A-8 (docs) ── A-9 (test)
A-7 (#16 root cause)  ───────────────────┘                          

B-1 ── B-2 ── B-6
   ├── B-3 (Q4 待ち)
   ├── B-4
   └── B-5 (Q5 待ち)

D-1 ── D-2
D-3 (Q7 待ち)

E-1, E-2 (independent)
```

---

## 推奨実行順（Wave）

| Wave | タスク | 並列度 | 想定期間 |
|---|---|---|---|
| 0 | Q1〜Q9 を user に確認 | — | 1 ラウンド |
| 1 | C-1（即修正）+ A-1（設計） | 並列 | 半日 |
| 2 | A-2 / A-3 / A-4 / A-5 / A-7 | 一部並列 | 1〜2 日 |
| 3 | A-6（dashboard） + B-1（base 統合） | 並列 | 1 日 |
| 4 | B-2 / D-1 / D-2 | 並列 | 半日 |
| 5 | B-3（Q4 後） / B-4 / B-5（Q5 後） | 並列 | 1 日 |
| 6 | D-3 / E-1 / E-2 / A-8 / A-9 / B-6 | 並列 | 1 日 |

---

## issue ↔ タスク 対応表

| issue | 担当タスク | close 条件 |
|---|---|---|
| #3 | E-2 | docs/policy-reference.md に OpenAI 例追記 + ROADMAP 更新 |
| #13 | A-6 | dashboard で inbox 一覧が確認できる |
| #16 | A-7 (+ A-3) | 根本原因特定または再現せずで close |
| #17 | D-1, D-2 | extra cert が build-time / runtime 両方で機能 |
| #18 | B-1 | Dockerfile.base からの二段ビルドが PASS |
| #19 | B-2 | base に python3/gh/glab/jq 追加、smoke OK |
| #20 | C-1 | `make candidates` が動作 |
| #21 | B-4, B-5 | `make bash` で workspace 入り、AGENTS.md 注入 |
| #23 | A-1〜A-9（全体） | inbox 移行完了、policy_candidate.toml 廃止 |
| #24 | B-3 | `AGENT=gemini make run` が起動 |
| #25 | E-1 | README.en.md 公開 |
| #26 | D-3 | `eval "$(zoo proxy on)"` で host CLI が proxy 経由 |

---

## 進捗チェックリスト

### Group A: Policy Inbox（P0）
- [ ] A-1 設計確定 & ADR 起票
- [ ] A-2 `addons/policy_inbox.py` 実装 + テスト
- [ ] A-3 docker-compose.yml volume 変更
- [ ] A-4 harness テンプレ更新
- [ ] A-5 マイグレーションスクリプト
- [ ] A-6 dashboard Inbox タブ
- [ ] A-7 #16 根本検証
- [ ] A-8 ドキュメント更新
- [ ] A-9 テスト整備 + smoke

### Group B: ベースイメージ統合（P1）
- [ ] B-1 Dockerfile.base 切出し
- [ ] B-2 base にツール群追加
- [ ] B-3 gemini-cli 追加
- [ ] B-4 bash モード
- [ ] B-5 AGENTS.md inject
- [ ] B-6 ドキュメント更新

### Group C: 単発バグ修正（P0）
- [ ] C-1 `make candidates` SyntaxError 解消

### Group D: 運用補助（P1）
- [ ] D-1 docker build 時 extra CA
- [ ] D-2 mitmproxy runtime extra CA
- [ ] D-3 one-liner proxy command

### Group E: ドキュメント（P2）
- [ ] E-1 README/docs 英語版
- [ ] E-2 OpenAI tool_calls policy 例

---

## 備考

- 本 BACKLOG は `docs/plans/` 系列とは独立した「issue grooming」専用ドキュメント。
- 各タスク着手時は `docs/plans/<task-id>.md` を別途切る運用を推奨（Plan エージェント / レビューエージェント連携用）。
- `CLAUDE.md` の開発ワークフロー（Plan → レビュー → TDD → サブエージェントレビュー → Gemini レビュー → docs → ナレッジ → スキル → commit-push）は各タスクで踏襲。
