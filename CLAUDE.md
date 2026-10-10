# app-usage-tracker

共通ルール（コミットの書式、バージョン、タグ、CHANGELOG）は、ここには書きません。このファイルは、このリポジトリ固有の事実だけを書きます。

## 概要
Windows PC とスマートフォンのアプリ使用時間を記録し、ブラウザで確認するための個人用ツールです。PC版（Python / Flask）と、Android版（Kotlin / Jetpack Compose）があります。

## 構成と技術
- `main.py`、`app/`: PC版の本体（計測、保存、Web 画面、API）
  - `app/storage/`: 保存処理、`app/web/`: Flask の画面、`app/web/api/`: API
- `templates/`、`static/`: PC版の画面
- `tests/`: PC版のテスト（pytest）
- `android/`: Android版（Gradle プロジェクト）
- `config.json`: 設定
- `stop_tracker.bat`: 停止用のバッチファイル（CRLF）

## ビルド・テストの手順
PC版:
```bash
pip install -r requirements.txt      # 実行に必要なもの
pip install -r requirements-dev.txt  # テストに必要なもの
python -m pytest tests -q            # テスト
```
Android版:
```bash
cd android && ./gradlew assembleDebug testDebugUnitTest lint
```
- ※ 自動対応でこれらを実行するには、dev-hub の `tools\claude-auto\config.ps1` の `$ExtraTools` で許可が必要です。

## バージョンの記録場所
**メインは PC版です。** タグ、コミットメッセージ末尾の `(vX.Y.Z)`、`CHANGELOG.md` の見出しには、PC版の番号を使います。Android版だけの変更でも、PC版の番号を上げます。

リリースのときに、次をすべて同じコミットで更新します。
- `app/__init__.py` の `__version__`（PC版。メイン）
- `README.md` の冒頭の「**PC版** vX.Y.Z」
- `CHANGELOG.md` の見出し（`## [X.Y.Z] - YYYY-MM-DD`）

Android版を変更したときだけ、次も更新します（サブ。コミットメッセージやタグには使いません）。
- `android/app/build.gradle.kts` の `versionName`
- `README.md` の冒頭の「**Android版** vX.Y.Z」

## 注意事項
- `/data/`（記録データ。個人の利用状況とトークンを含む）とログは、Git 管理外です。コミットしないでください。
- `.gitignore` の `/data/` は、先頭の `/` を外さないでください（外すと、Android版の `mobile/data/` のソースまで除外されます）。
- `CHANGELOG.md` の箇条書きは `-` で、文体は「だ・である」です。
