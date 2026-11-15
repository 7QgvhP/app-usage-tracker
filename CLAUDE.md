# app-usage-tracker

コミットの書式、バージョン、タグ、CHANGELOG の規約（全プロジェクト共通）は、ここには書かない。このファイルは、このリポジトリ固有の事実だけを書く。

## 概要
Windows PC とスマートフォンのアプリ使用時間を記録し、ブラウザで確認するための個人用ツール。PC版（Python / Flask）と、Android版（Kotlin / Jetpack Compose）がある。

## 技術スタックと主要ディレクトリ
- `main.py`、`app/`: PC版の本体（計測、保存、Web 画面、API）。`app/storage/` 保存処理、`app/web/` Flask の画面、`app/web/api/` API
- `templates/`、`static/`: PC版の画面
- `tests/`: PC版のテスト（pytest）
- `android/`: Android版（Gradle プロジェクト）
- `config.json`: 設定。`stop_tracker.bat`: 停止用のバッチファイル（CRLF）
- 詳細は [docs/architecture.md](docs/architecture.md)

## コマンド
```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q                                   # PC版のテスト
cd android && ./gradlew assembleDebug testDebugUnitTest lint   # Android版のビルド・テスト・lint
```
- PC版の lint: なし。
- ※ 自動対応でこれらを実行するには、dev-hub の `tools\claude-auto\config.ps1` の `$ExtraTools` で許可が必要。

## コーディング規約
- コメント・docstring・画面の文言は日本語。
- 配色と名前の扱いの決まりは [docs/development.md](docs/development.md) にある。
- `CHANGELOG.md` の箇条書きは `-` で、文体は「だ・である」。

## バージョンの記録場所
**メインは PC版。** タグ、コミットメッセージ末尾の `(vX.Y.Z)`、`CHANGELOG.md` の見出しには、PC版の番号を使う。Android版だけの変更でも、PC版の番号を上げる。

リリースのときに、次をすべて同じコミットで更新する。
- `app/__init__.py` の `__version__`（PC版。メイン）
- `README.md` の冒頭の「**PC版** vX.Y.Z」
- `CHANGELOG.md` の見出し（`## [X.Y.Z] - YYYY-MM-DD`）

Android版を変更したときだけ、次も更新する（サブ。コミットメッセージやタグには使わない）。
- `android/app/build.gradle.kts` の `versionName`
- `README.md` の冒頭の「**Android版** vX.Y.Z」

GitHub Releases は作らない（配布物がないため、タグだけでリリースとする）。

## ドキュメント更新ルール
今後の開発で、次の変更を行う際は、同じ作業の中で該当ドキュメントも更新すること。
- 機能の追加・変更・削除 → `docs/spec.md`、`docs/usage.md`、`CHANGELOG.md`
- 構成や設計の変更 → `docs/architecture.md`
- 設定項目の追加・変更 → `docs/configuration.md`
- 技術選定や設計方針を変える判断 → 新しい ADR を `docs/adr/` に追加する（既存の ADR は書き換えず、ステータスを Superseded にして、新しい ADR から参照する）
- バージョンを上げるとき → `CHANGELOG.md` に新しいバージョンの節（`## [X.Y.Z] - YYYY-MM-DD`）を追加し、「バージョンの記録場所」のファイルをすべて同じコミットで更新する

## 注意事項
- `/data/`（記録データ。個人の利用状況とトークンを含む）とログは、Git 管理外。コミットしない。
- `.gitignore` の `/data/` は、先頭の `/` を外さない（外すと、Android版の `mobile/data/` のソースまで除外される）。
- 起動用のショートカット（`*.lnk`）は、環境固有の絶対パスを含むため Git 管理外。
