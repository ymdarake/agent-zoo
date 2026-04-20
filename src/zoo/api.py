"""Public Python API for Agent Zoo.

Import as:
    from zoo import run, task, up, down, ...

All functions are plain Python — no typer/rich dependency — so you can use them
from notebooks, other scripts, or custom tooling.

Interactive commands (``run``, ``task``, ``host_start``, ``test_unit``)
attach the current process stdio and return a subprocess-style exit code.
Non-interactive commands raise on failure or return structured data.
"""
from __future__ import annotations

import enum
import os
import shutil
import subprocess
from pathlib import Path

from . import runner

_BUNDLED_FILES = [
    "docker-compose.yml",
    "docker-compose.strict.yml",
    # policy.toml は issue #66 で bundle/policy/*.toml に分離。
    # init() が policy 引数に応じて 1 ファイル選択コピーする。
]
_BUNDLED_DIRS = [
    "container",
    "addons",
    "dashboard",
    "templates",
    "host",
    "dns",
]


class PolicyProfile(str, enum.Enum):
    """`zoo init --policy <profile>` で選択可能な初期ポリシープロファイル。

    str subclass 化しているのは以下 2 点のため:
    - typer が Enum を native に choice として扱う（`--help` 自動生成 + invalid value exit 2）
    - f-string 等で `profile.value` 経由せず直接 path 構築に使える
    """

    minimal = "minimal"
    claude = "claude"
    codex = "codex"
    gemini = "gemini"
    all = "all"


def _coerce_policy_profile(value: PolicyProfile | str) -> PolicyProfile:
    """str / PolicyProfile を PolicyProfile に正規化。未知名は候補を含めた ValueError.

    Note: `from None` で Enum 内部の ValueError を chain 表示しない
    (user 向けエラーを dry に保つ; Claude self-review #2 指摘)。
    """
    if isinstance(value, PolicyProfile):
        return value
    try:
        return PolicyProfile(value)
    except ValueError:
        choices = ", ".join(p.value for p in PolicyProfile)
        raise ValueError(
            f"unknown policy profile: {value!r} (choose from: {choices})"
        ) from None


def _asset_source() -> Path:
    """Locate bundled assets.

    - Installed: `zoo/_assets/.zoo/` (= 配布物の `.zoo/` 構造)
    - Source repo (開発時): `bundle/` (source repo root から検索)
    """
    try:
        import importlib.resources as resources

        pkg_assets = resources.files("zoo").joinpath("_assets").joinpath(".zoo")
        if pkg_assets.is_dir():
            return Path(str(pkg_assets))
    except (ModuleNotFoundError, AttributeError, OSError):
        pass
    # Source repo fallback: walk up from this file to find bundle/
    here = Path(__file__).resolve()
    for candidate in here.parents:
        bundle = candidate / "bundle"
        if bundle.is_dir() and (bundle / "docker-compose.yml").exists():
            return bundle
    raise SystemExit(
        "Bundled assets not found. Either install the package "
        "or run from agent-zoo source repo (which has a `bundle/` directory)."
    )


def _init_assets_dir() -> Path:
    """Init 専用 assets (gitignore テンプレ等) のディレクトリ。

    `src/zoo/_init_assets/` に置かれた package data を返す。
    """
    try:
        import importlib.resources as resources

        pkg = resources.files("zoo").joinpath("_init_assets")
        if pkg.is_dir():
            return Path(str(pkg))
    except (ModuleNotFoundError, AttributeError, OSError):
        pass
    # Fallback: source repo の src/zoo/_init_assets/
    return Path(__file__).resolve().parent / "_init_assets"


