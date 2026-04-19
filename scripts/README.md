# scripts/ — maintainer 向け補助スクリプト

repo root で実行する maintainer / dev 専用スクリプト。配布物には含めない。

## `dogfood-dashboard.sh`

Sprint 007 (ADR 0004) で完成した dashboard を **隔離 venv** で smoke するための補助。

```bash
./scripts/dogfood-dashboard.sh                  # /tmp/zoo-trial で実施
./scripts/dogfood-dashboard.sh /tmp/my-trial    # workspace 場所を指定
./scripts/dogfood-dashboard.sh --no-build       # build skip (image 再利用)
./scripts/dogfood-dashboard.sh --cleanup-only   # zoo down + workspace 削除
```

実施内容:

1. preflight (python3 / docker daemon)
2. workspace dir + venv 作成
3. `pip install -e <repo>` で zoo CLI 注入
4. `zoo init` → `zoo build --agent claude` → `zoo up --dashboard-only`
5. dashboard ready 待ち (curl http://127.0.0.1:8080/ で 30s tries)
6. **自動検証**:
   - Network: CDN URL 不在 / `/static/app.{css,js}` 200 配信
   - CSP: `'unsafe-inline'` / CDN ドメイン不在、`default-src 'self'` / `form-action 'self'` 存在
   - Permissions-Policy: camera/microphone/geolocation/payment 全 deny
   - Security headers: X-Frame-Options DENY / X-Content-Type-Options nosniff / Referrer-Policy no-referrer
   - body 内: inline `<style>` / `style=` / `onclick=` / hx-* 不在、`<meta name="csrf-token">` 存在
7. **目視確認 prompt** (#31 コメントの A/D/F):
   - UI 表示 (Agent Zoo 見出し / 4 stat card / tab nav 4 個)
   - DevTools Console エラー 0 件
   - Tab 切替 / Filter dropdown 動作

参照: [包括レビュー M-1/L-6 resolved 確認](../docs/dev/sprints/007-dashboard-zero-deps.md) /
[#31 user smoke checklist](https://github.com/ymdarake/agent-zoo/issues/31)
