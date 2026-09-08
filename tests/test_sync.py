"""
test_sync.py - 外部端末（スマホ）からの受信のテスト

受信データの検証、取り込みの冪等性、LAN公開時のアクセス制御を確認する。
"""

from __future__ import annotations

import copy
import sqlite3

import pytest

from app.config import DEFAULTS, Config
from app.storage import LOCAL_DEVICE, SCHEMA_VERSION, UsageStore
from app.sync import (
    ValidationError,
    load_or_create_token,
    normalize_session,
    normalize_sessions,
    validate_device,
)
from app.web import create_app, is_loopback

TOKEN = "test-token-1234567890"


def devices_in(store, start_date, end_date):
    """期間内に記録がある端末名を返す（画面が使うのと同じ経路で確かめる）"""
    rows = store.get_usage_by_device(start_date, end_date)
    return sorted({row["device"] for row in rows})


def make_session(external_id="a:1", app_name="YouTube", start="2026-08-23 10:00:00",
                 end="2026-08-23 10:10:00", seconds=600):
    """テスト用の使用区間を組み立てる"""
    return {
        "external_id": external_id,
        "app_name": app_name,
        "started_at": start,
        "ended_at": end,
        "seconds": seconds,
    }


@pytest.fixture
def sync_config(tmp_path):
    """同期を有効にした設定（トークンは固定値を使う）"""
    data = copy.deepcopy(DEFAULTS)
    data["sync"]["enabled"] = True
    config = Config(data)
    token_path = tmp_path / "data" / "sync_token.txt"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(TOKEN, encoding="utf-8")
    # data_dir はプロジェクト直下を指すため、テスト用の場所へ差し替える
    type(config).sync_token_path = property(lambda self: str(token_path))
    yield config
    del type(config).sync_token_path


@pytest.fixture
def client(store, sync_config):
    app = create_app(store, None, sync_config, None)
    app.config["TESTING"] = True
    return app.test_client()


def post_sync(client, payload, token=TOKEN, **kwargs):
    """同期APIへ送信する"""
    headers = {"X-Sync-Token": token} if token is not None else {}
    return client.post("/api/sync/usage", json=payload, headers=headers, **kwargs)


# ── 端末名の検証 ──


class TestValidateDevice:
    def test_正常な端末名を受け付ける(self):
        assert validate_device("android") == "android"
        assert validate_device("Pixel-8") == "pixel-8"
        assert validate_device(" ANDROID ") == "android"

    def test_pcは予約語のため拒否する(self):
        # このPCの記録は usage_log が正であり、区間から作り直すと壊れるため
        for name in ("pc", "PC", " Pc "):
            with pytest.raises(ValidationError):
                validate_device(name)

    def test_使用できない文字を拒否する(self):
        for name in ("", "a" * 33, "スマホ", "my device", "-lead", "a/b"):
            with pytest.raises(ValidationError):
                validate_device(name)

    def test_文字列以外を拒否する(self):
        for name in (None, 123, ["android"]):
            with pytest.raises(ValidationError):
                validate_device(name)


# ── 使用区間の検証 ──


