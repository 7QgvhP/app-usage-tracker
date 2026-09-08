# TODO

未対応の課題と、コードからは読み取りにくい決定事項をまとめる。
解決済みの経緯は [README.md](README.md) に移してある。

---

## 未解決の課題

### 1. 冗長な表示名が残る

` - ` での切り捨てでは対処できない例がある。

| プロセス名 | 現在の表示名 |
|---|---|
| `mshta.exe` | Microsoft (R) HTML Application host |

`data/app_names.json` の `display` で個別に直せる。自動で短縮する規則を
増やすかどうかは未検討。

### 2. 名前情報を持たない実行ファイル

`CatchMe.exe` / `outhold_windows.exe` / `Super Battle Golf.exe` などは
`FileDescription` も `ProductName` も持たず、プロセス名のまま表示される。
`data/app_names.json` の `display` で個別に直すしかない。

### 3. ブラウザのサイト判定が限定的

`apps.browser_site_rules` に登録したパターンとウィンドウタイトルの照合に
依存しており、登録済みのサイト（YouTube / X）しか判別できない。
URLを取得する方式（拡張機能 / UI Automation）は検討済みだが未着手。
ManicTime も本体は拡張機能からURLを受け取る構成を採っている。

**YouTube Music が YouTube に吸収される**のもこの規則による副作用。

**Android**: 実装不可能。Android版 Chrome に拡張機能が無く、
ウィンドウタイトルに相当する取得手段も無い。

### 4. 棒グラフは端末間の重なりを除けない

`usage_log` には時刻が無いため、同じアプリを2台で同時に使った時間を
判別できない。合計値（`union_seconds`）だけが実時間で出る。

別々のアプリを2台で同時に使った時間はそれぞれ実際に使っているため、
足し上げが実時間を超えるのは正しい。

### 5. スマホから過去のデータを見られない

OSが保持する生イベントは数日程度で消えるため、スマホの利用状況画面は
それより前の日を出せない。遡って見るにはPC側へ閲覧用APIを足し、
アクセス制御を見直す必要がある。

---

## 設計上の決定

コードを読んだだけでは理由が分からないもの。

### 端末名 `pc` は予約語

取り込みには使えない。PC自身の記録を外部から汚染させないため。

### 再送しても二重にならない

スマホは `{パッケージ名}:{開始時刻のエポックミリ秒}` という決定的な
`external_id` を振る。同じ値の区間は無視されるため、何度送っても増えない。
`usage_log` は加算せず、影響を受けた `(端末, 日付)` の合計を区間から
再計算して置き換える。

### スマホでは「一時停止」の意味が変わる

OS側の記録は止められないため、表示を隠す動作になる。

### 取り込みを怠ると欠損する

OSのイベント保持は数日程度のため、最低でも1日1回は自前のデータベースへ
取り込む必要がある。受信が途絶えた端末はヘッダーに警告として出る。

---

## Android アプリ（`android/`）

### 構成

| 項目 | 内容 |
|---|---|
| ビルド | AGP 9.3.1 / Gradle 9.5.0 / compileSdk 37 / minSdk 29 |
| JDK | Android Studio 同梱の JBR 25 |
| 計測 | `UsageStatsManager.queryEvents()` |
| 保存 | SQLite（`SQLiteOpenHelper`。Room は使わない） |
| 画面 | Jetpack Compose |
| 同期 | WorkManager で15分ごと |

実機（Nothing A069 / Android 16）で動作確認済み。

### AGP 9 での書き方の変更

- `org.jetbrains.kotlin.android` プラグインは**不要**（AGP に内蔵された）
- `kotlinOptions` は廃止。Kotlin の設定は**トップレベルの `kotlin { compilerOptions { } }`**
- `compileSdk` は `compileSdk { version = release(37) }` のブロック形式

### 意図的に残している非推奨API

`AppOpsManager.unsafeCheckOpNoThrow` は非推奨だが、代替の4引数版は
API 36 以降のため minSdk 29 では使えない。

### 他アプリの情報が見えない問題

**Android 11 以降、他アプリの情報は既定で見えない。** 対処しないとアプリ名が
`com.twitter.android` のようなパッケージ名のままになる。マニフェストの
`<queries>` で `MAIN` + `LAUNCHER` を宣言して解決した
（`QUERY_ALL_PACKAGES` は用途に対して広すぎるため使わない）。

ホームアプリは `MAIN` + `HOME` で特定し、計測から除いている
（Windows版が `explorer.exe` を除いているのと同じ考え方）。

### 開発時の操作メモ

端末の設定（`shared_prefs/settings.xml`）は `adb shell run-as` で読み書きできる。
書き込み時はコマンド全体を二重引用符で囲み、内側を単引用符にすること
（引用符が崩れると Permission denied になる）。

定期同期の強制実行:

```
adb shell cmd jobscheduler run -f -n "androidx.work.systemjobscheduler" com.appusagetracker.mobile 1
```

### 表記を変えるときの注意

秒数の表記は Python / JavaScript / Kotlin の3つに実装がある。
[tests/duration_cases.py](tests/duration_cases.py) の表を直せば、
揃っていない実装がテストで落ちる。

---

## 機能を検討するときの前提

機能追加や仕様変更を検討する際は、**Android でも実装可能かを併せて判断する**。
中核は `UsageStatsManager`。`queryEvents()` が `ACTIVITY_RESUMED` /
`ACTIVITY_PAUSED` を時刻付きで返すため、合計時間と使用区間の両方を再現できる。