def init(
    target_dir: str | Path = ".",
    *,
    force: bool = False,
    policy: PolicyProfile | str = PolicyProfile.minimal,
) -> Path:
    """Bootstrap a ready-to-use agent-zoo workspace at ``target_dir``.

    全 zoo 管理ファイルを ``target/.zoo/`` 配下に集約。
    - ``target/.zoo/`` 配下に bundled files / dirs をコピー
    - ``target/.zoo/policy.toml`` は ``policy`` 引数で選択された profile を書き出す
      (default = minimal = secure by default)
    - ``target/.gitignore`` (workspace 用、`.zoo/` 1 行) を配置（既存 skip）
    - ``target/.zoo/.gitignore`` (内部 runtime artifact 除外) を配置
    - runtime dirs (``data/``, ``certs/``, ``inbox/``) と
      ``policy.runtime.toml`` を作成

    既存ファイルは ``force=True`` 指定がない限り保持される。

    Args:
        target_dir: workspace root (デフォルト current dir)
        force: 既存 ``.zoo/`` 配下のファイル/ディレクトリを上書き
        policy: 初期ポリシープロファイル (minimal/claude/codex/gemini/all)。
            PolicyProfile Enum または同等の str を受け付ける。

    Returns: the resolved target path (= workspace root).

    Raises:
        ValueError: ``policy`` が未知の profile 名の場合
    """
    # 引数検証（ファイル生成前に実行）
    profile = _coerce_policy_profile(policy)

    target = Path(target_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    source = _asset_source()
    zoo_target = target / ".zoo"
    zoo_target.mkdir(parents=True, exist_ok=True)

    for name in _BUNDLED_FILES:
        src = source / name
        if not src.exists():
            continue
        dst = zoo_target / name
        if dst.exists() and not force:
            continue
        shutil.copy2(src, dst)

    for name in _BUNDLED_DIRS:
        src = source / name
        if not src.exists():
            continue
        dst = zoo_target / name
        if dst.exists():
            if not force:
                continue
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    # policy.toml: 選択された profile を <workspace>/.zoo/policy.toml に書き出す。
    # runtime consumer (docker-compose bind mount / POLICY_PATH env / PolicyEngine)
    # は単一ファイル名 policy.toml を前提にしているため、出力名は固定。
    _write_policy_profile(
        source=source, zoo_target=zoo_target, profile=profile, force=force
    )

    ws_gi_src = _init_assets_dir() / "workspace.gitignore"
    ws_gi_dst = target / ".gitignore"
    if ws_gi_src.exists() and not ws_gi_dst.exists():
        shutil.copy2(ws_gi_src, ws_gi_dst)

    # Runtime dirs/files（.zoo/ 配下）
    # Sprint 006 PR F: locks/ は cross-container policy lock 用 (M-8)。proxy /
    # dashboard 両方から bind mount される。
    # certs/extra: Dockerfile.base が `COPY certs/extra/ ...` で取り込むため
    # 空でも dir 自体が必須 (D-1 ユーザー追加 CA、`.gitkeep` 配置で空 dir 維持)
    for d in ("data", "certs", "certs/extra", "inbox", "locks"):
        (zoo_target / d).mkdir(parents=True, exist_ok=True)
    # certs/extra/.gitkeep: docker build が空 dir を skip しないよう placeholder
    extra_gitkeep = zoo_target / "certs" / "extra" / ".gitkeep"
    if not extra_gitkeep.exists():
        extra_gitkeep.touch()
    (zoo_target / "policy.runtime.toml").touch(exist_ok=True)

    return target


def _write_policy_profile(
    *, source: Path, zoo_target: Path, profile: PolicyProfile, force: bool
) -> bool:
    """選択 profile を `<zoo_target>/policy.toml` に書き出す（先頭にメタデータコメント付与）.

    Returns:
        True — 新規書き込みまたは force で上書きした (= 生成後の profile が反映)
        False — 既存 policy.toml を preserve した (force=False で生成 skip)

    Raises:
        FileNotFoundError: bundle/policy/{profile}.toml が source 側に無い場合。
            production では wheel 破損 / 未インストール等の bug を早期に露出させる
            (Claude self-review #2 指摘: silent skip は原因不明エラーの温床)。

    既存ファイルは force=False なら維持（ユーザー編集を尊重）。
    """
    src_toml = source / "policy" / f"{profile.value}.toml"
    if not src_toml.is_file():
        raise FileNotFoundError(
            f"policy profile source not found: {src_toml}. "
            "reinstall the package or run from agent-zoo source repo."
        )
    dest = zoo_target / "policy.toml"
    if dest.exists() and not force:
        return False
    header = (
        f"# Generated by `zoo init --policy {profile.value}` — edit freely.\n"
        f"# Re-run `zoo init --policy <minimal|claude|codex|gemini|all> --force` to switch.\n"
    )
    dest.write_text(header + src_toml.read_text())
    return True


def run(
    *,
    agent: str = "claude",
    workspace: str | Path | None = None,
    dangerous: bool = False,
) -> int:
    """Launch an interactive agent session.

    Returns the agent process exit code.
    """
    cfg = runner.resolve_agent(agent)
    runner.ensure_agent_images_built([cfg.name])
    runner.compose_up([cfg.name, "dashboard"], workspace=_as_str(workspace))
    cmd = cfg.run_dangerous_cmd if dangerous else cfg.run_cmd
    return runner.run_interactive(cmd)


def task(
    *,
    prompt: str,
    agent: str = "claude",
    workspace: str | Path | None = None,
) -> int:
    """Run a one-shot autonomous task. Auth via the agent's required env var.

    Returns the agent process exit code.
    """
    cfg = runner.resolve_agent(agent)
    runner.require_env(
        cfg.required_env,
        hint=f"Set {cfg.required_env} before calling task().",
    )
    runner.ensure_agent_images_built([cfg.name])
    runner.compose_up([cfg.name, "dashboard"], workspace=_as_str(workspace))
    cmd = [arg.replace("{prompt}", prompt) for arg in cfg.task_cmd_template]
    return runner.run_interactive(cmd)


def bash(
    *,
    agent: str = "claude",
    workspace: str | Path | None = None,
) -> int:
    """B-4: Open an interactive bash shell inside the agent container.

    Useful for manual inspection / ad-hoc debugging within the harness.
    """
    cfg = runner.resolve_agent(agent)
    runner.ensure_agent_images_built([cfg.name])
    runner.compose_up([cfg.name, "dashboard"], workspace=_as_str(workspace))
    return runner.run_interactive(
        ["docker", "compose", "exec", cfg.name, "bash"],
    )


def up(
    *,
    agent: str = "claude",
    workspace: str | Path | None = None,
    dashboard_only: bool = False,
    strict: bool = False,
) -> None:
    """Start containers without attaching (no exec)."""
    if dashboard_only:
        services = ["proxy", "dashboard"]
    else:
        cfg = runner.resolve_agent(agent)
        services = [cfg.name, "dashboard"]
    runner.ensure_agent_images_built(services)
    runner.compose_up(services, workspace=_as_str(workspace), strict=strict)


def down() -> None:
    """Stop containers (includes strict profile if present)."""
    env = runner.compose_env()
    strict_cmd = [
        "docker", "compose", "--profile", "strict",
        "-f", "docker-compose.yml", "-f", "docker-compose.strict.yml",
        "down",
    ]
    result = subprocess.run(strict_cmd, env=env, cwd=runner.zoo_dir())
    if result.returncode != 0:
        runner.run(["docker", "compose", "down"], env=env, check=False)


def reload_policy() -> None:
    """Reload policy.toml by restarting proxy + dashboard (clears addon cache)."""
    cache = runner.zoo_dir() / "addons" / "__pycache__"
    if cache.exists():
        shutil.rmtree(cache)
    runner.run(
        ["docker", "compose", "restart", "proxy", "dashboard"],
        env=runner.compose_env(),
    )


def build(*, agent: str = "claude", no_cache: bool = False) -> None:
    """Build docker images for the given agent + dashboard.

    まず共通 base（B-1: `agent-zoo-base:latest`）をビルドし、次に compose build。

    Args:
        agent: agent name (claude / codex / gemini)
        no_cache: ``True`` で ``docker build --no-cache`` + ``docker compose build --no-cache``。
            Dockerfile 変更 (例: Dockerfile.base の CA env 追加) を package upgrade 後に
            確実に反映したい時に使う。
    """
    cfg = runner.resolve_agent(agent)
    runner.ensure_certs()
    runner.build_base(no_cache=no_cache)
    compose_cmd = ["docker", "compose", "build"]
    if no_cache:
        compose_cmd.append("--no-cache")
    compose_cmd.extend([cfg.name, "dashboard"])
    runner.run(compose_cmd, env=runner.compose_env())


def certs() -> None:
    """Generate the mitmproxy CA certificate if missing."""
    runner.ensure_certs()


# --- certs import / list / remove (issue #64) -------------------------------

_CERT_NAME_PROTECTED = (".gitkeep",)  # 完全一致のみ (`.gitkeep.pem` 等は拡張子 whitelist で別途遮断)
_CERT_EXTENSIONS = (".pem", ".crt", ".cer")
_PEM_HEADER = b"-----BEGIN CERTIFICATE-----"


def _check_cert_name_path_safety(name: str) -> None:
    """`extra/` 配下を指す file 名の path-safety check (DRY: import / remove で共有)。"""
    if not name or not name.strip():
        raise ValueError("name is empty")
    if name in (".", ".."):
        raise ValueError(f"reserved name: {name!r}")
    if any(c in name for c in ("/", "\\", "\x00")):
        raise ValueError(f"name contains path separator or NUL: {name!r}")
    if name in _CERT_NAME_PROTECTED:
        raise ValueError(f"{name} is protected")


def _validate_cert_name(name: str) -> str:
    """`extra/` 配下に置く file 名の strict 検証 (path-safety + 単一 file 名 + 拡張子 whitelist)。"""
    _check_cert_name_path_safety(name)
    if Path(name).parts != (name,):
        raise ValueError(f"name must be a single file name: {name!r}")
    if Path(name).suffix.lower() not in _CERT_EXTENSIONS:
        raise ValueError(
            f"name must end with .pem / .crt / .cer: {name!r}"
        )
    return name


def _extra_certs_dir() -> Path:
    """`<workspace>/.zoo/certs/extra/` を返し、無ければ runtime 生成。

    Raises:
        ValueError: extra/ が存在するが dir で無い (file / broken symlink) 場合
    """
    extra = runner.zoo_dir() / "certs" / "extra"
    if extra.exists() and not extra.is_dir():
        raise ValueError(
            f"{extra} exists but is not a directory; "
            "remove it manually or run `zoo init --force`"
        )
    extra.mkdir(parents=True, exist_ok=True)
    return extra


def certs_import(
    src_path: str | Path,
    *,
    name: str | None = None,
    force: bool = False,
) -> Path:
    """ローカルの PEM cert を `<workspace>/.zoo/certs/extra/` にコピー。

    Args:
        src_path: コピー元 PEM 形式 cert (symlink は target に resolve)
        name: コピー先 file 名 (省略時は src の basename)
        force: 既存 file 上書き許可

    Returns: コピー先 Path

    Raises:
        FileNotFoundError: src 不在
        ValueError: src が dir / 不正 PEM / name に path separator 等 / dest が dir / `.gitkeep` 試行
        FileExistsError: dest が既存 + force=False
    """
    src = Path(src_path)
    try:
        resolved = src.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"src not found: {src_path}")
    except (RuntimeError, OSError) as e:
        # symlink loop (Python 3.10+ で RuntimeError) や ELOOP / 深さ過剰
        raise ValueError(f"failed to resolve src: {src_path}: {e}")
    if not resolved.is_file():
        raise ValueError(f"src is not a file: {resolved}")
    if _PEM_HEADER not in resolved.read_bytes():
        raise ValueError(
            f"src does not look like a PEM CERTIFICATE (header missing): {resolved}"
        )

    target_name = _validate_cert_name(name if name is not None else src.name)
    extra = _extra_certs_dir()
    dest = extra / target_name

    if dest.exists():
        if dest.is_dir():
            raise ValueError(f"dest is a directory (not a regular file): {dest}")
        # 同一 inode (= 既に extra/ にある cert を自分自身で再 import) は no-op
        try:
            if dest.resolve() == resolved:
                return dest
        except OSError:
            pass  # resolve 失敗時は通常の force / FileExistsError 経路へ
        if not force:
            raise FileExistsError(
                f"already exists: {dest} (use --force to overwrite)"
            )
        # force=True で既存が read-only (chmod 444) の場合、shutil.copy2 は PermissionError
        # で失敗するため、事前に unlink して clean state にする
        try:
            dest.unlink()
        except OSError as e:
            raise OSError(f"failed to remove existing {dest}: {e}")

    # CA cert は public 情報のため shutil.copy2 が source mode を継承する挙動を許容。
    # follow_symlinks=True で symlink target の通常 file をコピー (= dest は symlink にならない)。
    shutil.copy2(resolved, dest, follow_symlinks=True)
    return dest


