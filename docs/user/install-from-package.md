# パッケージからのインストール

`agent-zoo` は clone せずにパッケージとしてインストールして使えます。

## インストール

```bash
# uv 推奨
uv tool install agent-zoo         # PyPI 公開後
uv tool install git+https://github.com/ymdarake/agent-zoo  # 現状はこちら
# pip も可
pip install agent-zoo
```

### TestPyPI (プレリリース検証用)

公式リリース前の動作確認は TestPyPI からインストールできます。
依存関係は本番 PyPI から解決するために `--extra-index-url` を指定します。

```bash
# pip
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            agent-zoo

# uv tool
uv tool install --index-url https://test.pypi.org/simple/ \
                --extra-index-url https://pypi.org/simple/ \
                agent-zoo
```

> TestPyPI は同一バージョンの再アップロードを禁じているため、
> 検証時は `pyproject.toml` の `version` を `.devN` / `rcN` などで
> インクリメントしてから workflow を再実行してください。

## セットアップ（ADR 0002 新 layout）

任意のディレクトリで `zoo init` を実行すると、パッケージに同梱された harness 一式が
**`<workspace>/.zoo/` 配下** に展開されます。user の作業ディレクトリは workspace 直下、
zoo の管理ファイルは `.zoo/` 配下に分離されるため、user の workspace が散らかりません。

```bash
mkdir ~/my-zoo && cd ~/my-zoo
zoo init                  # ./.zoo/ 配下にハーネスを展開、./.gitignore も生成
zoo build                 # base + agent イメージをビルド
zoo run                   # 対話モードで claude を起動（初回は /login）
```

`--force` で既存ファイルを上書き、引数なしで `.` に展開されます。

## ディレクトリ構成（ADR 0002）

```
~/my-zoo/                    # user の workspace root
├── .gitignore               # 生成: `.zoo/` 1 行で全 runtime artifact 除外
├── .zoo/                    # zoo 管理ファイル（user は普段触らない）
│   ├── docker-compose.yml
│   ├── docker-compose.strict.yml
│   ├── policy.toml          # 編集して独自ポリシーに（既存は尊重）
│   ├── policy.runtime.toml  # dashboard が書き込む runtime 状態
│   ├── addons/              # mitmproxy アドオン
│   ├── container/           # Agent 用 Dockerfile（claude/codex/gemini/unified）
│   ├── dashboard/           # 監視用 Flask アプリ
│   ├── dns/                 # strict モードの CoreDNS
│   ├── host/                # ホストモードのセットアップスクリプト
│   ├── templates/           # エージェント用 HARNESS_RULES.md 等
│   ├── certs/               # mitmproxy CA（zoo certs で生成）
│   ├── data/                # SQLite ログ保存先（harness.db）
│   └── inbox/               # ADR 0001: agent からの policy リクエスト
└── src/                     # user 自身のコード（任意）
```

`zoo` CLI は CWD から `.zoo/docker-compose.yml` を walk-up で検出するため、
workspace root（または配下のサブディレクトリ）からどこで `zoo` コマンドを
叩いても自動的に正しい `.zoo/` を解決します。

## Python API からも

```python
import zoo
zoo.init("~/my-zoo")   # 同じことをプログラムから
```

## Maintainer 向け（agent-zoo source repo の dogfood）

agent-zoo の source repo（git clone）では、配布資材は **`bundle/` 配下**にまとまっており、
**source repo 直下では `zoo` CLI は動きません**（ADR 0002 D7、`.zoo/` が無いため）。

開発時の動作確認は 2 通り:

1. **`bundle/` で直接 make を叩く** — `cd bundle && make build && make test`
2. **別ディレクトリで `zoo init` する** — `pip install -e .` 後、別 dir で `zoo init` → そこで `zoo run` 等

詳細は [ADR 0002 D7](adr/0002-dot-zoo-workspace-layout.md#d7-source-repo-bundle-と配布先-zoo-の命名分離) を参照。
