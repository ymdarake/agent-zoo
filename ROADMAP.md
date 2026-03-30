# ROADMAP

Agent Zooの未実装機能と将来の拡張計画。

---

## 未実装（優先度順）

### セキュリティ

- [ ] **ダッシュボード認証**: Basic認証 or APIキー（localhost専用のため優先度低）
- [ ] **エントロピーチェック**: ペイロード内の高エントロピー文字列を検知。`[payload_rules.advanced] entropy_threshold = 4.5`

### 運用

- [ ] **CoreDNSとpolicy.tomlの自動同期**: allow list変更時にCorefileを動的生成してリロード

### マルチプロバイダ対応

- [ ] **OpenAI形式のtool_calls対応**: SSEパーサーにOpenAI形式（tool_calls/function_call）を追加。`BaseSSEParser`を継承して`_handle_data`を実装するだけ

## 将来の拡張

- **LiteLLM的な設定ファイル認証管理**: YAML/TOMLでモデル別の認証情報・エンドポイントを一元管理
- **エージェントツールテンプレート拡充**: Codex CLI、Aider、Clineの推奨設定を`templates/`に追加
- **agentgateway統合**: MCP/A2Aプロトコルレベルでの制御
- **LlamaFirewall的なML検出**: tool_useパターン検出をMLベースに拡張
- **コミュニティdenyリスト共有**: ブロックドメイン+理由の匿名集約・公開

## 実装済み

Phase 1-3 + P0-P2。詳細は [agent-harness-design.md](agent-harness-design.md) のセクション11を参照。

主な実装済み機能:
- ドメイン制御 + パスベースallow/deny
- レート制限（RPM + burst 2段階）
- ペイロード検査（正規表現 + Base64/URLデコード再検査）
- SSE tool_useキャプチャ + リアルタイムブロック
- アラート（独立条件 + 組み合わせルール）
- ダッシュボード（ログ閲覧 + ホワイトリスト育成UI）
- CoreDNS strictモード
- ホストモード
- CLI分析（make analyze/summarize/alerts）
- policy.toml + policy.runtime.toml 分離
