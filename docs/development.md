# 開発者向けガイド

## 開発環境の構築

```bash
pip install -r requirements.txt      # 実行に必要なもの
pip install -r requirements-dev.txt  # テストに必要なもの
```

## テスト

```bash
python -m pytest tests -q            # PC版のテスト
```

Android版は `android/` にある。

```bash
cd android && ./gradlew assembleDebug testDebugUnitTest lint
```

## lint / フォーマット

PC版: なし。Android版: 上記の `lint`（Android Lint）。

## Android版

| 項目 | 内容 |
|---|---|
| ビルド | AGP 9.3.1 / Gradle 9.5.0 / compileSdk 37 / minSdk 29 |
| JDK | Android Studio 同梱の JBR 25 |
| 計測 | `UsageStatsManager.queryEvents()` |
| 保存 | SQLite（`SQLiteOpenHelper`。Room は使わない） |
| 画面 | Jetpack Compose |
| 同期 | WorkManager で15分ごと |

実機（Nothing A069 / Android 16）で動作を確認している。

**AGP 9 では書き方が変わっている。**

- `org.jetbrains.kotlin.android` プラグインは不要である（AGP に内蔵された）
- `kotlinOptions` は廃止された。Kotlin の設定はトップレベルの `kotlin { compilerOptions { } }` に書く
- `compileSdk` は `compileSdk { version = release(37) }` のブロック形式である

**`AppOpsManager.unsafeCheckOpNoThrow` は意図的に残している。** 非推奨だが、
代替の4引数版は API 36 以降のため minSdk 29 では使えない。

**Android 11 以降は、他アプリの情報が既定で見えない。** 対処しないとアプリ名が
`com.twitter.android` のようなパッケージ名のままになるため、マニフェストの
`<queries>` で `MAIN` + `LAUNCHER` を宣言している（`QUERY_ALL_PACKAGES` は
用途に対して広すぎるため使わない）。ホームアプリは `MAIN` + `HOME` で特定して
計測から除く（PC版が `explorer.exe` を除くのと同じ考え方である）。

端末の設定（`shared_prefs/settings.xml`）は `adb shell run-as` で読み書きできる。
書き込むときはコマンド全体を二重引用符で囲み、内側を単引用符にする
（引用符が崩れると Permission denied になる）。定期同期はすぐに実行させられる。

```bash
adb shell cmd jobscheduler run -f -n "androidx.work.systemjobscheduler" com.appusagetracker.mobile 1
```

機能を追加・変更するときは、**Android でも実装できるかを併せて判断する。**
中核の `UsageStatsManager.queryEvents()` は `ACTIVITY_RESUMED` / `ACTIVITY_PAUSED` を
時刻付きで返すため、合計時間と使用区間の両方を再現できる。

## 配色

**色は [static/style.css](../static/style.css) の `:root` だけに書く。**
JavaScript 側にも色を書くと二重管理になり、必ずずれる（実際に
グラフの6色目がCSSに無い、という状態になっていた）。

canvas や SVG のように CSS 変数を直接書けない場所へは、`common.js` の
`theme` を通して渡す。

```js
theme.color('--bar-1')      // '#8f8e8a'
theme.scale('--bar-', 6)    // 6色の配列
```

## 名前の扱い

**同一性は照合キー（`app_key`）で決め、表示名は見せる直前に決める。**

| 種類 | 例 | どこで使うか |
|---|---|---|
| 記録名 | `chrome.exe`（PC） / `Chrome`（スマホ） | データベースに残る生の名前 |
| 照合キー | `chrome` | 束ね・制限の判定・通知の重複防止 |
| 表示名 | `Chrome` | 画面・ミニウィンドウ・通知の文面 |

**判定に表示名を使ってはいけない。** 表示名は対応表の編集で変わり、
かつ「どの行を見たか」でも変わる（PCの記録だけを見れば `chrome.exe`、
スマホも含めれば `Chrome`）。以前は制限時間を表示名で保存していたため、
画面から `Chrome` に制限を設定してもPCでは通知が出なかった（v2.29.0 で修正）。

対応の解決は [app/storage/display.py](../app/storage/display.py) に集約している。
`store.py` は命名の知識を持たない。

| 用途 | メソッド |
|---|---|
| 判定に使う（キー） | `get_limits()` / `get_today_usage_by_key()` / `get_daily_seconds_by_key()` |
| 画面に出す（表示名） | `get_limits_by_name()` / `get_usage_by_range()` / `get_daily_breakdown()` |

## ブランチ運用とコミット

全プロジェクト共通の Git 運用ルールに従う。メインのバージョンは PC版（[CLAUDE.md](../CLAUDE.md#バージョンの記録場所)）。

## リリース手順

1. 更新するファイルは、[CLAUDE.md](../CLAUDE.md) の「バージョンの記録場所」を参照する。Android版を変更したときは、Android版の番号も上げる。
2. GitHub Actions はない。タグを push しても、ビルドや配布は行われない（GitHub Releases は作らない）。
