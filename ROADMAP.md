# ROADMAP

Agent Harnessの未実装機能と将来の拡張計画。

実装済み機能は [agent-harness-design.md](agent-harness-design.md) のセクション11を参照。

---

## ~~P0: クイック修正~~ ✅ 完了

- [x] **suspicious_argsのワード境界マッチ**: 非英数字/アンダースコア境界チェックに改善
- [x] **tool_usesテーブルのinputサイズ制限**: `max_tool_input_store=1000` + truncatedマーカー
- [x] **Dockerスモークテストの合否判定**: exit codeベースの自動判定

## P1: セキュリティ強化（主要完了）

- [x] **ペイロードのデコード+再検査**: URLデコード→Base64デコード→再検査（1段階のみ）
- [x] **policy.tomlのファイルロック**: `fcntl.flock`コンテキストマネージャで排他制御
- [ ] **ダッシュボード認証**: Basic認証 or APIキー（localhost専用のため優先度低）

## P2: 機能強化（運用品質の向上）

- [x] **tool_useリアルタイムブロック**: 方式B（事後キル）で実装。`[tool_use_rules]`セクション追加
- [x] **ログ管理**: `make clear-logs` + `log_retention_days=30`自動ローテーション + tsインデックス
- [x] **アラートルールの組み合わせ条件**: `[[alerts.rules]]`で複合条件を配列定義。ルール内AND、ルール間OR
- [ ] **CoreDNSとpolicy.tomlの自動同期**: allow list変更時にCorefileを動的生成してリロード
- [ ] **エントロピーチェック**: ペイロード内の高エントロピー文字列（暗号化データの疑い）を検知。`[payload_rules.advanced] entropy_threshold = 4.5`

- [ ] **OpenAI形式のtool_calls対応**: 現在のSSEパーサーはAnthropic API形式（content_block_start/delta/stop）に特化。OpenAI形式（tool_calls/function_call）のストリーミングパーサーを追加し、Codex CLI等のOpenAI互換エージェントにも対応する

## P3: 将来の拡張（エコシステム）

### LiteLLM的な設定ファイルベースの認証管理

現在は`CLAUDE_CODE_OAUTH_TOKEN`環境変数で毎回渡す方式。将来的にLiteLLMのような設定ファイル（YAML/TOML）でモデル別の認証情報・エンドポイント・パラメータを一元管理できるようにする。複数のLLMプロバイダやモデルを切り替えてエージェントを実行するユースケースに対応。

### シークレット保護の現実的な整理

エージェントが開発中のアプリを起動する場合（`npm run dev`等）、アプリが必要とするAPIキーやDB接続文字列はエージェントコンテナに渡すしかない。Docker SecretsやMatchlock方式で隠しても、アプリが起動できなければ意味がない。

**結論: ネットワーク隔離（読めても送れない）が唯一の現実的な防御。** `payload_rules.secret_patterns`でAPIリクエスト内の既知パターンを検知・ブロックし、`alerts`で不審なアクセスを事後検知する。

### エージェントツール設定テンプレート拡充

`templates/` ディレクトリに各ツールの推奨設定を追加:
- Codex CLI
- Aider
- Cline

### agentgateway統合

MCPサーバーへのルーティングをagentgateway経由にし、MCP/A2Aプロトコルレベルでの制御を実現。

### LlamaFirewall的なインライン検出

tool_useパターン検出を正規表現ベースからMLベースに拡張。Meta LlamaFirewallのガードレール設計を参考に、プロンプトインジェクション検出やツール使用の異常検知を組み込む。

### コミュニティdenyリスト共有

ブロックドメイン+理由の匿名集約、JSON/TOML形式でGitHub Gist等に公開。`policy.toml`に`[community_deny]`セクションを追加し、URLを指定すると定期的にフェッチしてdenyリストにマージ。

---

### tool_useリアルタイムブロックの設計メモ

`content_block_stop`イベント到達時に全貌が判明するため、それ以前のdeltaチャンクはClaude Codeに透過済みだが、stopなしにはtoolは実行されない。

| 方式 | 動作 | レイテンシ | 確実性 |
|---|---|---|---|
| A: バッファリング | tool_useチャンクをバッファ、stop時に一括送信 or 破棄 | tool_useブロック分の遅延 | 高（deltaが届かない） |
| B: 事後キル | deltaは即透過、stop時に危険なら接続切断 | なし | 十分（stop前に実行されない） |

**方式Bを推奨**。

```toml
[tool_use_rules]
block_tools = []                    # 完全ブロックするツール名
block_args = ["~/.ssh/id_rsa"]     # 引数にマッチしたらブロック
alert_only_tools = ["Bash"]        # ログのみ（現状の挙動）
```
