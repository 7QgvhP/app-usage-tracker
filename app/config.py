"""
config.py - アプリケーション設定の管理

プロジェクト直下の config.json を読み込み、欠けている項目は既定値で補完する。
config.json が存在しない場合は既定値の内容で新規生成する。
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

# プロジェクトのルートディレクトリ（app/ の一つ上）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# 既定の設定値
DEFAULTS: dict[str, Any] = {
    "web": {
        "host": "127.0.0.1",
        "port": 5000,
    },
    "tracker": {
        # アクティブウィンドウを確認する間隔（秒）
        "poll_interval_seconds": 5,
        # 集計結果をDBへ書き出す間隔（秒）
        "flush_interval_seconds": 60,
        # 制限時間の何分前に予告通知を出すか
        "notify_before_minutes": 5,
        # アイドル検知（無操作中は計測しない）
        "idle_detection": {
            "enabled": False,
            "threshold_seconds": 300,
        },
    },
    "timeline": {
        # これより短い使用区間は表示しない（一瞬の切り替えを除くため）
        "min_session_seconds": 30,
        # 同じアプリの区間がこの秒数以内で途切れた場合は1つにまとめる
        "merge_gap_seconds": 60,
    },
    "devices": {
        # 記録に使う端末名を、画面で見やすい表記へ変換する対応表
        # 未登録の端末は記録された名前をそのまま表示する
        "labels": {
            "pc": "PC",
        },
    },
    "sync": {
        # スマホなど外部端末からの受信を許可する
        # 有効にすると同一LAN内へポートを公開するため、既定では無効
        "enabled": False,
        # 受信を有効にしたときの待ち受けアドレス（web.host を上書きする）
        "bind_host": "0.0.0.0",
        # 1回のリクエストで受け取れる使用区間の上限
        "max_sessions_per_request": 5000,
        # この時間だけ端末から受信が無ければ警告する
        # スマホのOSは数日分しかイベントを保持しないため、
        # 気付かないまま放置するとその期間の記録が失われる
        "stale_hours": 24,
    },
    "mini_window": {
        # 現在使用中のアプリと本日の使用時間を表示する小型ウィンドウ
        "enabled": True,
        "always_on_top": True,
        # 0.3〜1.0（1.0で不透明）
        "opacity": 0.92,
        "font_size": 22,
    },
    "notion": {
        # 1日1回、前日分を Notion のデータベースへ登録する
        "enabled": False,
        # 登録先のデータベースID（NotionのURLに含まれる32桁）
        "database_id": "",
        # 起動時に遡って補う日数
        "backfill_days": 7,
    },
    "backup": {
        # 1日1回、data/backups へデータベースの複製を作る
        "enabled": True,
        # 残す世代数（上限を超えた古いものから削除される）
        "keep": 7,
    },
    "logging": {
        "level": "INFO",
        # ログファイル1つあたりの最大サイズ（バイト）
        "max_bytes": 1048576,
        # ローテーションで保持する世代数
        "backup_count": 3,
    },
    "apps": {
        # 実行ファイルに埋め込まれた名前（ProductName / FileDescription）を表示名に使う
        # 例: r5apex_dx12.exe → Apex Legends
        # 表示名の読み替えは data/app_names.json で行う（README「アプリ名の対応表」を参照）
        "use_executable_name": True,
        # 計測対象から除外するプロセス名
        "ignore_processes": [
            "explorer.exe",
            "SearchHost.exe",
            "ShellExperienceHost.exe",
            "StartMenuExperienceHost.exe",
            "TextInputHost.exe",
            "ApplicationFrameHost.exe",
            "SystemSettings.exe",
            "LockApp.exe",
        ],
        # ブラウザのウィンドウタイトルからサイトを判定する規則
        "browser_processes": ["chrome.exe"],
        "browser_site_rules": [
            {"name": "YouTube", "patterns": ["- YouTube", "YouTube"]},
            {"name": "X (Twitter)", "patterns": ["/ X", " on X", "X"]},
        ],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """base を override で再帰的に上書きした新しい辞書を返す"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """設定値へのアクセスを提供するクラス

    ログ設定より前に読み込まれるため、読み込み時の問題は例外を送出せず
    load_errors に蓄積し、ログ初期化後に main 側から出力する。
    """

    def __init__(self, data: dict[str, Any], load_errors: list[str] | None = None):
        self._data = data
        self.load_errors: list[str] = load_errors or []

    # ── パス ──

    @property
    def data_dir(self) -> str:
        return os.path.join(BASE_DIR, "data")

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "usage.db")

    @property
    def log_path(self) -> str:
        return os.path.join(BASE_DIR, "app.log")

    @property
    def notion_token_path(self) -> str:
        """Notion の連携トークンを置くファイル

        設定ファイルとは分けて置く（画面共有などで映らないようにするため）。
        自動生成はせず、利用者が Notion で発行して貼り付ける。
        """
        return os.path.join(self.data_dir, "notion_token.txt")

    @property
    def backup_dir(self) -> str:
        """データベースの複製を置くフォルダ"""
        return os.path.join(self.data_dir, "backups")

    @property
    def window_state_path(self) -> str:
        """小型ウィンドウの表示位置を保存するファイル"""
        return os.path.join(self.data_dir, "window_state.json")

    @property
    def app_names_path(self) -> str:
        """アプリ名の対応表を保存するファイル（利用者が編集できる）"""
        return os.path.join(self.data_dir, "app_names.json")

    @property
    def sync_token_path(self) -> str:
        """同期用の共有トークンを保存するファイル

        設定ファイルとは分けて置く（画面共有などで映らないようにするため）。
        """
        return os.path.join(self.data_dir, "sync_token.txt")

    @property
    def template_dir(self) -> str:
        return os.path.join(BASE_DIR, "templates")

    @property
    def static_dir(self) -> str:
        return os.path.join(BASE_DIR, "static")

    # ── Web サーバー ──

    @property
    def host(self) -> str:
        return self._data["web"]["host"]

    @property
    def port(self) -> int:
        return int(self._data["web"]["port"])

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def bind_host(self) -> str:
        """実際に待ち受けるアドレス

        同期を有効にした場合のみ、LANから届くアドレスへ広げる。
        ダッシュボード自体は create_app() 側でループバックのみに制限する。
        """
        if self.sync_enabled:
            return str(self._data["sync"]["bind_host"])
        return self.host

    # ── 端末 ──

    @property
    def device_labels(self) -> dict[str, str]:
        """端末名 → 画面表示名の対応表"""
        return dict(self._data["devices"]["labels"])

    # ── 端末間の同期 ──

    @property
    def sync_enabled(self) -> bool:
        return bool(self._data["sync"]["enabled"])

    @property
    def sync_stale_hours(self) -> int:
        """端末からの受信が途絶えたとみなすまでの時間。1時間未満は許可しない"""
        return max(1, int(self._data["sync"]["stale_hours"]))

    @property
    def sync_max_sessions(self) -> int:
        """1回のリクエストで受け取れる区間数。1件未満は許可しない"""
        return max(1, int(self._data["sync"]["max_sessions_per_request"]))

    # ── トラッカー ──

    @property
    def poll_interval(self) -> float:
        """アクティブウィンドウの確認間隔（秒）。1秒未満は許可しない"""
        return max(1.0, float(self._data["tracker"]["poll_interval_seconds"]))

    @property
    def flush_interval(self) -> float:
        """DBへの書き出し間隔（秒）。確認間隔より短くはならない"""
        value = float(self._data["tracker"]["flush_interval_seconds"])
        return max(self.poll_interval, value)

    @property
    def notify_before_minutes(self) -> int:
        return int(self._data["tracker"]["notify_before_minutes"])

    @property
    def idle_detection_enabled(self) -> bool:
        return bool(self._data["tracker"]["idle_detection"]["enabled"])

    @property
    def idle_threshold_seconds(self) -> float:
        return float(self._data["tracker"]["idle_detection"]["threshold_seconds"])

    # ── タイムライン ──

    @property
    def timeline_min_session_seconds(self) -> int:
        return max(0, int(self._data["timeline"]["min_session_seconds"]))

    @property
    def timeline_merge_gap_seconds(self) -> int:
        return max(0, int(self._data["timeline"]["merge_gap_seconds"]))

    # ── 小型ウィンドウ ──

    @property
    def mini_window_enabled(self) -> bool:
        return bool(self._data["mini_window"]["enabled"])

    @property
    def mini_window_always_on_top(self) -> bool:
        return bool(self._data["mini_window"]["always_on_top"])

    @property
    def mini_window_opacity(self) -> float:
        """不透明度。完全に透明にならないよう下限を設ける"""
        return min(1.0, max(0.3, float(self._data["mini_window"]["opacity"])))

    @property
    def mini_window_font_size(self) -> int:
        return max(8, int(self._data["mini_window"]["font_size"]))

    # ── ログ ──

    @property
    def log_level(self) -> str:
        return str(self._data["logging"]["level"]).upper()

    @property
    def log_max_bytes(self) -> int:
        return int(self._data["logging"]["max_bytes"])

    @property
    def log_backup_count(self) -> int:
        return int(self._data["logging"]["backup_count"])

    # ── アプリ判定 ──

    @property
    def notion_enabled(self) -> bool:
        return bool(self._data["notion"]["enabled"])

    @property
    def notion_database_id(self) -> str:
        return str(self._data["notion"]["database_id"]).strip()

    @property
    def notion_backfill_days(self) -> int:
        return max(1, int(self._data["notion"]["backfill_days"]))

    @property
    def local_device(self) -> str:
        """このPCの記録に付く端末名"""
        from app.storage import LOCAL_DEVICE

        return LOCAL_DEVICE

    @property
    def backup_enabled(self) -> bool:
        return bool(self._data["backup"]["enabled"])

    @property
    def backup_keep(self) -> int:
        return max(1, int(self._data["backup"]["keep"]))

    @property
    def use_executable_name(self) -> bool:
        return bool(self._data["apps"]["use_executable_name"])

    @property
    def ignore_processes(self) -> set[str]:
        return set(self._data["apps"]["ignore_processes"])

    @property
    def browser_processes(self) -> set[str]:
        """小文字に正規化したブラウザのプロセス名集合"""
        return {p.lower() for p in self._data["apps"]["browser_processes"]}

    @property
    def browser_site_rules(self) -> list[dict[str, Any]]:
        return list(self._data["apps"]["browser_site_rules"])


def load_config(path: str | None = None, create_if_missing: bool = True) -> Config:
    """設定を読み込む

    ファイルが存在しない・壊れている場合でも既定値で動作を継続し、
    問題の内容は Config.load_errors に記録する。
    """
    config_path = path or CONFIG_PATH
    errors: list[str] = []
    user_data: dict[str, Any] = {}

    if os.path.exists(config_path):
        try:
            # メモ帳やPowerShellが付与するBOMも読めるよう utf-8-sig を用いる
            with open(config_path, "r", encoding="utf-8-sig") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                user_data = loaded
            else:
                errors.append(f"設定ファイルの形式が不正です（辞書ではありません）: {config_path}")
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"設定ファイルの読み込みに失敗したため既定値を使用します: {e}")
    elif create_if_missing:
        try:
            save_config(DEFAULTS, config_path)
        except OSError as e:
            errors.append(f"既定の設定ファイルを作成できませんでした: {e}")

    merged = _deep_merge(DEFAULTS, user_data)

    # 型が壊れていても起動できるよう、値の妥当性をここで検証する
    config = Config(merged, errors)
    try:
        _validate(config)
    except (TypeError, ValueError, KeyError) as e:
        errors.append(f"設定値が不正なため既定値を使用します: {e}")
        config = Config(copy.deepcopy(DEFAULTS), errors)

    return config


def _validate(config: Config) -> None:
    """すべての設定値へ実際にアクセスし、型変換できることを確認する

    プロパティを走査するため、設定を増やしてもこの関数を直す必要は無い。
    以前は名前を手で並べており、追加し忘れると検証を素通りしていた。
    """
    for name in dir(Config):
        if name.startswith("_"):
            continue
        if isinstance(getattr(Config, name, None), property):
            getattr(config, name)


def save_config(data: dict[str, Any], path: str | None = None) -> None:
    """設定をJSONファイルへ保存する"""
    config_path = path or CONFIG_PATH
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
