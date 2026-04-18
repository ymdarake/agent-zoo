# E2E Tests

[ADR 0003 E2E Test Strategy](../../docs/dev/adr/0003-e2e-test-strategy.md) に基づく自動テスト。

## 構成

| ファイル | スコープ | 必要環境 | CI 想定 |
|---|---|---|---|
| `test_dashboard.py` | **P1**: dashboard UI（Inbox accept/reject 等） | Python + Playwright のみ | 毎 PR |
| `test_proxy_block.py` | **P2**: proxy ドメイン制御疎通 | Docker daemon | PR or nightly |
| `test_real_agent.py` | **P3**: 実 agent + 固定 prompt（[#34](https://github.com/ymdarake/agent-zoo/issues/34)） | Docker + agent token | weekly cron / opt-in |

## 初回 Setup

```bash
# 1. e2e extras を install
uv pip install -e ".[e2e]"

# 2. Playwright バイナリ download (~150MB、初回のみ)
playwright install chromium
```

## 実行

```bash
# P1 のみ（Docker 不要、~30 秒）
pytest tests/e2e/test_dashboard.py -v

# P2 のみ（Docker 必要、~2 分）
cd bundle && make build && cd ..
pytest tests/e2e/test_proxy_block.py -v

# 全 E2E
pytest tests/e2e/ -v
```

## fixture（conftest.py）

| fixture | 内容 |
|---|---|
| `workspace` | tmp_path に ADR 0002 layout の `.zoo/` を生成（policy.toml / policy.runtime.toml / inbox/ / data/harness.db schema） |
| `dashboard` | bundle/dashboard を Flask 直起動（subprocess.Popen）→ URL を返す |
| `write_inbox_pending` | agent が submit した状態を fixture で再現（`inbox/*.toml` を直接配置） |
| `page` | pytest-playwright が提供する Chromium page object |

## デバッグ

```bash
# headed mode で見ながら実行
pytest tests/e2e/ --headed

# 各 step の動画記録
pytest tests/e2e/ --video=on

# 特定テストのみ
pytest tests/e2e/test_dashboard.py::test_inbox_accept_writes_to_runtime -v
```

## CI

- **P1** (`ci.yml` の `e2e-dashboard` job): Docker 不要、毎 PR
- **P2** (`ci.yml` の `e2e-proxy` job): GitHub Actions ubuntu-latest は Docker 標準、PR or nightly
- **P3** (`agents-realtime.yml`): weekly cron + `[agents-realtime]` PR label opt-in

## 将来の追加候補（Gemini レビュー指摘）

- **Whitelist タブ E2E**: 過去のブロック履歴 → 候補一覧 → 許可/無視フロー（`harness.db` の `blocks` テーブルに fixture 投入が必要）
- **破損 TOML 共存**: invalid TOML ファイルが 1 つあっても他の pending が表示されることの確認
- **Dedup UI**: 同一 content の pending を再 submit しても dashboard 表示が 1 件にとどまる確認
- **`_free_port` race**: 取得 → 起動の極小 race のリトライ機構

## 設計上の制約

- **agent はモック (P1)**: 実 agent (claude/codex/gemini) を起動せず、agent が submit する `inbox/*.toml` を fixture で再現。これにより Docker 不要 + 確率的応答リスク回避（[ADR 0003 D5](../../docs/dev/adr/0003-e2e-test-strategy.md#d5-agent-モック戦略-p1)）
- **port は OS 割当**: `_free_port()` で空きポートを取得、固定 8080 と衝突しない
- **DB schema は手動初期化**: `policy_enforcer.py` が import できない環境でも動くよう、conftest 内で sqlite3 schema を直接 CREATE
