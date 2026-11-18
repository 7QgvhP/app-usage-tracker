# 0002. リポジトリのバージョンは PC版の番号を使う

- ステータス: Accepted
- 日付: 2026-10-10（v2.30.2）

## 背景（Context）

1つのリポジトリに、PC版（`app/__init__.py` の `__version__`）と Android版（`android/app/build.gradle.kts` の `versionName`）があり、それぞれがバージョンを持つ。

## 決定内容（Decision）

タグ、コミットメッセージ末尾の `(vX.Y.Z)`、`CHANGELOG.md` の見出しには、PC版の番号を使う。Android版だけの変更でも PC版の番号を上げ、Android版の番号はコミットメッセージやタグには使わない。

## 理由と検討した代替案（Consequences / Alternatives）

- 全プロジェクト共通の Git 運用ルール（1つのリポジトリで複数のバージョンを持つ場合は、メインの端末のバージョンを使う）に従う。
- 検討した代替案: タグに `android-` などの接頭辞を付けて、Android版を別に管理する。共通ルールで使わないことにしている。