def certs_list() -> list[str]:
    """`extra/` 配下の cert ファイル名を sorted で返す (`.gitkeep` 除外)。"""
    extra = _extra_certs_dir()
    return sorted(
        p.name for p in extra.iterdir()
        if p.is_file() and p.name not in _CERT_NAME_PROTECTED
    )


def certs_remove(name: str) -> bool:
    """`extra/` から指定 cert を削除。

    Returns: 存在し削除成功 → True / 不在 → False
    Raises: ValueError (`.gitkeep` 試行 / path traversal)
    """
    _check_cert_name_path_safety(name)
    extra = _extra_certs_dir()
    target = extra / name
    if not target.is_file():
        return False
    target.unlink()
    return True


def host_start() -> int:
    """Start host-mode mitmproxy via host/setup.sh."""
    return runner.run_interactive(["./host/setup.sh"])


def proxy(*, agent: str, agent_args: list[str] | None = None) -> int:
    """D-3: ホスト CLI に zoo proxy 環境を注入して exec する。

    mitmproxy が未起動なら host/setup.sh で起動。env に
    HTTPS_PROXY / HTTP_PROXY / NODE_EXTRA_CA_CERTS / SSL_CERT_FILE / GIT_SSL_CAINFO
    を注入してサブプロセスを実行する。
    """
    pid_file = runner.zoo_dir() / "data" / ".mitmproxy.pid"
    if not pid_file.exists():
        runner.run_interactive(["./host/setup.sh"])

    cert = runner.cert_path()
    env = os.environ.copy()
    env.update({
        "HTTPS_PROXY": "http://127.0.0.1:8080",
        "HTTP_PROXY": "http://127.0.0.1:8080",
        "NODE_EXTRA_CA_CERTS": str(cert),
        "SSL_CERT_FILE": str(cert),
        "GIT_SSL_CAINFO": str(cert),
    })
    cmd = [agent, *(agent_args or [])]
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        return 130


