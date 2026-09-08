"""Notion への日次登録

実際の通信は行わない。送る内容と、送信の要否の判断を検証する。
"""

from __future__ import annotations

import copy
from datetime import date

import pytest

from app.config import DEFAULTS, Config
from app.notion import (
    PROPS,
    NotionError,
    NotionPublisher,
    build_children,
    build_properties,
    load_token,
)
from app.report import build_report

LABELS = {"pc": "PC", "android": "スマホ"}


class FakeClient:
    """Notion API の代わり。送られた内容を控える"""

    def __init__(self, existing=None, fail=False):
        self.existing = existing or {}
        self.fail = fail
        self.created = []
        self.updated = []

    def find_page(self, date):
        if self.fail:
            raise NotionError("接続できません")
        return self.existing.get(date)

    def create_page(self, properties, children):
        if self.fail:
            raise NotionError("接続できません")
        self.created.append((properties, children))
        return f"page-{len(self.created)}"

    def update_page(self, page_id, properties, children):
        if self.fail:
            raise NotionError("接続できません")
        self.updated.append((page_id, properties, children))


@pytest.fixture
def notion_config(tmp_path):
    data = copy.deepcopy(DEFAULTS)
    data["notion"]["enabled"] = True
    data["notion"]["database_id"] = "db-1234"
    data["notion"]["backfill_days"] = 3
    config = Config(data, [])
    # トークンとデータベースの場所をテスト用へ差し替える
    token = tmp_path / "notion_token.txt"
    token.write_text("secret_token", encoding="utf-8")
    type(config).notion_token_path = property(lambda self: str(token))
    return config


@pytest.fixture
def filled(store):
    store.add_session("Claude", "2026-03-02 09:00:00", "2026-03-02 10:00:00", 3600)
    store.add_usage("Claude", 3600, "2026-03-02")
    store.import_sessions("android", [{
        "date": "2026-03-02", "app_name": "X (Twitter)",
        "started_at": "2026-03-02 22:00:00", "ended_at": "2026-03-02 22:40:00",
        "seconds": 2400, "external_id": "a:1",
    }])
    return store


class TestLoadToken:
    """トークンの読み込み"""

    def test_無ければNone(self, tmp_path):
        assert load_token(str(tmp_path / "ない.txt")) is None

    def test_空のファイルもNone(self, tmp_path):
        path = tmp_path / "t.txt"
        path.write_text("  \n", encoding="utf-8")
        assert load_token(str(path)) is None

    def test_前後の空白を落とす(self, tmp_path):
        path = tmp_path / "t.txt"
        path.write_text("  secret \n", encoding="utf-8")
        assert load_token(str(path)) == "secret"


class TestProperties:
    """Notion のプロパティ組み立て"""

    def test_必要な項目がそろう(self, filled):
        report = build_report(filled, "2026-03-02")

        props = build_properties(report, LABELS)

        assert props[PROPS["date"]]["date"]["start"] == "2026-03-02"
        assert props[PROPS["total"]]["number"] == 100  # 1時間40分
        assert props[PROPS["pc"]]["number"] == 60
        assert props[PROPS["phone"]]["number"] == 40
        assert props[PROPS["top_app"]]["select"]["name"] == "Claude"
        assert props[PROPS["app_count"]]["number"] == 2

    def test_タイトルは日付と曜日(self, filled):
        props = build_properties(build_report(filled, "2026-03-02"), LABELS)

        assert props[PROPS["title"]]["title"][0]["text"]["content"] == "2026-03-02（月）"

    def test_合計は分の数値と表示用の両方を持つ(self, filled):
        props = build_properties(build_report(filled, "2026-03-02"), LABELS)

        assert props[PROPS["total"]]["number"] == 100
        assert props[PROPS["total_text"]]["rich_text"][0]["text"]["content"] == "1時間40分"

    def test_長い文字列は2000文字で切る(self, filled):
        report = build_report(filled, "2026-03-02")
        report.apps = [(f"アプリ{i}" * 20, 3600) for i in range(60)]

        props = build_properties(report, LABELS)

        for value in props.values():
            for item in value.get("rich_text", []) + value.get("title", []):
                assert len(item["text"]["content"]) <= 2000