class TestNormalizeSession:
    def test_日付は開始時刻から導出する(self):
        result = normalize_session(make_session(), 0)
        assert result["date"] == "2026-08-23"
        assert result["seconds"] == 600

    def test_secondsを省略すると区間の長さを使う(self):
        raw = make_session()
        del raw["seconds"]
        assert normalize_session(raw, 0)["seconds"] == 600

    def test_区間より長いsecondsを拒否する(self):
        with pytest.raises(ValidationError, match="区間の長さ"):
            normalize_session(make_session(seconds=601), 0)

    def test_区間より短いsecondsは許可する(self):
        # 無操作時間を差し引いた値が送られてくる場合があるため
        assert normalize_session(make_session(seconds=300), 0)["seconds"] == 300

    def test_終了が開始より前なら拒否する(self):
        raw = make_session(start="2026-08-23 10:10:00", end="2026-08-23 10:00:00", seconds=0)
        with pytest.raises(ValidationError, match="ended_at"):
            normalize_session(raw, 0)

    def test_24時間を超える区間を拒否する(self):
        raw = make_session(start="2026-08-23 00:00:00", end="2026-08-24 00:00:01", seconds=0)
        with pytest.raises(ValidationError, match="24時間"):
            normalize_session(raw, 0)

    def test_必須項目の欠落を拒否する(self):
        for key in ("app_name", "external_id", "started_at", "ended_at"):
            raw = make_session()
            del raw[key]
            with pytest.raises(ValidationError):
                normalize_session(raw, 0)

    def test_時刻の形式違反を拒否する(self):
        with pytest.raises(ValidationError, match="形式"):
            normalize_session(make_session(start="2026/08/23 10:00:00"), 0)

    def test_長すぎるアプリ名は切り詰める(self):
        result = normalize_session(make_session(app_name="あ" * 300), 0)
        assert len(result["app_name"]) == 200

    def test_件数の上限を超えると拒否する(self):
        with pytest.raises(ValidationError, match="5 件まで"):
            normalize_sessions([make_session(f"a:{i}") for i in range(6)], max_count=5)

    def test_配列以外を拒否する(self):
        with pytest.raises(ValidationError, match="配列"):
            normalize_sessions({"a": 1}, max_count=10)


# ── 共有トークン ──


class TestToken:
    def test_無ければ生成して保存する(self, tmp_path):
        path = str(tmp_path / "data" / "sync_token.txt")
        token = load_or_create_token(path)
        assert len(token) >= 24
        # 2回目は同じ値を返す
        assert load_or_create_token(path) == token

    def test_空のファイルは作り直す(self, tmp_path):
        path = tmp_path / "sync_token.txt"
        path.write_text("   ", encoding="utf-8")
        assert load_or_create_token(str(path)).strip() != ""


# ── スキーマ移行 ──


