"""
main.py - App Usage Tracker エントリーポイント

設定の読み込み、各コンポーネントの組み立て、起動と終了処理のみを担当する。
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import urllib.error
import urllib.request

from app import __version__
from app.backup import BackupScheduler
from app.config import load_config
from app.logging_setup import setup_logging
from app.mini_window import MiniWindowController
from app.naming import AppNameRegistry
from app.notion import NotionPublisher
from app.notifier import Notifier
from app.storage import StorageError, UsageStore
from app.tracker import AppTracker
from app.web import create_app, is_port_available, run_server

logger = logging.getLogger(__name__)


def request_show_mini_window(base_url: str, timeout: float = 3.0) -> bool:
    """既に起動しているインスタンスへミニウィンドウの表示を要求する

    Returns:
        要求できた場合は True。応答が無い場合は False。
    """
    request = urllib.request.Request(f"{base_url}/api/mini-window/show", data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.debug(f"起動中のインスタンスへ要求できませんでした: {e}")
        return False


def show_mini_window(tracker, config, shutdown, controller: MiniWindowController) -> None:
    """ミニウィンドウを表示する（閉じられるまでブロックする）

    表示できない環境でもアプリ全体は動作させたいため、失敗はログに残して継続する。
    """
    from app.mini_window import MiniWindow

    controller.set_visible(True)
    try:
        MiniWindow(tracker, config, shutdown).run()
    except Exception as e:
        logger.error(f"小型ウィンドウを表示できませんでした: {e}", exc_info=True)
    finally:
        controller.set_visible(False)
        # 表示中に届いた要求は、閉じた直後の再表示を招くため破棄する
        controller.consume_request()


def local_ip_address() -> str:
    """LAN内から見えるこのPCのIPアドレスを返す

    外部へ接続はせず、経路表からアドレスを引くだけ。
    判定できない場合は空文字を返す。
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.168.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def log_sync_ready(config) -> None:
    """スマホから接続するための情報をログへ出す

    ファイアウォールの受信規則が無いと届かないため、その案内も添える。
    """
    address = local_ip_address()
    if address:
        logger.info(f"スマホからの接続先: http://{address}:{config.port}")
    else:
        logger.warning("このPCのLAN内アドレスを特定できませんでした")

    logger.info(f"同期トークン: {config.sync_token_path} を参照してください")
    logger.info(
        "接続できない場合はファイアウォールの受信規則を確認してください "
        f"(プライベートネットワークのTCP {config.port} 番)"
    )


def main() -> int:
    """アプリケーションを起動する

    Returns:
        終了コード（正常終了は 0）
    """
    config = load_config()
    setup_logging(
        config.log_path,
        config.log_level,
        config.log_max_bytes,
        config.log_backup_count,
    )

    # 設定の読み込み時に発生した問題は、ログ初期化後にここで出力する
    for message in config.load_errors:
        logger.warning(message)

    logger.info(f"App Usage Tracker v{__version__} を起動しています...")

    # 既に起動している場合は、そちらのミニウィンドウを表示させて終了する
    if not is_port_available(config.bind_host, config.port):
        if request_show_mini_window(config.url):
            logger.info("既に起動しているため、ミニウィンドウの表示を要求して終了します")
            return 0
        logger.critical(
            f"ポート {config.port} は使用中ですが応答がありません。"
            "他のアプリが使用しているか、二重起動の可能性があります"
        )
        return 1

    # アプリ名の対応表を用意する（PCとスマホで名前が違う同じアプリを束ねるため）
    names = AppNameRegistry(config.app_names_path)
    names.load()

    try:
        store = UsageStore(config.db_path, names)
        store.get_limits()  # 起動時点でデータベースへ接続できるか確認する
        # 記録済みのアプリ名を対応表へ取り込み、編集内容があれば束ね方を合わせ直す
        store.register_existing()
        store.renormalize()
    except StorageError as e:
        logger.critical(f"データベースを初期化できないため起動を中止します: {e}")
        return 1

    # 記録の複製は起動直後に1度取り、以後は日付が変わるたびに取る
    backup: BackupScheduler | None = None
    if config.backup_enabled:
        backup = BackupScheduler(config.db_path, config.backup_dir, config.backup_keep)
        backup.start()
    else:
        logger.info("データベースのバックアップは設定により無効です")

    # 前日分を Notion へ登録する（未設定なら何もしない）
    notion = NotionPublisher(store, config)
    notion.start()

    shutdown = threading.Event()
    mini_window = MiniWindowController()

    tracker = AppTracker(config, store, Notifier())
    tracker.start()

    flask_app = create_app(store, tracker, config, mini_window, notion)

    def serve() -> None:
        """Webサーバーを起動する（異常終了時はアプリ全体を終了させる）"""
        try:
            run_server(flask_app, config.bind_host, config.port)
        except Exception as e:
            logger.critical(f"Webサーバーの起動に失敗しました: {e}")
            shutdown.set()

    server_thread = threading.Thread(target=serve, name="WebServerThread", daemon=True)
    server_thread.start()
    logger.info(f"ダッシュボード: {config.url}")

    if config.sync_enabled:
        log_sync_ready(config)

    def handle_signal(signum, _frame) -> None:
        logger.info(f"終了シグナルを受信しました (signal={signum})")
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, OSError):
            # メインスレッド以外やpythonw実行時はシグナルを登録できないことがある
            logger.debug(f"シグナル {sig} を登録できませんでした")

    try:
        if config.mini_window_enabled:
            show_mini_window(tracker, config, shutdown, mini_window)

        # ウィンドウを閉じても計測は続く。再表示の要求を待ちながら終了を監視する
        # タイムアウト付きで待機することで Ctrl+C を受け取れるようにする
        while not shutdown.is_set():
            if mini_window.wait_for_request(1):
                mini_window.consume_request()
                if not shutdown.is_set():
                    show_mini_window(tracker, config, shutdown, mini_window)
    except KeyboardInterrupt:
        logger.info("キーボード操作により終了します")
    finally:
        logger.info("App Usage Tracker を終了しています...")
        tracker.stop()
        if backup is not None:
            backup.stop()
        notion.stop()
        names.save()
        store.close()
        logger.info("終了しました")

    return 0


if __name__ == "__main__":
    sys.exit(main())