class TestChildren:
    """ページ本文の組み立て"""

    def test_要約と内訳が入る(self, filled):
        blocks = build_children(build_report(filled, "2026-03-02"), LABELS)

        assert blocks[0]["type"] == "paragraph"
        assert "3月2日" in blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
        assert any(b["type"] == "bulleted_list_item" for b in blocks)

    def test_1リクエストの上限に収まる(self, filled):
        """Notion は1リクエスト1000ブロックまで"""
        blocks = build_children(build_report(filled, "2026-03-02"), LABELS)

        assert len(blocks) < 1000


class TestPublisher:
    """送信の要否と実行"""

    def publisher(self, store, config):
        return NotionPublisher(store, config)

    def test_設定が無効なら送らない(self, store, notion_config):
        notion_config._data["notion"]["enabled"] = False

        assert self.publisher(store, notion_config).reason_unavailable() is not None

    def test_データベースIDが空なら送らない(self, store, notion_config):
        notion_config._data["notion"]["database_id"] = ""

        assert "database_id" in self.publisher(store, notion_config).reason_unavailable()

    def test_準備できていれば理由は無い(self, store, notion_config):
        assert self.publisher(store, notion_config).reason_unavailable() is None

    def test_未送信の日を古い順に返す(self, store, notion_config):
        publisher = self.publisher(store, notion_config)

        dates = publisher.pending_dates(today=date(2026, 3, 5))

        assert dates == ["2026-03-02", "2026-03-03", "2026-03-04"]

    def test_当日は対象にしない(self, store, notion_config):
        """まだ終わっていない日は送らない"""
        publisher = self.publisher(store, notion_config)

        assert "2026-03-05" not in publisher.pending_dates(today=date(2026, 3, 5))

    def test_送信済みの日は除く(self, store, notion_config):
        store.mark_notion_sent("2026-03-03", "page-x")
        publisher = self.publisher(store, notion_config)

        dates = publisher.pending_dates(today=date(2026, 3, 5))

        assert dates == ["2026-03-02", "2026-03-04"]

    def test_記録が無い日は送らない(self, store, notion_config):
        publisher = self.publisher(store, notion_config)
        client = FakeClient()

        assert publisher.send_date("2026-03-02", client) is False
        assert client.created == []

    def test_新しい日はページを作る(self, filled, notion_config):
        publisher = self.publisher(filled, notion_config)
        client = FakeClient()

        assert publisher.send_date("2026-03-02", client) is True
        assert len(client.created) == 1
        assert filled.get_notion_sent()["2026-03-02"] == "page-1"

    def test_二度目は更新して重複させない(self, filled, notion_config):
        publisher = self.publisher(filled, notion_config)
        client = FakeClient()
        publisher.send_date("2026-03-02", client)

        publisher.send_date("2026-03-02", client)

        assert len(client.created) == 1
        assert len(client.updated) == 1
        assert client.updated[0][0] == "page-1"

    def test_Notion側に既にある日は更新する(self, filled, notion_config):
        """送信記録が消えていても、同じ日のページを二重に作らない"""
        publisher = self.publisher(filled, notion_config)
        client = FakeClient(existing={"2026-03-02": "既存ページ"})

        publisher.send_date("2026-03-02", client)

        assert client.created == []
        assert client.updated[0][0] == "既存ページ"

    def test_失敗した日は送信済みにしない(self, filled, notion_config):
        """次の機会に送り直せるようにする"""
        publisher = self.publisher(filled, notion_config)

        with pytest.raises(NotionError):
            publisher.send_date("2026-03-02", FakeClient(fail=True))

        assert filled.get_notion_sent() == {}
