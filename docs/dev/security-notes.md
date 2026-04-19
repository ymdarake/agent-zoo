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

## policy_lock の cross-container 協調（M-8 defer related）

Sprint 006 PR D 計画の Rev.1 で `fcntl.LOCK_SH` を `PolicyEngine._load` に追加する案が検討されましたが、以下の破綻点で **PR F に defer** されました:

1. proxy container は `./policy.runtime.toml:/config/policy.runtime.toml:ro` で ro mount
2. 同一 path に lock file (`/config/policy.runtime.toml.lock`) を書けない (EROFS)
3. 結果として `maybe_reload` が常時 fail-closed 経路へ流れ、reload 機能が silently 停止

### PR F で対応予定の設計

- `./locks:/locks:rw` bind mount を proxy / dashboard に追加
- `bundle/addons/_policy_lock.py` に `_policy_lock_path()` helper を実装
- 既存 `policy_edit.py::policy_lock` を新 helper 経由に移行（6 callsite）

詳細は `docs/plans/2026-04-18-consolidated-work-breakdown.md` の PR F 節。

### 当面の TOCTOU 分析

`atomic_write` は tmpfile + rename で実装されており POSIX 下では atomic。reader は古い内容か新しい内容のいずれかを確実に観察します（partial read 不可）。direct overwrite fallback 経路のみ race condition 余地がありますが、rename 失敗は Docker bind mount の特定環境でのみ稀に発生するため実害小。PR F マージまで現状の atomic rename + 単一プロセス pattern で許容。
