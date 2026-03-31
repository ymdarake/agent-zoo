# TODO

## 完了

- [x] devtool MCP設定（chrome-devtools-mcp@0.20.3、Node.js 22.12.0）
- [x] ROADMAPの整理
- [x] ホワイトリスト、ブロックリストのリストUI（Current Policy表示）
- [x] パスベースの許可UI改善（URLクリック→パスパターン自動入力）
- [x] tool_use反映（バッファリング方式に変更、9件確認済み）
- [x] Restoreボタン修正（base/runtime分離、runtime側のみRestore可能に）
- [x] ホワイトリストページのインジケーター固定（Jinja2 loop.parent修正）
- [x] ドキュメント整備（README/CLAUDE.md/ROADMAP.md最新化）
- [x] レビュー陣と総チェック（Claude + Gemini 2段階）

## 未対応

- [x] 許可したものを逆に戻す操作（Revoke機能、runtime設定のみ✕ボタンで取り消し可能）
- [ ] SSEストリーミング透過の復元（mitmproxyのstream callable対応待ち。現在はバッファリングでレイテンシ増加）
- [ ] ダッシュボードのフィルタリング・検索機能
- [ ] ダッシュボードのHTMXローディングインジケータ