def host_stop() -> int:
    """Stop host-mode mitmproxy via host/stop.sh."""
    return runner.run_interactive(["./host/stop.sh"])


def logs_clear() -> bool:
    """Delete harness.db (and WAL/SHM). Returns True if anything was removed."""
    data = runner.zoo_dir() / "data"
    db = data / "harness.db"
    if not db.exists():
        return False
    for name in ("harness.db", "harness.db-wal", "harness.db-shm"):
        (data / name).unlink(missing_ok=True)
    return True


def logs_analyze() -> int:
    """Pipe block-log summary + policy.toml into ``claude -p`` for analysis."""
    query = (
        "SELECT host, COUNT(*) as n, GROUP_CONCAT(DISTINCT status) as statuses "
        "FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED','PAYLOAD_BLOCKED') "
        "GROUP BY host ORDER BY n DESC"
    )
    policy = (runner.zoo_dir() / "policy.toml").read_text()
    context = f"=== ブロックログ ===\n\n=== 現在のpolicy.toml ===\n{policy}"
    return _pipe_to_claude(
        query,
        "ブロックログとpolicy.tomlを比較して改善案をTOML形式で提案して。"
        "許可すべきドメインとその理由、危険なドメインとその理由を分けて。",
        extra_context=context,
    )


def logs_summarize() -> int:
    """Pipe recent tool_use log into ``claude -p`` for policy suggestion."""
    query = (
        "SELECT tool_name, input, input_size, ts "
        "FROM tool_uses ORDER BY ts DESC LIMIT 100"
    )
    return _pipe_to_claude(
        query,
        "このtool_use履歴からホストモード用settings.jsonの最小権限設定を提案して",
    )


