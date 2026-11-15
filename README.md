# App Usage Tracker

Windows PC とスマートフォンのアプリ使用時間を記録し、ブラウザで確認するための個人用ツールです。

- **PC版** v2.30.6（Python / Flask）
- **Android版** v1.3.0（Kotlin / Jetpack Compose） … `android/` 配下

**リポジトリのバージョンは PC版の番号を使います。** タグ（`vX.Y.Z`）、コミットメッセージ末尾の
`(vX.Y.Z)`、`CHANGELOG.md` の見出しは、すべて PC版の番号に対応します。Android版だけの変更でも
PC版の番号を上げ、Android版の番号はコミットメッセージやタグには使いません。

## 概要

PC で前面のアプリの使用時間を記録し、スマホの使用状況も同じ Wi-Fi の中で PC に集めて、ブラウザのダッシュボードで確認する。
記録はすべて手元の SQLite に置き、外部には送らない（Notion への日次登録を有効にした場合を除く）。

## 主な機能

- PC のアプリ（Chrome は登録したサイトごと）の使用時間の記録と、小型ウィンドウでの表示
- 日・週・月の集計、前の期間との増減、タイムライン、制限時間の通知
- アプリ名の対応表による、表示名の変更・統合
- スマホ（Android版）との同期
- Notion への日次登録、データベースの自動バックアップ

## クイックスタート

前提：Windows、Python。

```bash
pip install -r requirements.txt
pythonw main.py
```

ブラウザで `http://127.0.0.1:5000` を開く。常駐のさせ方と停止のしかたは [docs/usage.md](docs/usage.md) を参照。

## ドキュメント

| ファイル | 内容 |
|---|---|
| [docs/spec.md](docs/spec.md) | 仕様（画面、集計の数え方、アプリ名の対応表、Notion、スマホとの連携、データ） |
| [docs/usage.md](docs/usage.md) | 使用方法（起動と停止、表示名の編集、Notion・スマホの設定） |
| [docs/architecture.md](docs/architecture.md) | 設計（構成、ファイル構成、画面の共通化） |
| [docs/development.md](docs/development.md) | 開発者向けガイド（テスト、Android版、配色、名前の扱い） |
| [docs/configuration.md](docs/configuration.md) | 設定リファレンス（`config.json`） |
| [docs/adr/](docs/adr/README.md) | 設計判断記録（ADR） |
| [CHANGELOG.md](CHANGELOG.md) | 変更履歴 |

## ライセンス

TODO(要確認): LICENSE ファイルがなく、ライセンスは定められていない。
