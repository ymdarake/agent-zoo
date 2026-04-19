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

## `check-release-cleanliness.sh`

リリース前に「変な混ざりもの」が git track 済ファイルに含まれていないかを一括検査。

```bash
./scripts/check-release-cleanliness.sh                          # 標準
./scripts/check-release-cleanliness.sh --strict                 # WARNING も fail
./scripts/check-release-cleanliness.sh -v                       # 詳細表示
./scripts/check-release-cleanliness.sh --extra-pii 'me@example.com|alice'
                                                                # 追加 PII 検出 pattern
EXTRA_PII_PATTERNS='maintainer-email-or-name' ./scripts/check-release-cleanliness.sh
                                                                # env でも渡せる (CI 用)
```

### 検査項目

**[CRITICAL]** (失敗で exit 2)

- C1: credential-like strings (PRIVATE KEY block / hardcoded api/secret/password)
- C2: credential file extensions (`.pem` / `.key` / `.env` / `.p12` / `.pfx` / `.crt`)
- C3: personal PII (generic home path `/Users/*/workspace`, `/home/*/workspace` + `--extra-pii` で追加)
- C4: cloud / SaaS token patterns (AWS access key / GitHub token / OpenAI / Claude OAuth)

**[WARNING]** (`--strict` で exit 1、それ以外 exit 0)

- W1: dev artifacts (`.DS_Store` / `__pycache__` / `.pyc` 等)
- W2: tmp / backup (`.swp` / `.bak` / `.orig` / `~`)
- W3: AI tool metadata (`.claude/` / `.cursor/` / `.windsurf/` / `.aider`)
- W4: large files (>500KB、`docs/images/*` 等の意図的画像も含むため目視判断)
- W5: TODO/FIXME/XXX in production code (CHANGELOG/BACKLOG/docs/tests 除外)

### 設計原則

**script 自体に固有名を hardcode しない**: hardcode するとその script が C3 検出対象になり矛盾。固有名は `EXTRA_PII_PATTERNS` env or `--extra-pii` arg で渡す。CI では GitHub secret 経由で注入推奨。
