# Security Notes（dev-only）

本ドキュメントは **開発者向け** の security 設計メモです。具体的な bypass 例 / 緩和の限界 / 将来の強化案 を扱います。`docs/user/` には抽象的な警告のみ残し、具体的な攻撃ベクタ情報は本ファイルに集約しています。

---

## `tool_use_rules.block_args` の bypass 例（M-7 related）

`bundle/addons/policy.py::PolicyEngine._match_word_boundary` は次の regex を用います:

```python
re.search(rf'(?:^|[^a-zA-Z0-9_]){escaped}(?:$|[^a-zA-Z0-9_])', text)
```

つまり「パターン前後が英数字・アンダースコア以外のいずれか」という緩い境界条件。以下は `block_args = ["rm -rf /"]` が設定されていても通過する攻撃例です（LLM agent 自身が生成しうる）:

| # | bypass 例 | 原因 |
|---|---|---|
| 1 | `rm  -rf /` (空白 2 つ) | 本体のパターン `rm -rf /` は単一スペース前提、連続空白でマッチしない |
| 2 | `/bin/rm -rf /` | 直前が `/`、直前文字が「非英数字」なので「`rm -rf /` が別文脈で現れている」とみなされるが、正規表現が語尾 `/` + 英数字扱いのため連続境界に収まらない |
| 3 | `R="rm -rf"; eval "$R /"` | パターン全体が引数文字列内に現れず、string split で bypass |
| 4 | `python -c 'import os; os.system("rm -rf /")'` | パターンは含まれるがコマンド interpreter を介している |
| 5 | `busybox rm -rf /` | pattern 直前が `busybox ` で match するが、`/` 末尾で match failure するケースあり（実装による） |
| 6 | `X=rm; Y=-rf; $X $Y /` | env 変数による分割 |

**要点**: LLM のコマンド生成能力に対して文字列パターンマッチ単独で完全防御することは本質的に困難です。`block_args` は「**既知の正面攻撃に対する早期検知ログ**」と位置づけ、最終防御は **ネットワーク隔離 (`domains.allow` を最小化)** で担保するのが安全な運用です。

### 緩和方針（将来）

1. **AST/syntax-level parsing**: Bash / Python 等のコマンド AST を解析し、`rm -rf /` 相当を semantic に検知（false positive / CPU cost 増）。
2. **ML ベースの tool_use 分類**: LlamaFirewall 的なアプローチ（ROADMAP 項目）。
3. **capability-based restriction**: コンテナ側で `/` への書き込みを read-only mount で物理的に防ぐ（PR H-3 で一部実施）。

---

## URL scrub の設計根拠（M-2 related）

`bundle/addons/policy_enforcer.py::scrub_url` は以下 3 要素を redact します:

| 要素 | 処理 | 理由 |
|---|---|---|
| `userinfo` (`user:pass@`) | `[redacted]@` 置換 | Basic Auth 認証情報の漏洩防止 |
| `query` (`?...`) | `?[redacted]` 置換（query 存在は保持） | API key / token 漏洩防止、dashboard 表示での可観測性維持 |
| `fragment` (`#...`) | 削除 | OAuth implicit flow 等の token 漏洩防止 |

`scheme` / `host` / `port` / `path` は原文維持（ドメイン / パス別集計に必要）。

### parse 失敗時

`urlsplit` が例外を投げるケース（極端な malformed URL）は fixed string `[invalid-url]` を返します。元 URL を attacker-controlled のまま DB に入れないため。

### 代案比較

- **query 完全削除**: dashboard で「どの endpoint が呼ばれたか」の path-only 集計は残るが、`?` の有無が消えるのでリクエストパターン観察性が減る
- **query key 名保持** (`?api_key=[redacted]&foo=[redacted]`): key 名が機密 (`api_key` 自体を隠したい) のケースで不十分
- **現行採用: `?[redacted]` placeholder**: query 存在は分かる / 値は完全隠蔽 の中庸

### Content-Length fail-closed (M-6)

`scrub_url` と一体で実装されている 1MB 超 body の事前遮断:

```python
content_length = _parse_content_length(flow.request.headers.get("content-length"))
if content_length is not None and content_length > _MAX_BODY_BYTES:
    flow.response = http.Response.make(413, ...)
    return
```

