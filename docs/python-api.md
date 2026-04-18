# Python API

`zoo` は CLI だけでなく Python ライブラリとしても使えます。自動化・カスタム統合・
notebook からの実験などに利用できます。

## インストール

```bash
uv tool install .        # グローバルコマンドも入る
# または
pip install .
```

## クイックスタート

```python
import zoo

# 対話モードを非同期で起動（TTY 必須）
exit_code = zoo.run(agent="claude", workspace="/path/to/my-project")

# ワンショット自律実行
import os
os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "..."
exit_code = zoo.task(prompt="テストを追加して", agent="claude")

# 起動のみ（exec しない）
zoo.up(agent="claude", workspace="/path/to/project")
# ... 何か処理 ...
zoo.down()

# ログ操作
if zoo.logs_clear():
    print("logs cleared")

```

## API 一覧

| 関数 | 戻り値 | 備考 |
|---|---|---|
| `zoo.run(*, agent, workspace, dangerous)` | `int` (exit code) | TTY attach |
| `zoo.task(*, prompt, agent, workspace)` | `int` | 環境変数による認証必須 |
| `zoo.up(*, agent, workspace, dashboard_only, strict)` | `None` | |
| `zoo.down()` | `None` | strict プロファイルも対象 |
| `zoo.reload_policy()` | `None` | policy.toml 反映 |
| `zoo.build(*, agent)` | `None` | |
| `zoo.certs()` | `None` | 存在すれば何もしない |
| `zoo.host_start()` / `zoo.host_stop()` | `int` | |
| `zoo.logs_clear()` | `bool` | 削除した場合 True |
| `zoo.logs_analyze()` / `summarize()` / `alerts()` | `int` | ホスト側 `claude` CLI 必須 |
| `zoo.test_unit()` / `zoo.test_smoke(*, agent)` | `int` | |

## 設計メモ

- `zoo.api` に純粋な関数 API を置き、`zoo.cli` は typer ラッパー
- typer / rich 依存は CLI 層のみ。API 層は stdlib + `tomllib`
- `zoo` パッケージは `docker-compose.yml` と `policy.toml` のあるディレクトリを
  CWD から親方向に探索（`zoo.runner.repo_root()`）。agent-zoo リポジトリを
  clone した場所で呼び出してください
- 長時間実行されるコマンド（`run`, `task`）は subprocess を TTY に attach します
