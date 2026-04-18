# インストールとセットアップ

`agent-zoo` はパッケージとしてインストールして使います（clone 不要）。

## インストール

```bash
# uv 推奨
uv tool install agent-zoo         # PyPI 公開後
uv tool install git+https://github.com/ymdarake/agent-zoo  # 現状はこちら
# pip も可
pip install agent-zoo
```

## セットアップ

任意のディレクトリで `zoo init` を実行すると、harness 一式が
**`<workspace>/.zoo/` 配下** に展開されます。作業ディレクトリは workspace 直下、
zoo の管理ファイルは `.zoo/` 配下に分離されるため、作業ディレクトリが散らかりません。

```bash
mkdir ~/my-zoo && cd ~/my-zoo
zoo init                  # ./.zoo/ 配下にハーネスを展開、./.gitignore も生成
zoo build                 # base + agent イメージをビルド
zoo run                   # 対話モードで claude を起動（初回は /login）
```

`--force` で既存ファイルを上書き、引数なしで `.` に展開されます。

## ディレクトリ構成

```
~/my-zoo/                    # workspace root
├── .gitignore               # 生成: `.zoo/` 1 行で全 runtime artifact 除外
├── .zoo/                    # zoo 管理ファイル（普段触らない）
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
│   └── inbox/               # agent からの policy 許可リクエスト
└── src/                     # 自分のコード（任意）
```

`zoo` CLI は CWD から `.zoo/docker-compose.yml` を walk-up で検出するため、
workspace root でもその配下のサブディレクトリでも、どこで `zoo` コマンドを
叩いても自動的に正しい `.zoo/` を解決します。

## Python API からも

```python
import zoo
zoo.init("~/my-zoo")   # 同じことをプログラムから
```
