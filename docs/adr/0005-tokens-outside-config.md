# 0005. トークンは `config.json` に書かず、`data/` の下のファイルに置く

- ステータス: Accepted
- 日付: 不明

## 背景（Context）

Notion のトークンと、スマホとの同期の共有トークンが必要になる。

## 決定内容（Decision）

Notion のトークンは `data/notion_token.txt`、同期のトークンは `data/sync_token.txt`（自動生成）に置き、`config.json` には書かない。`data/` は Git 管理外。

## 理由と検討した代替案（Consequences / Alternatives）

- 設定ファイルは、画面共有などで映る可能性があるため（旧 README より）。
- 検討した代替案: `config.json` に書く。上記の理由で採用しない。
