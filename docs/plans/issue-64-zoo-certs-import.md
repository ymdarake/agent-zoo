# Plan: `zoo certs import` (issue #64)

| 項目 | 値 |
|---|---|
| issue | [#64](https://github.com/ymdarake/agent-zoo/issues/64) |
| branch | `feat/zoo-certs-import` (main から分岐済) |
| 作成日 | 2026-04-19 |
| 想定規模 | small / 半日 |

---

## 1. 背景

社内 proxy / 企業 root CA 環境で extra cert を `bundle/certs/extra/` (実環境では `<workspace>/.zoo/certs/extra/`) に配置する手順が手動 (`cp`)。Dockerfile.base の COPY コメントが唯一の手がかりで docs 化されておらず、UX 悪い。

## 2. スコープ

- **対象**: `zoo certs` を typer sub-app 化し、3 sub-command を追加
  - `zoo certs import <path-to-pem> [--name X] [--force]`
  - `zoo certs list`
  - `zoo certs remove <name>`
- **既存挙動の互換維持**: `zoo certs` (引数なし) は **mitmproxy CA generate** と同じ動作 (= 後方互換破壊しない)
- **対象外 (non-goal)**:
  - extra CA cert の自動更新 / OS keychain 同期 (将来 issue で別)
  - **agent (container 内) から `zoo certs import` を triggerable にしない** (現行 bind mount は `:ro` で塞がっており、本 PR でもこの境界を維持)

## 3. 設計

### 3.1 API (src/zoo/api.py)

```python
def certs() -> None:
    """既存: mitmproxy CA を生成 (変更なし)。"""
    runner.ensure_certs()


def certs_import(
    src_path: str | Path, *, name: str | None = None, force: bool = False
) -> Path:
    """ローカルの PEM cert を <workspace>/.zoo/certs/extra/ にコピー。

    Returns: コピー先 Path
    Raises:
        FileNotFoundError: src 不在
        ValueError: PEM 形式違反 / name に path separator / `.gitkeep` 上書き試行
        FileExistsError: dest が既存 + force=False
    """


def certs_list() -> list[str]:
    """extra/ 配下の cert ファイル名を sorted で返す (.gitkeep 除外)。"""


def certs_remove(name: str) -> bool:
    """extra/ から指定 cert を削除。
    存在 → True / 不在 → False / `.gitkeep` 試行 → ValueError
    name に path separator → ValueError
    """
```

### 3.2 CLI (src/zoo/cli.py)

`certs` を typer Typer sub-app に置き換える:

```python
certs_app = typer.Typer(
    help="mitmproxy CA / extra CA cert 管理",
    invoke_without_command=True,   # `zoo certs` (no sub) で generate
    no_args_is_help=False,
)
app.add_typer(certs_app, name="certs")


@certs_app.callback()
def _certs_default(ctx: typer.Context) -> None:
    """サブコマンド無しなら mitmproxy CA を生成 (後方互換)。"""
    if ctx.invoked_subcommand is None:
        api.certs()


@certs_app.command("import")
def certs_import_cmd(
    src: str = typer.Argument(..., help="ローカルの PEM cert path"),
    name: str | None = typer.Option(None, "--name", "-n", help="リネーム"),
    force: bool = typer.Option(False, "--force", "-f", help="上書き"),
) -> None:
    try:
        dest = api.certs_import(src, name=name, force=force)
    except (FileNotFoundError, ValueError, FileExistsError) as e:
        raise SystemExit(str(e))
    typer.echo(f"Imported: {dest}")
    typer.echo("Note: extra cert は次回 `zoo build --no-cache` で base image に反映されます")


@certs_app.command("list")
def certs_list_cmd() -> None:
    items = api.certs_list()
    if not items:
        typer.echo("(no extra certs)")
    for n in items:
        typer.echo(n)


@certs_app.command("remove")
def certs_remove_cmd(name: str = typer.Argument(...)) -> None:
    try:
        ok = api.certs_remove(name)
    except ValueError as e:
        raise SystemExit(str(e))
    typer.echo(f"Removed: {name}" if ok else f"Not found: {name}")
```

### 3.3 PEM 検証

軽量に `b"-----BEGIN CERTIFICATE-----"` を含むかチェック。複数 cert の bundle (chain) は **どこかに header がある** だけで pass (`if header not in content: raise`)。先頭が KEY / 2 番目が CERTIFICATE のような file も pass するが、chain の正当性 / KEY の混入は OpenSSL 側 (`update-ca-certificates`) に委ねる。OpenSSL 完全 parse は overkill / 依存追加 (cryptography) 必要なので skip。

DER (binary) 形式は header 文字列を含まないので自動 reject される。

### 3.4 src 検証

`src_path` に対し:
1. `Path(src).resolve(strict=True)` で symlink を target に resolve (target 不在なら `FileNotFoundError`)
2. `is_file()` チェック (dir なら `ValueError("src is not a file")`)
3. PEM 検証 (3.3) を resolve 後の中身に対して実行
4. `shutil.copy2(resolved, dest, follow_symlinks=True)` で実 file の copy

### 3.5 name 検証 (path traversal 防御)

**検査順序を明文化**:

```python
def _validate_cert_name(name: str) -> str:
    if not name or not name.strip():
        raise ValueError("name is empty")
    if name in (".", ".."):
        raise ValueError(f"reserved name: {name!r}")
    if any(c in name for c in ("/", "\\", "\x00")):
        raise ValueError(f"name contains path separator or NUL: {name!r}")
    if name == ".gitkeep":
        raise ValueError(".gitkeep is protected")
    if Path(name).parts != (name,):
        raise ValueError(f"name must be a single file name: {name!r}")
    # 拡張子 whitelist (CA cert として update-ca-certificates が認識する形式に限定)
    if Path(name).suffix.lower() not in (".pem", ".crt", ".cer"):
        raise ValueError(f"name must end with .pem / .crt / .cer: {name!r}")
    return name
```

### 3.6 dest 衝突 / dir 検証

```python
dest = extra_dir / name
if dest.exists():
    if dest.is_dir():
        raise ValueError(f"dest is a directory (not a regular file): {dest}")
    if not force:
        raise FileExistsError(f"already exists: {dest} (use --force to overwrite)")
```

### 3.7 CLI message (Note 強調)

`zoo certs import` 成功後に **目立つ警告**:

```python
typer.echo(f"Imported: {dest}")
typer.secho(
    "Note: extra cert を image に反映するには `zoo build --no-cache` が必要です。\n"
    "      (--no-cache 無しだと Docker layer cache hit で COPY 再評価されません)",
    fg=typer.colors.YELLOW,
)
```

### 3.8 export

- `src/zoo/__init__.py` に `certs_import / certs_list / certs_remove` を追加
- 既存 `certs` は維持

## 4. テスト戦略

`tests/test_zoo_certs_import.py` (新設、TDD で先に書いた + レビュー反映で追加):

| クラス | ケース | 件数 |
|---|---|---|
| TestCertsImport | copy / rename / 既存衝突 / force 上書き / src 不在 / 不正 PEM / path traversal (`.`, `..`, `/`, `\`, NUL) / `.gitkeep` 保護 / extra/ 自動作成 | 11 |
| TestCertsImport (追加: レビュー反映) | **空文字 name** / **`.` 単独** / **拡張子 whitelist** (.txt reject) / **dest が dir** / **src が dir** / **symlink src を resolve** | 6 |
| TestCertsList | 空 / `.gitkeep` のみ / 複数 cert sorted | 3 |
| TestCertsRemove | 存在削除 / 不在 / `.gitkeep` 保護 / path traversal | 4 |
| TestCertsCli (smoke) | `zoo certs --help` / `zoo certs` (no arg = generate) / `zoo certs list` (典型) | 3 |

**合計 27 件** (initial 18 + review 9)。全て tmp 環境で実行、`runner.workspace_root` の cache を clear。

CLI 層 smoke 3 件は `typer.testing.CliRunner` で callback fire のリグレッション保険。API 層メインは引き続き直接 test。

## 5. 受入基準 (issue #64)

- [x] api.py 実装 (certs_import / certs_list / certs_remove + _validate_cert_name)
- [x] cli.py 実装 (certs を Typer sub-app 化、後方互換維持)
- [x] PEM 検証 + path traversal 防御 + .gitkeep 保護
- [x] 単体テスト 18 件 PASS
- [x] `zoo certs --help` で sub-command が出る、`zoo certs` (no arg) で従来通り generate
- [ ] docs 更新 (CHANGELOG + 新規 docs/user/cli-reference.md or install-from-package.md 加筆)
- [ ] 既存 unit test (281 → 299 件) 全 PASS / 既存 e2e 全 PASS

## 6. 後方互換性

| 既存挙動 | 維持 |
|---|---|
| `zoo certs` (no arg) | ✅ `_certs_default` callback で `api.certs()` を呼ぶ |
| `api.certs()` シグネチャ | ✅ 変更なし |
| `zoo` import path | ✅ 既存 `zoo.certs` は残し、新規 `zoo.certs_import` 等を追加 |

## 7. ドキュメント方針

- **CHANGELOG**: `### Added` に 2 行 (CLI コマンドと Python API の両方、Sprint 003 の zoo CLI 追加 entry に sub-app 形式で並記)
- **README**: 触らない (詳細は docs/user/ に集約方針)
- **docs/user/install-from-package.md**: 「企業 proxy 配下で root CA を信頼させる場合」セクションを追記 (3-5 行 + コマンド例)
- **docs/dev/python-api.md**: API 一覧表に `certs_import / certs_list / certs_remove` 追記
- **新規 cli-reference.md**: 別 PR で対応 (本 PR 内では加筆のみ)

## 8. 開発フロー

1. ✅ Plan 作成 (本ファイル)
2. **Plan レビュー** (Claude subagent + Gemini 並行) ← **次**
3. レビュー反映
4. TDD: red (テストは既に書いた) → green (実装) → refactor
5. self-review (Claude subagent + Gemini) on code
6. docs 更新
7. commit-push + PR

## 9. リスク / 留意点

- typer の `--help` は **eager option で callback の前に exit** するため、`_certs_default` callback は help 表示時に fire **しない** (実機検証済)。`ctx.invoked_subcommand is None` チェックは「sub-command 無しの正常呼び出し」を判定するためのみ
- CA cert は **image build 時に COPY** される。import 後は **`zoo build --no-cache`** が必要 (`--no-cache` 無いと Docker layer cache hit で COPY が再評価されない)。CLI 出力で yellow 警告
- PEM 検証が緩い (header 存在のみ) → 不正 cert で build 時に fail することがある。許容 (小規模 CLI で過剰な依存を避ける)
- **macOS case-insensitive FS**: `Cert.pem` import 後に `cert.pem` を import すると `dest.exists()` は True を返すため `FileExistsError` で防御される (= OS の FS 判定に委ねる、明示テスト不要)
- **agent コンテナからの triggerability**: docker-compose.yml で `./certs:/certs:ro` (ro mount) なので agent が `extra/` に直接書く経路なし。本 PR でもこの境界を維持 (non-goal §2)
