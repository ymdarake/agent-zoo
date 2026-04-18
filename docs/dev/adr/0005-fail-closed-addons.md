# ADR 0005: mitmproxy Addon の Fail-closed 化

| 項目 | 値 |
|---|---|
| 日付 | 2026-04-19 |
| ステータス | Accepted |
| 起点 | [2026-04-18 包括レビュー](../reviews/2026-04-18-comprehensive-review.md) C-2（Gemini 2.5 Pro 検出） |
| 実装 Sprint | Sprint 005 PR A |

---

## Context

agent-zoo は mitmproxy addon (`policy_enforcer.py`) で全外向きトラフィックを検査・制御する「セキュリティハーネス」を謳う。しかし mitmproxy v10.x の `AddonManager` は addon 内で未捕捉例外が発生した場合、エラーをログ出力するだけで **フロー自体は通過させる**（fail-open の挙動）。

```python
# mitmproxy の概念コード
for addon in addons:
    try:
        addon.request(flow)
    except Exception as e:
        logger.error(f"addon {addon} raised: {e}")
    # ← flow はそのまま upstream に送られる
```

これは以下の致命的リスクを伴う:

1. **policy.toml 解析ミス / maybe_reload race** で `KeyError` / `AttributeError` が出ると全ポリシーが bypass
2. **SSE parser の edge case** で `TypeError` 等が出ると tool_use ブロックが無効化
3. **DB 接続切断** で `sqlite3.OperationalError` が出るとログ記録が抜け、事後検知も不能
4. **悪意 agent** が意図的に addon を crash させる input を送り込めば 単一 exception で全防御が外れる

セキュリティ製品としての前提「検査が壊れていれば必ず deny」を守るには、**fail-closed** 設計が必須。

## Decision

`bundle/addons/_fail_closed.py` に **hook 種別ごとの decorator** を用意し、`policy_enforcer.py` の全 mitmproxy event hook に適用する。

### Decorator 一覧

| decorator | 対象 hook | 例外時の動作 |
|---|---|---|
| `@fail_closed_block` | `request`, `response` | `flow.response = http.Response.make(500, ...)` で block。upstream 送出 / client 返却を強制遮断 |
| `@fail_closed_ws_message` | `websocket_message` | `flow.websocket.messages[-1].drop()` で当該メッセージを agent に届けない |
| `@fail_closed_lifecycle` | `websocket_end`, `done` | ログのみ（cleanup 段階で flow 遮断手段がないため）|

### 実装原則

- **再 raise しない**: 必ず `try/except Exception` で吸収し、mitmproxy 本体や他 addon に伝播させない
- **ログは必ず出す**: `ctx.log.error` に `addon <Class>.<method> raised <ExcType>: <msg> — fail-closed triggered` 形式。運用側で alert / tail -f watch 可能
- **ログ出力自体の失敗も無害化**: `ctx` が未セットアップ（import 直後 / テスト環境）の場合は `print(..., file=sys.stderr)` にフォールバック
- **drop 系の失敗も吸収**: `flow.websocket.messages[-1].drop()` が壊れても再 raise しない

### 500 ステータスコードを選ぶ理由

通常の policy block は 403（Forbidden、policy 判定）。500 は **addon 側のバグ / 内部エラーによる block** を示唆し、運用ログから区別しやすい。agent 側には「upstream は応答を返したが proxy が壊れている」と認識され、retry されても同じエラーが続くため結果的に通信停止。

## Alternatives Considered

### A. mitmproxy 設定で "kill-on-error" にする

mitmproxy には `--set keep_host_header` 等の設定はあるが、「addon error 時に flow kill」のグローバル設定は無い（少なくとも v10.x では）。addon 側実装でしか対応できない。

### B. 全 hook の本体を 1 重の try/except で囲む（decorator を使わない）

```python
def request(self, flow):
    try:
        self.engine.maybe_reload()
        # ... 長い処理 ...
    except Exception as e:
        ctx.log.error(...)
        flow.response = ...
```

- **デメリット**: 各 hook に同じ boilerplate が散らばり、追加時の漏れリスク。hook 種別ごとの block 方式（`response` 置換 vs `message.drop()` vs ログのみ）を個別に覚える必要がある
- **採用しなかった理由**: DRY + 宣言的な方が read/audit しやすい

### C. カスタム mitmproxy middleware でグローバルラップ

addon ではなく mitmproxy の `events.py` を改造する案。
- **デメリット**: mitmproxy の upgrade 追従が困難、fork 維持コスト
- **採用しなかった理由**: 配布物としての保守性が悪い

## Consequences

### Positive

- **セキュリティ製品としての契約 (fail-closed) が実装で担保される**
- 新しい hook を追加するときも decorator を忘れなければ自動で protection される
- テスト (`tests/test_addon_fail_closed.py` 12 件) で decorator の振る舞いを独立検証可能
- ログから「addon が壊れた瞬間」が特定しやすい（事後調査容易）