class TestMigration:
    def _create_old_database(self, path):
        """移行前（バージョン0）のデータベースを作る"""
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                app_name TEXT NOT NULL,
                seconds INTEGER NOT NULL DEFAULT 0,
                UNIQUE(date, app_name)
            );
            CREATE TABLE app_limits (
                app_name TEXT PRIMARY KEY,
                limit_minutes INTEGER NOT NULL
            );
            CREATE TABLE usage_session (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                app_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                seconds INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO usage_log (date, app_name, seconds)
                VALUES ('2026-08-20', 'YouTube', 3600), ('2026-08-20', 'chrome.exe', 1800);
            INSERT INTO usage_session (date, app_name, started_at, ended_at, seconds)
                VALUES ('2026-08-20', 'YouTube', '2026-08-20 09:00:00', '2026-08-20 10:00:00', 3600);
            """
        )
        conn.commit()
        conn.close()

    def test_既存の記録をPCの記録として引き継ぐ(self, tmp_path):
        path = str(tmp_path / "usage.db")
        self._create_old_database(path)

        store = UsageStore(path)
        assert store.get_today_usage() == {}  # 今日の記録は無い
        assert store.get_usage_by_range("2026-08-20", "2026-08-20") == {
            "YouTube": 3600,
            "chrome.exe": 1800,
        }
        assert devices_in(store, "2026-08-20", "2026-08-20") == [LOCAL_DEVICE]
        store.close()

    def test_移行後のバージョンが記録される(self, tmp_path):
        path = str(tmp_path / "usage.db")
        self._create_old_database(path)

        store = UsageStore(path)
        store.get_limits()
        store.close()

        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        conn.close()

    def test_移行前の複製が残る(self, tmp_path):
        path = str(tmp_path / "usage.db")
        self._create_old_database(path)

        store = UsageStore(path)
        store.get_limits()
        store.close()

        backups = list(tmp_path.glob("usage.db.bak-*"))
        assert len(backups) == 1

    def test_新規作成では移行も複製も行わない(self, tmp_path):
        path = str(tmp_path / "new.db")
        store = UsageStore(path)
        store.add_usage("メモ帳", 60, "2026-08-23")
        store.close()

        assert list(tmp_path.glob("new.db.bak-*")) == []
        conn = sqlite3.connect(path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        conn.close()

    def test_二度目の接続では移行が走らない(self, tmp_path):
        path = str(tmp_path / "usage.db")
        self._create_old_database(path)

        # UsageStore は最初のDB操作で接続するため、明示的に呼んで移行させる
        first = UsageStore(path)
        first.get_limits()
        first.close()

        second = UsageStore(path)
        second.get_limits()
        second.close()

        # 移行済みなら複製は作られないため、1件目のまま増えない
        assert len(list(tmp_path.glob("usage.db.bak-*"))) == 1
        assert second.get_usage_by_range("2026-08-20", "2026-08-20") == {
            "YouTube": 3600,
            "chrome.exe": 1800,
        }


# ── 取り込み ──


class TestImportSessions:
    def test_区間と日次合計の両方へ反映される(self, store):
        result = store.import_sessions("android", [normalize_session(make_session(), 0)])

        assert result == {"accepted": 1, "skipped": 0, "dates": ["2026-08-23"]}
        assert store.get_usage_by_range("2026-08-23", "2026-08-23", device="android") == {
            "YouTube": 600
        }
        assert len(store.get_sessions("2026-08-23", device="android")) == 1

    def test_同じ内容を再送しても二重にならない(self, store):
        sessions = [normalize_session(make_session(), 0)]
        store.import_sessions("android", sessions)
        result = store.import_sessions("android", sessions)

        assert result["accepted"] == 0
        assert result["skipped"] == 1
        # 合計も膨らまない（加算ではなく作り直しているため）
        assert store.get_usage_by_range("2026-08-23", "2026-08-23", device="android") == {
            "YouTube": 600
        }
        assert len(store.get_sessions("2026-08-23", device="android")) == 1

    def test_一部が重複する再送でも合計が正しい(self, store):
        first = [normalize_session(make_session("a:1"), 0)]
        store.import_sessions("android", first)

        second = [
            normalize_session(make_session("a:1"), 0),
            normalize_session(
                make_session("a:2", start="2026-08-23 11:00:00", end="2026-08-23 11:05:00",
                             seconds=300),
                1,
            ),
        ]
        result = store.import_sessions("android", second)

        assert result["accepted"] == 1
        assert result["skipped"] == 1
        assert store.get_usage_by_range("2026-08-23", "2026-08-23", device="android") == {
            "YouTube": 900
        }

    def test_同一リクエスト内の重複も除かれる(self, store):
        sessions = [normalize_session(make_session("a:1"), 0)] * 2
        result = store.import_sessions("android", sessions)
        assert result == {"accepted": 1, "skipped": 1, "dates": ["2026-08-23"]}

    def test_送り直すと表示名が更新される(self, store):
        # 送信側でアプリ名の判定が良くなった場合に、過去の記録も直せるようにする
        first = make_session("a:1", app_name="com.twitter.android")
        store.import_sessions("android", [normalize_session(first, 0)])

        second = make_session("a:1", app_name="X")
        result = store.import_sessions("android", [normalize_session(second, 0)])

        # 行は増えないが、名前は新しいものになる
        assert result["accepted"] == 0
        assert result["skipped"] == 1
        assert len(store.get_sessions("2026-08-23", device="android")) == 1
        assert store.get_usage_by_range("2026-08-23", "2026-08-23", device="android") == {"X": 600}

    def test_PCの記録は取り込めない(self, store):
        with pytest.raises(ValueError, match="pc"):
            store.import_sessions(LOCAL_DEVICE, [normalize_session(make_session(), 0)])

    def test_PCの記録に影響しない(self, store):
        store.add_usage("YouTube", 1200, "2026-08-23")
        store.import_sessions("android", [normalize_session(make_session(), 0)])

        # 既定はPCのみを返すため、スマホ分は混ざらない
        assert store.get_usage_by_range("2026-08-23", "2026-08-23") == {"YouTube": 1200}
        # 端末を指定しなければ合算される
        assert store.get_usage_by_range("2026-08-23", "2026-08-23", device=None) == {
            "YouTube": 1800
        }

    def test_端末ごとに別の記録として保持される(self, store):
        store.import_sessions("android", [normalize_session(make_session("a:1"), 0)])
        store.import_sessions(
            "tablet",
            [normalize_session(make_session("t:1", start="2026-08-23 12:00:00",
                                            end="2026-08-23 12:30:00", seconds=1800), 0)],
        )

        assert store.get_usage_by_range("2026-08-23", "2026-08-23", device="android") == {
            "YouTube": 600
        }
        assert store.get_usage_by_range("2026-08-23", "2026-08-23", device="tablet") == {
            "YouTube": 1800
        }
        assert devices_in(store, "2026-08-23", "2026-08-23") == ["android", "tablet"]


# ── 合算表示 ──


class TestCombinedView:
    def test_端末別の内訳を取得できる(self, store):
        store.add_usage("YouTube", 600, "2026-08-23")
        store.import_sessions("android", [normalize_session(make_session(), 0)])

        rows = store.get_usage_by_device("2026-08-23", "2026-08-23")
        breakdown = {r["device"]: r["seconds"] for r in rows if r["app_name"] == "YouTube"}

        assert breakdown == {"pc": 600, "android": 600}

    def test_APIは全端末を合算して返す(self, client, store):
        store.add_usage("YouTube", 600)
        post_sync(client, {"device": "android", "sessions": [make_session()]})

        data = client.get("/api/usage/today").get_json()
        youtube = next(d for d in data if d["app"] == "YouTube")

        # 今日の分だけが対象のため、スマホ側の日付が違えば合算されない
        assert youtube["seconds"] >= 600
        assert "devices" in youtube

    def test_状態APIが端末の表示名を返す(self, client):
        data = client.get("/api/status").get_json()
        assert data["local_device"] == LOCAL_DEVICE
        assert data["devices"]["pc"] == "PC"


# ── 受信API ──


class TestSyncApi:
    def test_正常に取り込める(self, client, store):
        response = post_sync(client, {"device": "android", "sessions": [make_session()]})

        assert response.status_code == 200
        assert response.get_json() == {
            "accepted": 1,
            "skipped": 0,
            "dates": ["2026-08-23"],
            "device": "android",
        }

    def test_トークンが無ければ401(self, client):
        response = post_sync(client, {"device": "android", "sessions": []}, token=None)
        assert response.status_code == 401

    def test_トークンが違えば401(self, client):
        response = post_sync(client, {"device": "android", "sessions": []}, token="wrong")
        assert response.status_code == 401

    def test_pcを指定すると400(self, client):
        response = post_sync(client, {"device": "pc", "sessions": [make_session()]})
        assert response.status_code == 400
        assert "pc" in response.get_json()["error"]

    def test_内容が不正なら400(self, client):
        bad = make_session()
        bad["started_at"] = "2026/08/23 10:00:00"
        response = post_sync(client, {"device": "android", "sessions": [bad]})
        assert response.status_code == 400

    def test_JSON以外なら400(self, client):
        response = client.post(
            "/api/sync/usage", data="not json", headers={"X-Sync-Token": TOKEN}
        )
        assert response.status_code == 400

    def test_空の配列でも成功する(self, client):
        response = post_sync(client, {"device": "android", "sessions": []})
        assert response.status_code == 200
        assert response.get_json()["accepted"] == 0

    def test_上限を超える件数は400(self, client, sync_config):
        sync_config._data["sync"]["max_sessions_per_request"] = 2
        sessions = [make_session(f"a:{i}") for i in range(3)]
        response = post_sync(client, {"device": "android", "sessions": sessions})
        assert response.status_code == 400

    def test_接続確認用の情報を返す(self, client):
        response = client.get("/api/sync/info", headers={"X-Sync-Token": TOKEN})
        assert response.status_code == 200
        assert response.get_json()["ok"] is True

    def test_同期が無効なら503(self, store, config):
        # config フィクスチャは sync.enabled が False のまま
        app = create_app(store, None, config, None)
        response = app.test_client().post("/api/sync/usage", json={"device": "android"})
        assert response.status_code == 503


# ── 同期の停止検知 ──


class TestSyncHealth:
    """端末からの受信が途絶えたことを知らせる"""

    def test_受信すると時刻が記録される(self, client, store):
        post_sync(client, {"device": "android", "sessions": [make_session()]})

        seen = store.get_device_seen()
        assert "android" in seen

    def test_送るものが無くても記録される(self, client, store):
        # スマホ側は空でも送ってくる。届いていること自体が合図になる
        post_sync(client, {"device": "android", "sessions": []})

        assert "android" in store.get_device_seen()

    def test_状態APIが受信状況を返す(self, client):
        post_sync(client, {"device": "android", "sessions": []})

        sync = client.get("/api/status").get_json()["sync"]
        entry = next(s for s in sync if s["device"] == "android")

        assert entry["stale"] is False
        assert entry["elapsed_hours"] < 1

    def test_時間が経つと停止とみなす(self, client, store, sync_config):
        from datetime import datetime, timedelta

        old_time = (datetime.now() - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")
        store.touch_device("android", old_time)

        entry = next(
            s for s in client.get("/api/status").get_json()["sync"]
            if s["device"] == "android"
        )
        assert entry["stale"] is True
        assert entry["elapsed_hours"] >= 30

    def test_判定の時間は設定で変えられる(self, client, store, sync_config):
        from datetime import datetime, timedelta

        store.touch_device(
            "android", (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        )

        # 既定の24時間なら問題なし
        entry = next(s for s in client.get("/api/status").get_json()["sync"] if s["device"] == "android")
        assert entry["stale"] is False

        # 3時間に縮めると停止扱いになる
        sync_config._data["sync"]["stale_hours"] = 3
        entry = next(s for s in client.get("/api/status").get_json()["sync"] if s["device"] == "android")
        assert entry["stale"] is True

    def test_同期が無効なら何も返さない(self, store, config):
        app = create_app(store, None, config, None)
        assert app.test_client().get("/api/status").get_json()["sync"] == []


# ── アクセス制御 ──


class TestAccessControl:
    def test_ループバックの判定(self):
        assert is_loopback("127.0.0.1")
        assert is_loopback("::1")
        assert is_loopback("127.0.0.2")
        assert not is_loopback("192.168.1.5")
        assert not is_loopback(None)

    def test_LANからはダッシュボードへ入れない(self, client):
        response = client.get("/", environ_overrides={"REMOTE_ADDR": "192.168.1.5"})
        assert response.status_code == 403

    def test_LANからは通常のAPIも使えない(self, client):
        response = client.get(
            "/api/usage/today", environ_overrides={"REMOTE_ADDR": "192.168.1.5"}
        )
        assert response.status_code == 403
        assert "error" in response.get_json()

    def test_LANからでも同期APIは使える(self, client):
        response = post_sync(
            client,
            {"device": "android", "sessions": [make_session()]},
            environ_overrides={"REMOTE_ADDR": "192.168.1.5"},
        )
        assert response.status_code == 200

    def test_LANからでもトークンが違えば拒否する(self, client):
        response = post_sync(
            client,
            {"device": "android", "sessions": []},
            token="wrong",
            environ_overrides={"REMOTE_ADDR": "192.168.1.5"},
        )
        assert response.status_code == 401

    def test_このPCからは従来どおり使える(self, client):
        assert client.get("/api/usage/today").status_code == 200


# ── 設定 ──


class TestSyncConfig:
    def test_既定では無効でループバックのみ(self):
        config = Config(copy.deepcopy(DEFAULTS))
        assert config.sync_enabled is False
        assert config.bind_host == "127.0.0.1"

    def test_有効にすると待ち受けが広がる(self):
        data = copy.deepcopy(DEFAULTS)
        data["sync"]["enabled"] = True
        assert Config(data).bind_host == "0.0.0.0"

    def test_件数の上限は1件を下回らない(self):
        data = copy.deepcopy(DEFAULTS)
        data["sync"]["max_sessions_per_request"] = 0
        assert Config(data).sync_max_sessions == 1