**設計根拠**: mitmproxy の `--set body_size_limit=1m` は OOM 保護として必要だが、それ単独では「大きな body は stream pass-through」になり secret_patterns 検査が silently bypass される恐れ（fail-open）。addon 側で Content-Length 前チェックを追加することで fail-closed 原則を担保。

**既知の制約**: `Transfer-Encoding: chunked` で Content-Length header が無いケースは addon 前チェックでは弾けない。このケースは mitmproxy の stream 側で自然に body_size_limit に抵触して検知される（OOM は防げる、ただし secret_patterns 検査は skip）。完全対応には request body streaming 解析が必要で Sprint 007 以降。

---

## harness.db の file 権限（G3-B1 related）

`bundle/addons/policy_enforcer.py::_secure_db_file` は以下 3 ファイルを chmod 600 します:

- `harness.db` 本体
- `harness.db-wal` (SQLite WAL journal、PRAGMA journal_mode=WAL 時に生成)
- `harness.db-shm` (WAL shared memory index)

### umask vs 明示 chmod

代案として container entrypoint で `umask 0077` を設定する方法もあります。本実装では chmod 明示を採用:

- **pros**: audit log から追跡可能、既存 entrypoint 改変なし、SQLite 内部の file 生成タイミングを気にしない
- **cons**: `_init_db` が reload で複数回呼ばれた時に chmod overhead（許容範囲）

### bind mount 環境での EPERM 耐性

Docker bind mount で `/data` が host UID 未満から mount されているケース等で chmod が EPERM を返すことがあります。本実装は `try / except OSError` で包み `ctx.log.error` へ記録して処理を継続します（fail-safe）。権限強制失敗時のユーザー通知は log review に任せる方針。

### symlink follow 抑止 (self-review M-1)

`os.chmod` は default で symlink を follow するため、attacker が `/data/harness.db` を `/etc/something` への symlink に置換できれば外側 path を 600 化される TOCTOU 余地があります。本実装は `os.chmod(path, 0o600, follow_symlinks=False)` を優先し、Linux で AT_SYMLINK_NOFOLLOW が未対応の場合は `os.path.islink(target)` で symlink 検出して chmod を skip し log で通知します。

### WAL/SHM rotation で chmod 600 が剥がれる既知制約 (self-review M-5)

SQLite は `wal_autocheckpoint`（default 1000 pages）で WAL を自動 truncate/recreate します。recreate された WAL/SHM は proxy プロセスの umask に従い、container default では 0o644 になる可能性があります。完全防御には container entrypoint で `umask 0077` を設定するか、bind mount の host 側 ACL でも制限する 2 段防御が必要です。本実装は chmod 600 を `_init_db` で 1 回保証する暫定対応で、完全な権限維持は ROADMAP 行き。

---

## domain validation の strict regex（M-5 related）

`bundle/dashboard/app.py::_DOMAIN_RE` は RFC 1035 label 準拠:

```python
_LABEL_RE = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_DOMAIN_RE = re.compile(rf"^(\*\.)?({_LABEL_RE}\.)+{_LABEL_RE}$")
```

### behavior change 詳細

UI から `localhost` や `*.com` を追加できなくなります。これらは base `policy.toml` の直接編集でのみ設定可能。user environment で単一ラベル内部 host (`mailserver` 等) や TLD-only wildcard (`*.internal` 等) を使いたい場合は base policy に手書きで維持してください。

### IDN (Unicode) の扱い

現 regex は ASCII のみ許可。Punycode (`xn--foo.example.com`) は通過しますが、生の Unicode (`日本.example`) は reject されます。IDN 対応は ROADMAP 行き（将来 `idna` ライブラリ経由で内部 Punycode 正規化）。

---

## サプライチェーン: SHA pin 運用 (Sprint 006 PR E related)

### Docker image SHA pin の前提

`bundle/container/Dockerfile.base` 等で `FROM <image>@sha256:...` 形式で digest pin しています。`@sha256:` は **マルチアーキテクチャ manifest list の digest** を使うこと。特定 arch (linux/amd64 のみ等) の image manifest digest を pin すると、Apple Silicon ホストで `no matching manifest for linux/arm64` で `zoo build` が失敗します。

**新 SHA を Dependabot PR で受け入れる前のチェック**:
```bash
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/node:pull" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -sH "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  "https://registry-1.docker.io/v2/library/node/manifests/<NEW_SHA>" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['mediaType']); [print(' ', m.get('platform')) for m in d.get('manifests', [])]"
```

