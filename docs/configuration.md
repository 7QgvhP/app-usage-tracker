# 設定リファレンス

環境変数とコマンドラインオプションはない（`main.py` は引数を取らない）。設定を変えたら再起動する（起動時にしか読み込まない）。

## 設定ファイル

`config.json` に書く。

「デフォルト値」は、項目を省いたときにコード（`app/config.py`）が使う値。リポジトリの `config.json` の値と異なるものは備考に書く。

| 名前 | 説明 | 型 | デフォルト値 | 必須 |
|---|---|---|---|---|
| `web.host` | ダッシュボードの待ち受けアドレス | 文字列 | `127.0.0.1` | いいえ |
| `web.port` | ダッシュボードのポート | 整数 | `5000` | いいえ |
| `tracker.poll_interval_seconds` | 前面のウィンドウを確認する間隔（秒） | 整数 | `5` | いいえ |
| `tracker.flush_interval_seconds` | 集計結果を DB へ書き出す間隔（秒） | 整数 | `60` | いいえ |
| `tracker.notify_before_minutes` | 制限時間の何分前に予告通知を出すか | 整数 | `5` | いいえ |
| `tracker.idle_detection.enabled` | 無操作中は計測しない | 真偽値 | `false` | いいえ |
| `tracker.idle_detection.threshold_seconds` | 無操作とみなす秒数 | 整数 | `300` | いいえ |
| `timeline.min_session_seconds` | これより短い使用区間は表示しない（一瞬の切り替えを除くため） | 整数 | `30` | いいえ |
| `timeline.merge_gap_seconds` | 同じアプリの区間がこの秒数以内で途切れたら1つにまとめる | 整数 | `60` | いいえ |
| `devices.labels` | 記録に使う端末名を、画面の表記へ変換する対応表（未登録は記録された名前のまま） | オブジェクト | `{"pc": "PC"}` | いいえ |
| `sync.enabled` | スマホなど外部の端末からの受信を許可する（有効にすると LAN にポートを公開する） | 真偽値 | `false`（リポジトリの `config.json` では `true`） | いいえ |
| `sync.bind_host` | 受信を有効にしたときの待ち受けアドレス（`web.host` を上書き） | 文字列 | `0.0.0.0` | いいえ |
| `sync.max_sessions_per_request` | 1回のリクエストで受け取れる使用区間の上限 | 整数 | `5000` | いいえ |
| `sync.stale_hours` | この時間だけ端末から受信がなければ警告する | 数値 | `24` | いいえ |
| `mini_window.enabled` | 現在のアプリと本日の使用時間を示す小型ウィンドウを表示する | 真偽値 | `true` | いいえ |
| `mini_window.always_on_top` | 小型ウィンドウを最前面に表示する | 真偽値 | `true` | いいえ |
| `mini_window.opacity` | 小型ウィンドウの不透明度（0.3〜1.0） | 数値 | `0.92` | いいえ |
| `mini_window.font_size` | 小型ウィンドウの文字サイズ | 整数 | `22` | いいえ |
| `notion.enabled` | 1日1回、前日分を Notion のデータベースへ登録する | 真偽値 | `false` | いいえ |
| `notion.database_id` | 登録先のデータベース ID（Notion の URL に含まれる32桁） | 文字列 | `""` | Notion を使うなら、はい |
| `notion.backfill_days` | 起動時に遡って補う日数 | 整数 | `7` | いいえ |
| `backup.enabled` | 1日1回、`data/backups/` へデータベースの複製を作る | 真偽値 | `true` | いいえ |
| `backup.keep` | 残す世代数（超えた分は古いものから削除する） | 整数 | `7` | いいえ |
| `logging.level` | ログの水準 | 文字列 | `INFO` | いいえ |
| `logging.max_bytes` | ログファイル1つあたりの最大サイズ（バイト） | 整数 | `1048576` | いいえ |
| `logging.backup_count` | ローテーションで残すログの世代数 | 整数 | `3` | いいえ |

### apps

- **`use_executable_name`** … 実行ファイルの情報から読みやすい名前を得る
  （`r5apex_dx12.exe` → `Apex Legends`）。既定で有効
- **`ignore_processes`** … 計測しないプロセス名
- **`browser_site_rules`** … Chrome のウィンドウタイトルからサイトを判定する規則

`config.json` は「**名前をどう決めるか**」だけを持ちます。決まった名前を任意の表記へ
読み替えるのは `data/app_names.json`（前節の対応表）の役目です。

- **`browser_processes`** … サイトを判定するブラウザのプロセス名（既定 `chrome.exe`）

アプリ名が決まる順序は [spec.md](spec.md#計測と常駐) を参照。

## そのほかのファイル（`data/` の下。Git 管理外）

| 名前 | 説明 |
|---|---|
| `data/app_names.json` | アプリ名の対応表（[spec.md](spec.md#アプリ名の対応表dataapp_namesjson)） |
| `data/notion_token.txt` | Notion のインテグレーションのトークン（`config.json` には書かない） |
| `data/sync_token.txt` | スマホとの同期に使う共有トークン（同期を有効にして起動すると作られる。削除して再起動すると作り直す） |
