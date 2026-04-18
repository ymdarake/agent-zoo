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

## セットアップ

任意のディレクトリで `zoo init` を実行すると、パッケージに同梱された
`docker-compose.yml` / `policy.toml` / `container/` / `addons/` / `dashboard/`
などが展開されます。

```bash
mkdir ~/my-zoo && cd ~/my-zoo
zoo init .
# Workspace ready: /Users/you/my-zoo
#   cd into it and run `zoo build` then `zoo run`.

zoo build
zoo run
```

`--force` で既存ファイルを上書き、引数なしで `.` に展開されます。

## ディレクトリ構成

```
my-zoo/
├── docker-compose.yml
├── docker-compose.strict.yml
├── policy.toml              # 編集して独自ポリシーに
├── policy.runtime.toml      # zoo 実行時の書き換え用（空でOK）
├── Makefile                 # zoo の代わりに make も可
├── addons/                  # mitmproxy アドオン
├── container/               # Agent 用 Dockerfile
├── dashboard/               # 監視用 Flask アプリ
├── dns/                     # strict モードの CoreDNS
├── host/                    # ホストモードのセットアップスクリプト
├── templates/               # エージェント用プロンプト
├── certs/                   # mitmproxy CA（zoo certs で生成）
├── data/                    # SQLite ログ保存先
└── workspace/               # デフォルトの作業ディレクトリ
```

## Python API からも

```python
import zoo
zoo.init("~/my-zoo")   # 同じことをプログラムから
```

## 既存の repo clone 利用との関係

既に `git clone` したディレクトリで作業している場合、`zoo init` は不要です。
CWD 探索で同じディレクトリが自動的にワークスペースとして使われます。