`mediaType` が `manifest.list.v2+json` または `image.index.v1+json` であり、`manifests[].platform` に `amd64` と `arm64` の両方が含まれていることを確認してください。

### `pypa/gh-action-pypi-publish` の branch ref vs tag SHA

PyPI publish action は `release/v1` という **branch ref** で配布されています。SHA pin する際は同じ commit を指す **tag (`v1.14.0` 等)** の SHA を使うこと。コメントを `# v1.14.0` にすることで Dependabot が tag based で新版検出できます。`# release/v1` のままだと Dependabot は branch HEAD を追跡できず更新 PR が来ない（branch ref には SemVer が無い）。

### tag rewrite (force tag) 検出時の判定

Dependabot PR で **同じ tag (`v1.14.0`) なのに SHA が変わっている** ケースは、上流 maintainer が tag を別 commit に force-update した可能性があります。これは git tag の信頼性に関わる事象なので、安易に accept せず:

1. 上流リポジトリ (`pypa/gh-action-pypi-publish`) の releases / CHANGELOG / commits ページで該当 tag の歴史を確認
2. tag rewrite の理由 (typo 修正 / 緊急 hotfix 再リリース等) が release notes に記載されているか確認
3. 不審な場合は **古い SHA を維持** し、上流 issue / discussion で理由を確認するまで Dependabot PR は merge しない

SHA pin 時点での合意「この commit を信頼する」が壊れるイベントなので、blind merge は避けます。

### `pip-audit` の運用

CI では `uv tool run pip-audit --vulnerability-service osv` で project 全体、`uv tool run pip-audit -r bundle/dashboard/requirements.txt --vulnerability-service osv` で dashboard 別 audit を走らせています。

**`--ignore-vuln` のガードレール**: 安易な ignore は hardening の意味を失います。**ignore を追加するとき**は:

- security 担当 reviewer の approval を必須にする (PR review コメントで明示)
- `<GHSA-id> | 理由 | 受容期限 (例: 2026-07-01)` を本ファイルに記録
- 受容期限切れは BACKLOG に追跡項目として上げ、再評価する

**false positive 対応**: 既知だが受容するケースは `--ignore-vuln <GHSA-id>` で除外。例:
```yaml
- name: Audit
  run: uv tool run pip-audit --ignore-vuln GHSA-xxxx-yyyy-zzzz
```

ignore は **期限付きで期限切れに気付ける運用** が理想ですが、現状は最低限「除外時は本ファイルに `<GHSA-id> | 理由 | 受容期限` を記録する」運用で。

**`--strict` の意味**: `--strict` は metadata fail を error 扱いに昇格するもので「CVE warning を error に」ではない。CVE 検出時は `--strict` 無しでも exit != 0。`--strict` を付けると `tool.uv.exclude-newer` 等で metadata 取得失敗するパッケージで CI が落ちうるため、本実装では付けていません。

### npm CLI 版固定 (defer)

`bundle/container/Dockerfile` 等で `npm install -g @anthropic-ai/claude-code` をバージョン指定なしで install しています。Docker image SHA pin で base layer は固定されますが、build 時の npm registry の状態で **agent CLI のバージョンが変わる**ため bit-for-bit の再現性は完全ではありません。

将来 PR で `@anthropic-ai/claude-code@<version>` の形に固定する想定（現状は CLI 自体が頻繁に更新されるため lockstep でメンテすると追従コスト高）。BACKLOG ROADMAP に追記。

### Hash pin (uv.lock activation, defer)

`bundle/dashboard/Dockerfile` の `pip install --no-cache-dir -r requirements.txt` は **hash 検証なし**。`pip install --require-hashes` + `pip-compile --generate-hashes` で hash 入り requirements.txt を生成する運用への移行は ROADMAP 行き。同様に `Dockerfile.base` で `uv sync --frozen --locked` で `uv.lock` を build 時にアクティベートする案も保留。

## policy_lock の cross-container 協調（M-8、Sprint 006 PR F で実装済）

Sprint 006 PR D 計画の Rev.1 で `fcntl.LOCK_SH` を `PolicyEngine._load` に追加する案が検討されましたが、proxy container の `/config/` ro mount に lock file を書けない問題があり PR F に defer。本実装で解決済。

### 実装サマリ

