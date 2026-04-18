# Inbox（agent からの許可リクエスト）

> 詳細な設計判断は [ADR 0001 Policy Inbox](../dev/adr/0001-policy-inbox.md) を参照。

## これは何

agent が **許可されていないドメイン / パスにアクセスしようとした** とき、
agent 自身が「これを許可してください」というリクエストを残し、
**人間が dashboard で承認するまでブロック** する仕組み。

> **「読めても送れない」を保ちつつ、必要な許可だけを段階的に増やす** ための
> human-in-the-loop ワークフロー。

## どう動く

```
1. agent → 許可リスト外のドメインへ通信
2. proxy がブロック (HTTP 403)
3. agent が <workspace>/.zoo/inbox/<日時>-<id>.toml にリクエストを自動 submit
        ┌──────────────────────────────┐
        │ type   = "domain"            │
        │ value  = "registry.npmjs.org"│
        │ reason = "npm install で必要"│
        │ status = "pending"           │
        └──────────────────────────────┘
4. user → dashboard (http://localhost:8080) の **Inbox タブ** で確認
5. user → 「許可」ボタン
6. <workspace>/.zoo/policy.runtime.toml の domains.allow に自動追記
7. agent 再実行 → 通る
```

## ユーザーがやること

ほぼ **dashboard でクリックするだけ**。

### 1. dashboard を開く

```bash
zoo up --dashboard-only      # http://localhost:8080
```

agent 起動中なら既に開いている (`zoo run` 等が dashboard も up する)。

### 2. Inbox タブを開く

| 列 | 内容 |
|---|---|
| Type | `domain` / `path` / (将来) `tool_use_unblock` |
| Value | 許可したい対象（例: `registry.npmjs.org`、`/foo/*`） |
| Reason | agent が書いた理由 |
| Agent | claude / codex / gemini など |
| Created | 提出時刻 |

### 3. 操作

- **許可** ボタン → `policy.runtime.toml` に追記、status を `accepted` に
- **却下** ボタン → status を `rejected` に
- 複数選択して **一括許可 / 一括却下** も可

### 4. agent を再実行

許可された通信は次から通る。proxy が `policy.runtime.toml` を hot reload するため、再起動は不要なケースが多い (反映されない場合は `zoo reload`)。

## よくある質問

**Q. 許可しちゃダメな request はどう判断する?**
A. Reason 列の説明 + Value（ドメイン名）で判断。心配なら最初は **path 単位の絞り込み許可** を推奨（例: `registry.npmjs.org` 全域ではなく `/some-package/*` のみ）。

**Q. 同じ request が大量に溜まる**
A. 同一内容（type + value + domain）の **pending** は自動で dedup されるので 1 件しか溜まらない。表示が古い場合は dashboard を reload。

**Q. agent が submit しているか確認したい**
A. `<workspace>/.zoo/inbox/` ディレクトリを直接確認:
```bash
ls <workspace>/.zoo/inbox/
cat <workspace>/.zoo/inbox/2026-04-18T10-23-45-*.toml
```

**Q. 過去の accepted / rejected を消したい**
A. デフォルトで N 日経過後に自動削除されるが、即削除したい場合は `<workspace>/.zoo/inbox/` 内の該当ファイルを `rm` してよい（git 管理外）。

**Q. policy.runtime.toml と policy.toml の違いは?**
A. `policy.toml` が **あなたが手で編集する base policy**、`policy.runtime.toml` が **dashboard / Inbox accept で書き換えられる差分** (gitignore)。実行時にマージされる。詳細は [policy-reference.md](policy-reference.md) を参照。

## 仕組みをもう少し詳しく

- 1 リクエスト = 1 TOML ファイル（並行書込安全）
- ファイル名規約: `{ISO8601}-{shortid}-{contenthash}.toml`
- atomic write（`O_CREAT|O_EXCL`）で同時書込時の衝突を防止
- ライフサイクル: `pending → accepted | rejected | expired → cleanup`

設計の why は [ADR 0001](../dev/adr/0001-policy-inbox.md) で詳しく説明されています。