### Negative

- decorator 層が増えることで、policy_enforcer.py の hook 実装を trace する時に 1 段深くなる → コードリーディングの摩擦
- 500 を返すようにしたため、upstream (allow list 内のドメイン) への本来通すべきリクエストも addon bug があれば止まる → **意図した挙動**だが、user 側には「policy 壊れている = 作業止まる」体感になり、迅速な調査が必要

### Neutral

- 既存 policy 判定で設定される `flow.response` (403 block / 429 rate limit / 403 payload block) は decorator に触られない（例外が起きない限り通過）
- mitmproxy v11.x 以降で fail-closed 挙動が native に入った場合、本 decorator は冗長になるが依然として correctness を担保する層として残す価値あり

### Known Limitations (follow-up)

#### addon load 失敗時の挙動

`PolicyEnforcer.__init__` 自体で例外が発生した場合、mitmproxy は addon 無しで起動してしまう（= fail-open）。本 PR のスコープは hook レベルの fail-closed のみで、addon load レベルは未対応。

対応案:
- A: `__init__` で全例外を catch し `sys.exit(1)` で mitmproxy プロセス停止（container restart policy で agent 起動を防ぐ）
- B: `__init__` 内で `self._init_failed = True` を立て、hook の最初で check して 500 を返す

次の follow-up PR（Sprint 005 の C 以降）で対応する。

#### mitmproxy 制御例外の透過

`_MITMPROXY_CONTROL_EXCEPTIONS` (`AddonHalt`, `OptionsError` 等) は decorator が吸収せず再 raise する。これにより mitmproxy 本体の addon 実行チェーン制御が破壊されない。現状 `policy_enforcer.py` は使用していないが、将来 addon 拡張時の足枷を防ぐ防御的実装。

#### HTTP status 500 vs 502/503 の選択

fail-closed 時に返す status code は **500** を採用。検討した代替案:
- `502 Bad Gateway`: proxy 側の内部問題を明示するが意味的に "upstream が応答しなかった" に近い
- `503 Service Unavailable` + `Retry-After`: agent の retry 間隔を制御できるが、retry 自体を促進してしまう

現状 500 としているが、agent 側の retry 挙動（一部 CLI は 5xx で exponential backoff）が運用ログを汚染する可能性がある。実測後に 502/503 への変更を検討（follow-up）。

#### SSE / streaming response の block 粒度

`response` hook はデフォルトで **response 全体をバッファリング** してから呼ばれるため (mitmproxy 10.x は stream callable 非対応、ROADMAP)、decorator の `flow.response = 500` 置換は正常に効く。将来 streaming 対応を復元する場合は:
- streaming mode では response header 送出済みのケースで 500 置換が無効化される
- その場合は `flow.kill()` で接続全体を切断して fail-closed を担保する必要がある
- 現 `fail_closed_block` decorator は非 streaming 前提で最適化されており、streaming 復元時に decorator 側で「streaming 検知 → flow.kill()」の分岐を追加する必要がある

#### WebSocket drop 失敗時の最終防衛線

`flow.websocket.messages[-1].drop()` が例外で失敗した場合、decorator は `flow.kill()` で接続全体を強制切断する（fail-closed 最終防衛線）。`kill()` 自体が失敗した場合はログ出力のみで諦める（極端な内部状態、実害は該当メッセージ 1 件の漏洩に限定）。

## Test Strategy

`tests/test_addon_fail_closed.py`（12 ケース）:

- `fail_closed_block`:
  - 正常完了で flow.response を触らない
  - hook が明示設定した response (policy 403 など) を保持する
  - 例外時に 500 response で置換
  - 決して再 raise しない
- `fail_closed_ws_message`:
  - 例外時に最後の message を drop
  - websocket None / messages 空でも raise しない
  - 正常完了時に drop を呼ばない
- `fail_closed_lifecycle`:
  - 例外時にログのみ、return None
  - 正常完了時に return 値を透過
  - `(self, flow)` 2 引数 hook にも対応
- ログフォールバック:
  - ctx.log.error が失敗しても stderr に出力

`mitmproxy` のランタイム依存は `sys.modules` shim で test env から排除。

## References

- 包括レビュー [C-2 (Gemini 2.5 Pro 検出)](../reviews/2026-04-18-comprehensive-review.md#c-2-gemini-g-1-new-critical-mitmproxy-addon-の未捕捉例外でポリシーバイパスfail-open)
- 統合作業計画 [Sprint 005 PR A](../../plans/2026-04-18-consolidated-work-breakdown.md#pr-a-mitmproxy-addon-fail-closed-化c-2)
- mitmproxy AddonManager implementation: https://github.com/mitmproxy/mitmproxy
