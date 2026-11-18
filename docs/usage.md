# 使用方法

## 前提条件

- Windows（PC版。前面のウィンドウの監視に Windows の API を使う）。
- Python。
- スマホと連携する場合は、Android の端末と、PC と同じ Wi-Fi。Android版のビルドは [development.md](development.md#android版) を参照。

## インストール

```bash
pip install -r requirements.txt
```

起動用のショートカットを作る（下記「起動」）。

## 基本的な使い方

起動すると常駐し、`http://127.0.0.1:5000` でダッシュボードを開ける。
同時に、現在使用中のアプリを示す小型ウィンドウが最前面に表示される。

### 起動

**ショートカット `App Usage Tracker.lnk` から起動する。** 起動用のバッチファイルは
ない。ショートカットの中身は次のとおりである（環境固有の絶対パスを含むため、
リポジトリには入れていない。下表のとおり作成する）。

| 項目 | 値 |
|---|---|
| ターゲット | `pythonw.exe` |
| 引数 | `main.py` |
| 作業場所 | プロジェクトフォルダ |
| アイコン | `static/tracker.ico` |

`python.exe` ではなく `pythonw.exe` を使うことで、黒いコンソール画面を出さずに
常駐させている。

**サインイン時の自動起動**は、同じ内容のショートカットをスタートアップフォルダへ
置くことで実現している。場所は以下である。

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

自動起動をやめるときは、このフォルダのショートカットを削除する。

コマンドから直接起動することもできる。

```bash
pythonw main.py
```

### 停止

```bash
./stop_tracker.bat
```

**設定を変更したら再起動が必要である。** 起動時にしか読み込まないためである。

## ユースケース別の手順

### アプリの表示名を変える・統合する・分ける

#### 表示名を変える

`display` を書き換え、`source` を `"manual"` にする。
`manual` にしないと、次に記録されたときに自動で選び直される。

```json
"chrome": {
  "display": "グーグルクローム",
  "source": "manual",
  ...
}
```

#### 別々になっているものを統合する

規則では結び付かない組み合わせは、`aliases` に「記録された名前」→「まとめ先のキー」
を書く。まとめ先のキーは `apps` の中から選ぶ。

```json
"aliases": {
  "LineLauncher.exe": "line",
  "LineMediaPlayer.exe": "line"
}
```

#### 誤って統合されたものを分ける

`aliases` から該当の行を消す。自動で束ねられたものを分けたい場合は、
`aliases` でどちらか一方に別のキーを割り当てる。

```json
"aliases": { "Chrome": "chrome-mobile" }
```

#### 編集後

**アプリを再起動する。** 起動時に対応表を読み直し、過去の記録の
束ね方も合わせ直す。統合によって同じ日の記録がぶつかる場合は集計し直す。

**ファイルが壊れていても起動できる。** 読み込めない場合は警告をログへ残し、
規則による照合だけで動き続ける。

### Notion に日次登録する

1. [Notion のインテグレーション](https://www.notion.so/my-integrations)を作り、
   **内部インテグレーションシークレット**を発行する
2. 上の表のとおりデータベースを作る
3. そのデータベースを開き、右上「…」→「接続」から 1 のインテグレーションを追加する
4. 発行したトークンを **`data/notion_token.txt`** へ貼り付ける（改行のみでも可）
5. `config.json` を編集して再起動する

```json
"notion": {
  "enabled": true,
  "database_id": "データベースURLに含まれる32桁",
  "backfill_days": 7
}
```

**トークンは `config.json` に書かない。** 設定ファイルは画面共有などで映る可能性が
あるためで、同期用トークンと同じ扱いである。

待たずに試すには、次で未送信分をすぐ送れる。

```bash
curl -X POST http://127.0.0.1:5000/api/notion/send
```

登録される内容と注意点は [spec.md](spec.md#notion-への日次登録) を参照。

### スマホと連携する

1. `config.json` の `sync.enabled` を `true` にする
2. アプリを再起動する（`data/sync_token.txt` が生成される）
3. ファイアウォールに受信規則を追加する（**管理者権限のPowerShellで実行**）

```powershell
New-NetFirewallRule -DisplayName "App Usage Tracker (sync)" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
```

4. スマホのアプリに、PCのIPアドレス・ポート・`sync_token.txt` の値を入力する

通信の範囲と同期の仕組みは [spec.md](spec.md#スマホとの連携) を参照。

## よくあるエラーと対処

| 症状 | 原因と対処 |
|---|---|
| 設定を変えたのに反映されない | 再起動する（`stop_tracker.bat` で止めてから起動） |
| ヘッダーに、受信のない端末の警告が出る | スマホからの送信が止まっている。スマホのアプリと Wi-Fi、PC のファイアウォールの規則を確認する。OS が保持する記録は数日分なので、早めに対処する |
| 「最長アプリ」の選択肢が Notion で二重になる | アプリの表示名を変えたため。Notion 側で選択肢の名前を変える |
| 表示名が長いまま残る、ブラウザのサイトが判別されない | [spec.md の「制約条件」](spec.md#制約条件) を参照 |
| データベースを戻したい | アプリを終了してから、`data/backups/` の複製を `data/usage.db` へコピーし、`usage.db-wal` と `usage.db-shm` があれば削除する |