def logs_alerts() -> int:
    """Pipe recent alerts into ``claude -p`` for review."""
    query = "SELECT * FROM alerts ORDER BY ts DESC LIMIT 50"
    return _pipe_to_claude(query, "セキュリティ上の懸念があるパターンを報告して")


def test_unit() -> int:
    """Run the project's pytest suite."""
    return runner.run_interactive(
        ["uv", "run", "python", "-m", "pytest", "tests/", "-v"],
    )


# --- internal helpers --------------------------------------------------------

def _as_str(value: str | Path | None) -> str | None:
    return str(value) if value is not None else None


def _pipe_to_claude(sqlite_query: str, prompt: str, *, extra_context: str = "") -> int:
    """Run ``sqlite3 ... | claude -p PROMPT``. Returns the claude exit code."""
    db_path = runner.zoo_dir() / "data" / "harness.db"
    if not db_path.exists():
        raise FileNotFoundError(
            "data/harness.db が見つかりません。先にエージェントを実行してください。"
        )
    sqlite = subprocess.Popen(
        ["sqlite3", str(db_path), "-json", sqlite_query],
        stdout=subprocess.PIPE,
    )
    try:
        if extra_context:
            data = sqlite.stdout.read()  # type: ignore[union-attr]
            sqlite.wait()
            input_bytes = (extra_context + "\n" + data.decode()).encode()
            claude = subprocess.Popen(["claude", "-p", prompt], stdin=subprocess.PIPE)
            claude.stdin.write(input_bytes)  # type: ignore[union-attr]
            claude.stdin.close()  # type: ignore[union-attr]
            return claude.wait()
        claude = subprocess.Popen(["claude", "-p", prompt], stdin=sqlite.stdout)
        sqlite.stdout.close()  # type: ignore[union-attr]
        return claude.wait()
    finally:
        sqlite.wait()