- **`bundle/addons/_policy_lock.py`** 新設
  - `lock_path_for(policy_path)`: 3 段 fallback (`POLICY_LOCK_DIR` env / 同階層 / tempdir)
  - `policy_lock_shared(policy_path)`: reader 用 LOCK_SH。**失敗時 warn + passthrough** (best-effort、ADR 0005 fail-closed と両立)
  - `policy_lock_exclusive(policy_path)`: writer 用 LOCK_EX。**失敗時 raise** (一貫性破壊を防ぐ fail-closed)
  - `os.open(..., O_NOFOLLOW, 0o600)` で symlink 攻撃 / world-readable を抑止
- **`bundle/addons/policy_edit.py::policy_lock`** を `from _policy_lock import policy_lock_exclusive as policy_lock` に置換
- **`bundle/addons/policy.py::PolicyEngine._load`** の runtime 読込のみ `policy_lock_shared` で wrap (base は writer 不在なので不要)
- **`bundle/docker-compose.yml`** で proxy / dashboard に `./locks:/locks` mount
- **`src/zoo/api.py::init()`** で `.zoo/locks/` dir を自動生成

### reader / writer 失敗時の挙動分離

| 役割 | 失敗時の挙動 | 根拠 |
|---|---|---|
| reader (`policy_lock_shared`) | `logger.warning` + passthrough | ADR 0005 fail-closed は「addon 内例外で flow を pass しない」原則。reader が lock 取れずに read を中止すると enforcer 全体が止まる方が危険。observable な warn で診断可能化 |
| writer (`policy_lock_exclusive`) | `OSError` raise | 一貫性破壊を防ぐ fail-closed。dashboard 側で 503 / flash として retry 可能化 |

### macOS Docker Desktop の cross-VM flock 制約

Docker Desktop on macOS は VirtioFS / gRPC FUSE 経由で host ↔ Linux VM 間のファイル共有を行います。**この経路では flock のセマンティクスが host kernel と VM kernel で協調しません** (Linux 限定の lock 機構)。

本 PR F は **container-mode (proxy + dashboard が同一 Docker VM 内)** での協調を保証します。`zoo proxy <agent>` 等で host-mode mitmproxy を併用するケースでは:
- host process と container process の lock は協調しない
- dashboard (container) と policy_edit (container) は OK
- host process が `./policy.runtime.toml` を直接編集する経路は無いので実害は通常無し

ホストモード CLI から policy file を直接編集する場合は **container を停止してから** 行うのが確実です。Linux host (CI runner 等) では問題ありません。

### lock dir 解決順 (`lock_path_for`)

1. `POLICY_LOCK_DIR` env (default `/locks`) が writable → `<dir>/<basename>.lock`
2. `<policy_path>` の同 dir が writable → `<policy_path>.lock` (host-mode 互換)
3. tempdir → `<tmp>/agent_zoo_<basename>.lock` (last resort)

各候補で `O_NOFOLLOW` + `0o600` を強制し、symlink preplant 攻撃を抑止。

### basename 衝突の既知制約 (Gemini self-review #1, deferred)

`lock_path_for` は basename で lock file 名を決定するため、異なるディレクトリに
同名 policy file (`/path/a/policy.runtime.toml` と `/path/b/policy.runtime.toml`)
があると同一 lock (`/locks/policy.runtime.toml.lock`) を共有し、不要な mutual
blocking が発生する。本ハーネスの設計上 proxy / dashboard が共有するのは唯一の
`policy.runtime.toml` 1 件のみで、複数 policy file を扱う運用は想定外のため
現実の影響無し。将来 multi-policy 対応 (例: per-agent policy) を入れる場合は
`hashlib.sha256(abspath).hexdigest()[:16]` 等で path hash 化する。

### reader best-effort (warn + passthrough) の rationale (Gemini self-review #3)

`policy_lock_shared` を fail-closed (raise) ではなく fail-open (warn + passthrough)
にしている設計判断:

- ADR 0005 fail-closed 原則は「mitmproxy addon 内で flow を pass しない」=
  「セキュリティ enforcement を skip しない」が本質。**reader が lock 取得
  に失敗して `_load` が exception を投げると `PolicyEngine` 自体が起動不能で
  enforcer 全体が止まる**。これは「addon 例外で流量がそのまま流れる」のと
  同等以上に危険 (起動失敗で proxy が落ちたら network isolation も無効化)
