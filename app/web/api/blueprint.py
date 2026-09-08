"""
blueprint.py - APIのBlueprint

ルートを載せる各モジュールと、それらを取り込む __init__.py の両方が参照する。
どちらか一方に置くと循環参照になるため、ここだけに定義する。
"""

from __future__ import annotations

from flask import Blueprint

api_bp = Blueprint("api", __name__)
