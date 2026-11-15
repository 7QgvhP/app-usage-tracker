# 設計判断記録（ADR）

重要な設計判断を、1判断1ファイルで記録する。

## ファイル命名規則

`NNNN-短い題名.md`（`NNNN` は4桁の連番。題名は英小文字とハイフン）

## ステータス

| ステータス | 意味 |
|---|---|
| Proposed | 提案中 |
| Accepted | 採用済み |
| Deprecated | 廃止（後継なし） |
| Superseded | 別の ADR で置き換えられた（置き換えた ADR へのリンクを書く） |

コードや履歴から逆算した判断は、ステータスに「推定（コードから逆算）」と付記する。

## 運用

- 既存の ADR は書き換えない。判断を変えるときは新しい ADR を追加し、古い ADR のステータスを Superseded にする。

## 一覧

| 番号 | 題名 | ステータス | 日付 |
|---|---|---|---|
| [0001](0001-record-architecture-decisions.md) | ADR で設計判断を記録する | Accepted | 2026-11-15 |
| [0002](0002-pc-version-is-main.md) | リポジトリのバージョンは PC版の番号を使う | Accepted | 2026-09-21 |
| [0003](0003-local-only-storage.md) | 記録は手元の SQLite に置き、外部に送らない | Accepted（推定：コードから逆算） | 不明 |
| [0004](0004-lan-sync-with-idempotent-sessions.md) | スマホとの同期は LAN 内で、同じ区間を何度送っても二重にならない形にする | Accepted | 不明 |
| [0005](0005-tokens-outside-config.md) | トークンは `config.json` に書かず、`data/` の下のファイルに置く | Accepted | 不明 |
| [0006](0006-name-mapping-file.md) | 表示名の読み替えは、設定とは別の対応表で行う | Accepted | 不明 |

v2.30.0 より前は Git 管理の外で開発していたため、多くの判断の日付は記録がない（`CHANGELOG.md` の冒頭を参照）。