- writer (`policy_lock_exclusive`) は raise = ADR 0005 fail-closed と整合。
  「ユーザー操作 (whitelist accept) が無音失敗」を防ぎ UI で 503 retry できる
- reader 失敗時は `logger.warning` で観測可能化、運用で監視可能 (M-8 mitigation
  は best-effort、完全な fail-closed は別 PR で実装する場合 `policy_lock_strict`
  env で opt-in 可能化を検討)

### symlink hit 時の reader / writer 非対称 (Gemini self-review #4)

`O_NOFOLLOW` で symlink 検出した際の挙動:
- `policy_lock_shared`: warn + passthrough (上記 rationale と同じ best-effort)
- `policy_lock_exclusive`: OSError raise (fail-closed)

これは attacker が `/locks/*.lock` を symlink 化した場合、reader は読み取りを
継続するが、**writer は raise → dashboard 側で観測可能** という設計。symlink
preplant 攻撃の検出経路は確保している。完全な防御 (lock dir parent も含めた
ownership/perm 検証) は ROADMAP 行き。

---

## dashboard 外部依存ゼロ化 (Sprint 007 / ADR 0004)

### 達成内容

| 項目 | Before (Sprint 005 PR B 時点) | After (Sprint 007 PR I 完了) |
|---|---|---|
| 外部 CDN リソース | pico.css 2.x + htmx.org 2.0.4 を `cdn.jsdelivr.net` / `unpkg.com` から **SRI 無し** で読込 | **0 件** (`bundle/dashboard/static/app.{css,js}` のみ) |
| CSP `style-src` | `'self' https://cdn.jsdelivr.net 'unsafe-inline'` | **`'self'`** |
| CSP `script-src` | `'self' https://unpkg.com 'unsafe-inline'` | **`'self'`** |
| `form-action` | 未指定 (`default-src` の fallback 対象外) | **`'self'`** 明示追加 |
| `Permissions-Policy` | 未設定 | `camera=(), microphone=(), geolocation=(), payment=()` (defense-in-depth) |
| inline `<script>` / `<style>` / `style="..."` / `onclick=` | 全 partial に多数残存 | **完全削除** (BS4 ベースで test 防衛) |
| `<base>` 要素 / dns-prefetch / preconnect to CDN | 未確認 | BS4 test で 0 件 assert |

### 攻撃面消滅の効果

- **CDN 乗っ取り / unpkg リダイレクト改ざん** で任意 JS が dashboard コンテキストで実行される経路 → **無効化**
- **CSP `'unsafe-inline'`** に依存していた XSS escape の漏れ → **無効化** (template に inline asset がそもそも無い)
- **オフライン環境** でも dashboard が動作 (Playwright route で CDN block 確認、`tests/e2e/test_dashboard_offline.py`)
- **audit 対象縮小**: pico の数 KLOC + htmx の数 KLOC → 自前 ~552 行 (CSS 284 + JS 268)

### 残課題 (Sprint 008 follow-up)

- a11y polish: tab nav の `tabindex` 動的更新 (WAI-ARIA Authoring Practices)
- bulk-toggle-all で `dispatchEvent(new Event('change'))` 追加 (スクリーンリーダー通知)
- `data-suggest-target="#path-{{ host|replace('.', '-') }}"` の id 生成を slugify or hash 化
- `data-poll-interval="0"` の semantics を `data-poll-once` 等の明示属性に再設計
- `_triggerListenersByTarget` Map の removedNodes hook 対応 (memory leak 防止、polling element がほぼ静的なため実害小)
- dark theme 対応 (`@media (prefers-color-scheme: dark)`)

### 設計判断: なぜ self-host (代替 A) ではなく自前実装にしたか

ADR 0004 Alternatives 参照。要約:
- self-host (`bundle/dashboard/static/pico.min.css` 直置き) では依存ライブラリのバージョン追従コストが残り、Dependabot の docker ecosystem を 1 件追加する必要
- htmx の使用機能は `hx-get` / `hx-post` / `hx-target` / `hx-trigger` / `hx-include` / `hx-vals` / `hx-confirm` / `hx-ext` の 9 種のみ → vanilla JS で 165 行程度で実装可能
- pico の使用変数は `--pico-*` の 6 種のみ → 自前 design tokens で代替可能
- audit 対象が「pico 全機能 + htmx 全機能 + 自前 100 行」から「自前 552 行のみ」に縮小、長期 maintainability 向上
