"""
views.py - 画面表示のルーティング
"""

from __future__ import annotations

from flask import Blueprint, current_app, render_template

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def dashboard():
    """ダッシュボード画面"""
    return render_template("dashboard.html", version=current_app.config["APP_VERSION"])


@views_bp.route("/timeline")
def timeline():
    """タイムライン画面（いつ使ったか）"""
    return render_template("timeline.html", version=current_app.config["APP_VERSION"])


@views_bp.route("/history")
def history():
    """履歴画面（過去の利用状況の一覧）"""
    return render_template("history.html", version=current_app.config["APP_VERSION"])
