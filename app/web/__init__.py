"""
web パッケージ - Flask アプリケーションの生成

create_app() でアプリを組み立てることで、グローバル変数を介さずに
データストアやトラッカーを注入できるようにしている。
"""

from __future__ import annotations

import logging
import secrets
import socket
from typing import Optional

from flask import Flask, abort, jsonify, request
from werkzeug.exceptions import HTTPException

from app import __version__
from app.config import Config, load_config
from app.storage import UsageStore
from app.sync import load_or_create_token

logger = logging.getLogger(__name__)

# 同期API。LANへ公開するのはこの配下だけに限る
SYNC_PREFIX = "/api/sync/"

# ループバックとみなすアドレス（IPv4射影表現も含む）
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"})


def is_loopback(address: str | None) -> bool:
    """このPC自身からの接続かどうかを判定する"""
    if not address:
        return False
    return address in LOOPBACK_ADDRESSES or address.startswith("127.")


def create_app(
    store: UsageStore,
    tracker=None,
    config: Optional[Config] = None,
    mini_window=None,
    notion=None,
) -> Flask:
    """Flask アプリケーションを生成する

    Args:
        store: 使用時間データストア
        tracker: 一時停止状態を操作するトラッカー（無い場合は該当APIが無効化される）
        config: アプリケーション設定（省略時は読み込み直す）
        mini_window: ミニウィンドウの表示を仲介するコントローラ
        notion: Notion への登録を担う NotionPublisher（無い場合は該当APIが無効）
    """
    app_config = config or load_config()

    app = Flask(
        __name__,
        template_folder=app_config.template_dir,
        static_folder=app_config.static_dir,
    )
    # 日本語のアプリ名をそのままJSONで返すための設定（Flask 2.3 以降の書式）
    app.json.ensure_ascii = False
    # 同期を有効にしたときだけトークンを用意する（無効なら受信APIも閉じる）
    sync_token = None
    if app_config.sync_enabled:
        try:
            sync_token = load_or_create_token(app_config.sync_token_path)
        except OSError as e:
            logger.error(f"同期用トークンを準備できないため受信を無効にします: {e}")

    app.config.update(
        STORE=store,
        TRACKER=tracker,
        MINI_WINDOW=mini_window,
        NOTION=notion,
        # タイムラインの表示条件を参照するために保持する
        APP_CONFIG=app_config,
        APP_VERSION=__version__,
        SYNC_TOKEN=sync_token,
    )

    from app.web.api import api_bp
    from app.web.views import views_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    _register_access_control(app)
    _register_error_handlers(app)
    return app


def _register_access_control(app: Flask) -> None:
    """LANへ公開したときのアクセス範囲を制限する

    同期のためにポートを開くと、認証の無いダッシュボードにも
    LAN内の他端末から到達できてしまう。これを防ぐため、
    外部からの接続は同期APIだけに限り、そこは共有トークンで認証する。
    """

    @app.before_request
    def restrict_remote_access():
        if request.path.startswith(SYNC_PREFIX):
            token = app.config.get("SYNC_TOKEN")
            if not token:
                abort(503, description="端末間の同期は無効になっています")

            provided = request.headers.get("X-Sync-Token", "")
            # 文字列の比較時間から内容が推測されないようにする
            if not secrets.compare_digest(provided, token):
                logger.warning(f"同期トークンが一致しませんでした (from={request.remote_addr})")
                abort(401, description="トークンが正しくありません")
            return None

        if not is_loopback(request.remote_addr):
            logger.warning(
                f"このPC以外からのアクセスを拒否しました "
                f"(from={request.remote_addr} path={request.path})"
            )
            abort(403, description="このPC以外からは利用できません")

        return None


def _register_error_handlers(app: Flask) -> None:
    """例外処理を一箇所に集約する

    /api 配下は常にJSONで応答し、それ以外は既定のHTML応答を返す。
    """

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        if request.path.startswith("/api"):
            return jsonify({"error": e.description, "status": e.code}), e.code
        return e

    @app.errorhandler(Exception)
    def handle_unexpected_exception(e: Exception):
        logger.error(f"リクエスト処理でエラーが発生しました ({request.path}): {e}", exc_info=True)
        if request.path.startswith("/api"):
            return jsonify({"error": "Internal Server Error"}), 500
        return "Internal Server Error", 500


def check_port_available(host: str, port: int) -> None:
    """指定したポートが使用可能か確認する

    Windows では SO_REUSEADDR の仕様により使用中のポートへも bind できてしまい、
    二重起動しても気付けないまま使用時間が二重に記録される。
    排他指定で bind を試すことで、その状態を起動時に検出する。

    Raises:
        OSError: ポートが既に使用されている場合
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((host, port))
    except OSError as e:
        raise OSError(
            f"ポート {port} は既に使用されています（二重起動の可能性があります）: {e}"
        ) from e
    finally:
        sock.close()


def is_port_available(host: str, port: int) -> bool:
    """ポートが使用可能かを真偽値で返す"""
    try:
        check_port_available(host, port)
        return True
    except OSError:
        return False


def run_server(app: Flask, host: str, port: int) -> None:
    """waitress で本番用サーバーを起動する（呼び出し元をブロックする）"""
    from waitress import serve

    check_port_available(host, port)
    logger.info(f"Webサーバーを起動します: http://{host}:{port}")
    serve(app, host=host, port=port, _quiet=True)
