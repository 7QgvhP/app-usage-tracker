# 使用方法

PC版のテスト（`python -m pytest tests -q`）は 2026-11-15 に実行して動作を確認した。
それ以外（起動、停止、ファイアウォールの規則の追加、Notion への送信、Android版のビルド）は、常駐・システム設定の変更・外部への書き込みを伴うため実行しておらず「未検証」としている。

## 前提条件

- Windows（PC版。前面のウィンドウの監視に Windows の API を使う）。
- Python。TODO(要確認): 必要な Python のバージョンは記録がない（2026-11-15 の確認は Python 3.12.10）。
- スマホと連携する場合は、Android の端末と、PC と同じ Wi-Fi。Android版のビルドは [development.md](development.md#android版) を参照。

## インストール

```bash
pip install -r requirements.txt
```

起動用のショートカットを作る（下記「起動」）。

## 基本的な使い方

起動すると常駐し、`http://127.0.0.1:5000` でダッシュボードを開けます。
同時に、現在使用中のアプリを示す小型ウィンドウが最前面に表示されます。

### 起動

**ショートカット `App Usage Tracker.lnk` から起動します。** 起動用のバッチファイルは
ありません。ショートカットの中身は次のとおりです（環境固有の絶対パスを含むため、
リポジトリには入れていません。下表のとおり作成してください）。

| 項目 | 値 |
|---|---|
| ターゲット | `pythonw.exe` |
| 引数 | `main.py` |
| 作業場所 | プロジェクトフォルダ |
| アイコン | `static/tracker.ico` |

`python.exe` ではなく `pythonw.exe` を使うことで、黒いコンソール画面を出さずに
常駐させています。

**サインイン時の自動起動**は、同じ内容のショートカットをスタートアップフォルダへ
置くことで実現しています。場所は以下です。

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

自動起動をやめるときは、このフォルダのショートカットを削除してください。

コマンドから直接起動することもできます。

```bash
pythonw main.py
```

### 停止

```bash
./stop_tracker.bat
```

**設定を変更したら再起動が必要です。** 起動時にしか読み込まないためです。

## ユースケース別の手順

### アプリの表示名を変える・統合する・分ける

#### 表示名を変える

`display` を書き換え、`source` を `"manual"` にします。
`manual` にしないと、次に記録されたときに自動で選び直されます。

```json
"chrome": {
  "display": "グーグルクローム",
  "source": "manual",
  ...
}
```

#### 別々になっているものを統合する

規則では結び付かない組み合わせは、`aliases` に「記録された名前」→「まとめ先のキー」
を書きます。まとめ先のキーは `apps` の中から選びます。

```json
"aliases": {
  "LineLauncher.exe": "line",
  "LineMediaPlayer.exe": "line"
}
```

#### 誤って統合されたものを分ける

`aliases` から該当の行を消します。自動で束ねられたものを分けたい場合は、
`aliases` でどちらか一方に別のキーを割り当てます。

```json
"aliases": { "Chrome": "chrome-mobile" }
```

#### 編集後

**アプリを再起動してください。** 起動時に対応表を読み直し、過去の記録の
束ね方も合わせ直します。統合によって同じ日の記録がぶつかる場合は集計し直します。

**ファイルが壊れていても起動できます。** 読み込めない場合は警告をログへ残し、
規則による照合だけで動き続けます。

### Notion に日次登録する（未検証）

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

**トークンは `config.json` に書きません。** 設定ファイルは画面共有などで映る可能性が
あるためで、同期用トークンと同じ扱いです。

待たずに試すには、次で未送信分をすぐ送れます。

```bash
curl -X POST http://127.0.0.1:5000/api/notion/send
```

登録される内容と注意点は [spec.md](spec.md#notion-への日次登録) を参照。

### スマホと連携する（未検証）

1. `config.json` の `sync.enabled` を `true` にする
2. アプリを再起動する（`data/sync_token.txt` が生成されます）
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
