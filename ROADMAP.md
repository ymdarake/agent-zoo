# ROADMAP

Agent Harnessの未実装機能と将来の拡張計画。

実装済み機能は [agent-harness-design.md](agent-harness-design.md) のセクション11を参照。

---

## 未実装（設計済み）

### セキュリティ強化

- [ ] **ペイロードのデコード+再検査**: Base64, Hex, URL encodingをデコードしてからblock_patterns/secret_patternsを適用。難読化によるバイパスを防止
- [ ] **エントロピーチェック**: ペイロード内の高エントロピー文字列（暗号化データの疑い）を検知。`[payload_rules.advanced] entropy_threshold = 4.5`
- [ ] **ダッシュボード認証**: Basic認証 or APIキー。環境変数`DASHBOARD_USER`/`DASHBOARD_PASS`で設定。CSRF対策（カスタムヘッダチェック）
- [ ] **suspicious_argsのワード境界マッチ**: 現在の部分文字列マッチ（`.env`が`environment`にもマッチ）を正規表現のワード境界付きに改善
- [ ] **policy.tomlのファイルロック**: 同時書き込みのlost update防止。`fcntl.flock`で直列化

### 運用改善

- [ ] **Dockerスモークテストの合否判定**: exit codeベースの自動判定（CI連携用）
- [ ] **tool_uses テーブルのinputサイズ制限**: 先頭N文字のみ保存してDB肥大化を防止
- [ ] **CoreDNSとpolicy.tomlの自動同期**: allow list変更時にCorefileを動的生成してリロード
- [ ] **ログクリア機能**: `make clear-logs` ターゲット（全削除 or 日付指定）
- [ ] **コミュニティdenyリスト共有**: ブロックドメイン+理由の匿名集約、JSON/TOML形式でGitHub Gist等に公開

---

## 将来の拡張

### tool_useリアルタイムブロック

SSEストリーミング中のtool_useを検知し、危険と判定した時点で接続を切断してtool実行を阻止する。

**背景**: 現在はtool_useのログ・アラートのみ。`content_block_stop`イベント到達時に全貌が判明するため、それ以前のdeltaチャンクはClaude Codeに透過済みだが、stopなしにはtoolは実行されない。

**実装方式**:

| 方式 | 動作 | レイテンシ | 確実性 |
|---|---|---|---|
| A: バッファリング | tool_useチャンクをバッファ、stop時に一括送信 or 破棄 | tool_useブロック分の遅延 | 高（deltaが届かない） |
| B: 事後キル | deltaは即透過、stop時に危険なら接続切断 | なし | 十分（stop前に実行されない） |

**方式Bを推奨**。シンプルで、Claude Codeの仕様上`content_block_stop`なしにtool実行はしないため安全。

**設定例**:
```toml
[tool_use_rules]
block_tools = []                    # 完全ブロックするツール名
block_args = ["~/.ssh/id_rsa"]     # 引数にマッチしたらブロック
alert_only_tools = ["Bash"]        # ログのみ（現状の挙動）
```

### agentgateway統合

MCPサーバーへのルーティングをagentgateway経由にし、MCP/A2Aプロトコルレベルでの制御を実現。

### LlamaFirewall的なインライン検出

tool_useパターン検出を正規表現ベースからMLベースに拡張。Meta LlamaFirewallのガードレール設計を参考に、プロンプトインジェクション検出やツール使用の異常検知を組み込む。

### Matchlock的なシークレットインジェクション

mitmproxyで実行時に認証情報を置換。エージェントに秘密情報を直接渡さず、API呼び出し時にプロキシが自動でトークンを付与する。
