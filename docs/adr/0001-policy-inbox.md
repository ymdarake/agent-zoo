# ADR 0001: Policy Inbox

## Status
Accepted (2026-04-18)

## Context

現状 `policy_candidate.toml`（単一ファイル、全 workspace 共用）が抱える課題:

1. **UID 固定問題** — build 時 `HOST_UID` で固定された claude/codex ユーザーが、別 workspace 再利用時に host UID とずれて write 失敗
2. **並行書込 conflict** — 複数 agent / 同時操作で TOML 配列追記が競合
3. **dashboard 表示なし** — human-in-the-loop の承認 UI 不在 (issue #13)
4. **workspace 別管理不可** — 単一ファイルで全 workspace 共用、操作主体が混在

エージェントは `templates/CLAUDE.harness.md` / `CODEX.harness.md` の指示に従い `/harness/policy_candidate.toml` に「許可されていないが必要なリクエスト」を追記する設計だが、上記の構造的不具合により実運用に耐えない。

関連 issue: #23（親）, #16（同根の可能性）, #13（dashboard 表示）

## Decision

### D1. データ表現: ディレクトリ + 1 リクエスト 1 ファイル

- 配置先: workspace 内 `${WORKSPACE}/.zoo/inbox/`
- 1 request = 1 TOML ファイル

### D2. ファイル名規約

- 形式: `{ISO8601-with-dashes}-{shortid}.toml`
- 例: `2026-04-18T10-23-45-7c8e3f2a.toml`
- shortid: `secrets.token_hex(4)`（8 文字 hex）で衝突回避
- ISO8601 のコロン `:` は `-` に置換（macOS/Windows 互換性）

### D3. マウント方式

- docker-compose の **bind mount** で host の `${WORKSPACE}/.zoo/inbox/` を `/harness/inbox/` に
- claude / codex / gemini service 共通でマウント
- dashboard は read-write で同 path にマウント
- named volume は使わない（workspace と一蓮托生にする）

### D4. 権限戦略 (UID 整合)

- `Dockerfile.base` で `useradd -m -u ${HOST_UID}`（既存方式踏襲）
- bind mount 先のファイルはコンテナ内 UID = ホスト UID なので、ホスト側で `git clean` / 手動削除可能
- `${HOST_UID}` が異なる workspace を再利用する場合は base イメージ再 build 必須（README に明記）

### D5. Atomic Write（規定）

- すべての書込みは `tempfile.NamedTemporaryFile(dir=inbox_dir)` で一時ファイル作成 → `os.rename` で原子的に最終ファイル名へ
- これにより dashboard が「書込み中の中途半端なファイル」を読むことを防ぐ
- 状態遷移（pending → accepted 等）も同様に rename ベースで原子化

### D6. Deduplication（規定）

- 同一内容（`type` + `value` + `domain` の組）の `pending` ファイルが既に存在する場合、新規作成は **no-op**
- `add_request` は重複時に `None` を返す（ファイル名 None）
- 既存ファイルの `referenced_blocks` 追記は初版では skip（実装簡略化）
- 同一内容の `accepted` / `rejected` がある場合は新規 `pending` を許容（過去判断と現在の必要性を分離）

### D7. ライフサイクル

```
                            ┌→ accepted ─┐
write → pending →───────────┤            ├→ cleanup_expired (after N days)
                            └→ rejected ─┘
                                  ↑
                         (pending のまま N 日 → expired)
```

- **write**: エージェントが `pending` で新規作成
- **accept**: dashboard 操作 → `status=accepted` + `policy.runtime.toml` へ反映（D8）
- **reject**: dashboard 操作 → `status=rejected` + `status_reason` 保存
- **expired**: `pending` のまま N 日経過 → `cleanup_expired` で `expired` 化
- **cleanup**: `accepted` / `rejected` / `expired` を N 日後に削除（監査ログ用に保持期間あり）

### D8. `policy.runtime.toml` への "反映" 定義

accept 操作時、`addons/policy_edit.py` の既存 API を呼出して runtime TOML へ **追記**:

| inbox `type` | 呼出 API | 結果 |
|---|---|---|
| `domain` | `add_to_allow_list(domain)` | `[domains.allow].list` に追記 |
| `path` | `add_to_paths_allow(domain, value)` | `[paths.allow]."{domain}"` に追記 |
| `tool_use_unblock` | （将来対応） | 未実装 |

runtime TOML 構造は変更しない（後方互換）。

### D9. API 担当 (`addons/policy_inbox.py`)

pure logic（mitmproxy / Flask 非依存）。公開関数:

| 関数 | 戻り値 | 用途 |
|---|---|---|
| `add_request(inbox_dir, record)` | `str \| None` | 新規作成（重複時 `None`） |
| `list_requests(inbox_dir, status=None)` | `list[dict]` | 一覧取得（status フィルタ任意） |
| `mark_status(inbox_dir, record_id, new_status, reason="")` | `None` | 状態遷移（atomic rename） |
| `bulk_mark_status(inbox_dir, record_ids, new_status)` | `int` | dashboard 一括操作（成功件数） |
| `cleanup_expired(inbox_dir, days)` | `int` | N 日経過の pending を expired 化 + 古い終端状態を削除（処理件数） |

### D10. dashboard 連携

- `/partials/inbox` で `pending` 一覧表示
- 単一 accept / reject + **複数選択チェックボックスで bulk accept/reject**（D9 の `bulk_mark_status`）
- accept 時は D8 の通り `policy_edit` API 経由で `policy.runtime.toml` へ反映

## Consequences

### Positive
- workspace と inbox が一蓮托生 → workspace 削除で自動消滅
- 並行書込 safe（1 file = 1 record、ファイル名 unique で conflict 不可）
- atomic write 自然対応（D5）
- dedup でファイル爆発抑制（D6）
- bulk 操作で運用負荷低減（D9, D10）
- workspace 別管理が自然

### Negative / Trade-offs
- 旧 `policy_candidate.toml` から migration 必要（A-5 で対応）
- ファイル数が増える → cleanup 機能必須（D7, D9）
- TOML 統一のため JSON より parse cost 微増（無視可）
- bind mount のため UID 不一致時 base イメージ再 build 必要（D4）

## Schema

```toml
schema_version = 1
created_at = "2026-04-18T10:23:45Z"      # ISO8601 UTC

# 発行元
agent = "claude"                          # claude / codex / gemini / unknown

# 種別と内容
type = "domain"                           # domain / path / tool_use_unblock
value = "registry.npmjs.org"              # type="domain": ドメイン文字列, type="path": path pattern (例: /foo/*)
domain = ""                               # type="path" の時のみ使用 (パスを許可するドメイン)

# 理由（人間が判断するための説明）
reason = "npm install で依存解決のため"

# 監査メタデータ（任意、人間の判断材料）
context_url = ""                          # 元リクエストの URL（ブロック直前のもの）
method = ""                               # HTTP メソッド（GET/POST/PUT 等）
referenced_blocks = []                    # blocks.id 参照（任意）

# 状態
status = "pending"                        # pending / accepted / rejected / expired
status_updated_at = ""                    # status 変更時刻（pending 時は空）
status_reason = ""                        # rejected 等の理由（任意）
```

**フィールド種別**:
- 必須: `schema_version`, `created_at`, `agent`, `type`, `value`, `reason`, `status`
- 条件付き必須: `domain`（`type="path"` の時）
- 任意: `context_url`, `method`, `referenced_blocks`, `status_updated_at`, `status_reason`

## Migration

`scripts/migrate_candidates_to_inbox.py`:

1. `policy_candidate.toml` の `[[candidates]]` 配列を読込
2. 各要素を inbox の TOML レコードへ変換
   - `schema_version=1`
   - `created_at=now (UTC)`
   - `agent="unknown"`（旧形式に発行元情報なし）
   - `status="pending"`
3. **冪等性**: dedup ロジック（D6）で重複は skip。再実行しても重複作成しない
4. 元 `policy_candidate.toml` が存在すれば `.bak` rename（既存 `.bak` があれば skip）
5. 完了後、件数を stdout に表示

## Open / Future

- Q3 の `policy.runtime.toml` read-only 問題は A-7 で経過観察（A-1〜A-5 で構造的解消する想定）
- 将来 `tool_use_unblock` 種別（特定 tool_use の許可リクエスト）に拡張予定
- `referenced_blocks` の実効性向上のため `policy.toml` の `[[*.rules]]` に `id` 振る案（将来 ROADMAP）

## References

- BACKLOG.md Group A（A-1 〜 A-9）
- Issues: [#23](https://github.com/ymdarake/agent-zoo/issues/23) (親), [#16](https://github.com/ymdarake/agent-zoo/issues/16) (同根の可能性), [#13](https://github.com/ymdarake/agent-zoo/issues/13) (dashboard 表示)
- 関連実装予定: A-2 `addons/policy_inbox.py`, A-3 docker-compose, A-5 migration, A-6 dashboard
- レビュー記録: Gemini MCP (gemini-3-flash-preview) Plan レビュー反映済み（2026-04-18）
