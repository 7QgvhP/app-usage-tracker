"""
notion.py - Notion への日次登録

1日1ページを作り、同じ日を送り直したときは既存ページを更新する。
送信済みの日は notion_sync 表に控え、起動時に未送信の日を補う。

トークンは data/notion_token.txt から読む。config.json には書かない
（画面共有などで映る可能性があるため）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import date as date_type
from datetime import datetime, timedelta

from app.report import build_detail_lines, build_summary_text, format_duration

logger = logging.getLogger(__name__)

API_ROOT = "https://api.notion.com/v1"

# 送信時に宣言するAPIのバージョン。Notion は日付で版を管理する
API_VERSION = "2022-06-28"

# 日付が変わったかを確かめる間隔（秒）
DEFAULT_CHECK_INTERVAL = 600

# プロパティ名。Notion 側の表記を変えたときはここだけ直す
PROPS = {
    "title": "日付",
    "date": "日",
    "total": "合計",
    "total_text": "合計（表示）",
    "pc": "PC",
    "phone": "スマホ",
    "overlap": "同時使用",
    "app_count": "アプリ数",
    "top_app": "最長アプリ",
    "top_seconds": "最長時間",
    "spans": "活動時間帯",
    "over_limit": "超過",
    "summary": "要約",
}


class NotionError(Exception):
    """Notion への送信に失敗した"""


def load_token(path: str) -> str | None:
    """トークンを読む（未設定なら None）

    自動生成はしない。利用者が Notion で発行して置くもののため。
    """
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        return None
    return token or None


class NotionClient:
    """Notion API の最小限の呼び出し"""

    def __init__(self, token: str, database_id: str, timeout: float = 20.0):
        self.token = token
        self.database_id = database_id
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
        request = urllib.request.Request(
            f"{API_ROOT}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": API_VERSION,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise NotionError(f"HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise NotionError(str(e)) from e

    def find_page(self, date: str) -> str | None:
        """その日のページを探して ID を返す（無ければ None）"""
        result = self._request(
            "POST",
            f"/databases/{self.database_id}/query",
            {
                "filter": {"property": PROPS["date"], "date": {"equals": date}},
                "page_size": 1,
            },
        )
        results = result.get("results") or []
        return results[0]["id"] if results else None

    def create_page(self, properties: dict, children: list[dict]) -> str:
        """ページを作って ID を返す"""
        result = self._request(
            "POST",
            "/pages",
            {
                "parent": {"database_id": self.database_id},
                "properties": properties,
                "children": children,
            },
        )
        return result["id"]

    def update_page(self, page_id: str, properties: dict, children: list[dict]) -> None:
        """既存ページのプロパティと本文を差し替える"""
        self._request("PATCH", f"/pages/{page_id}", {"properties": properties})
        self._replace_children(page_id, children)

    def _replace_children(self, page_id: str, children: list[dict]) -> None:
        """本文を入れ替える（古いブロックを消してから追加する）"""
        existing = self._request("GET", f"/blocks/{page_id}/children?page_size=100")
        for block in existing.get("results") or []:
            try:
                self._request("DELETE", f"/blocks/{block['id']}")
            except NotionError as e:
                # 消せなくても追加は続ける（本文が二重になるだけで実害は小さい）
                logger.warning(f"本文のブロックを削除できませんでした: {e}")
        if children:
            self._request("PATCH", f"/blocks/{page_id}/children", {"children": children})


def _text(content: str) -> list[dict]:
    """rich_text の値を組み立てる（上限2000文字で切る）"""
    return [{"type": "text", "text": {"content": content[:2000]}}]


def build_properties(report, device_labels: dict[str, str], local_device: str = "pc") -> dict:
    """Notion のプロパティを組み立てる"""
    target = datetime.strptime(report.date, "%Y-%m-%d").date()
    from app.report import WEEKDAYS, active_spans

    minutes = report.total_seconds // 60
    phone_seconds = sum(
        seconds for device, seconds in report.device_seconds.items() if device != local_device
    )
    top = report.top_app

    properties = {
        PROPS["title"]: {
            "title": _text(f"{report.date}（{WEEKDAYS[target.weekday()]}）")
        },
        PROPS["date"]: {"date": {"start": report.date}},
        PROPS["total"]: {"number": minutes},
        PROPS["total_text"]: {"rich_text": _text(format_duration(report.total_seconds))},
        PROPS["pc"]: {"number": report.device_seconds.get(local_device, 0) // 60},
        PROPS["phone"]: {"number": phone_seconds // 60},
        PROPS["overlap"]: {"number": report.overlap_seconds // 60},
        PROPS["app_count"]: {"number": report.app_count},
        PROPS["top_seconds"]: {"number": (top[1] // 60) if top else 0},
        PROPS["spans"]: {"rich_text": _text("、".join(active_spans(report.hours)))},
        PROPS["over_limit"]: {"number": report.over_limit_count},
        PROPS["summary"]: {"rich_text": _text(build_summary_text(report, device_labels))},
    }
    # 選択肢は Notion 側へ自動で追加される。記録が無い日は空にする
    if top:
        properties[PROPS["top_app"]] = {"select": {"name": top[0][:100]}}
    return properties


def build_children(report, device_labels: dict[str, str]) -> list[dict]:
    """ページ本文を組み立てる（要約の文章と、アプリごとの内訳）"""

    def paragraph(content: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _text(content)},
        }

    blocks = [paragraph(build_summary_text(report, device_labels))]

    lines = build_detail_lines(report)
    if lines:
        blocks.append(
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": _text("アプリごとの内訳")},
            }
        )
        blocks.extend(
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": _text(line)},
            }
            for line in lines
        )
    return blocks


class NotionPublisher:
    """日次の送信を担う常駐スレッド

    日付が変わったら前日分を送り、未送信の日があれば遡って補う。
    Notion が応答しない日があっても記録は残るため、次の機会に送り直す。
    """

    def __init__(self, store, config, check_interval: int = DEFAULT_CHECK_INTERVAL):
        self.store = store
        self.config = config
        self.check_interval = check_interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ── 準備できているかの確認 ──

    def reason_unavailable(self) -> str | None:
        """送信できない理由を返す（送信できるなら None）"""
        if not self.config.notion_enabled:
            return "設定で無効になっています"
        if not self.config.notion_database_id:
            return "config.json の notion.database_id が空です"
        if not load_token(self.config.notion_token_path):
            return f"{self.config.notion_token_path} にトークンがありません"
        return None

    def _client(self) -> NotionClient:
        return NotionClient(
            load_token(self.config.notion_token_path), self.config.notion_database_id
        )

    # ── 送信 ──

    def pending_dates(self, today: date_type | None = None) -> list[str]:
        """送るべき日を古い順に返す

        当日はまだ終わっていないため対象にしない。
        遡る範囲は notion.backfill_days で決める。
        """
        today = today or datetime.now().date()
        sent = self.store.get_notion_sent()

        dates = []
        for offset in range(self.config.notion_backfill_days, 0, -1):
            target = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            if target not in sent:
                dates.append(target)
        return dates

    def send_date(self, date: str, client: NotionClient | None = None) -> bool:
        """1日分を送る

        Returns:
            送信した場合は True。記録が無くて送らなかった場合は False。
        """
        from app.report import build_report

        report = build_report(self.store, date)
        if report.is_empty:
            logger.info(f"{date} は記録が無いため Notion へ送りません")
            return False

        client = client or self._client()
        labels = self.config.device_labels
        properties = build_properties(report, labels, self.config.local_device)
        children = build_children(report, labels)

        page_id = self.store.get_notion_sent().get(date) or client.find_page(date)
        if page_id:
            client.update_page(page_id, properties, children)
        else:
            page_id = client.create_page(properties, children)

        self.store.mark_notion_sent(date, page_id)
        logger.info(f"{date} の記録を Notion へ登録しました（{format_duration(report.total_seconds)}）")
        return True

    def run_pending(self) -> int:
        """未送信の日をまとめて送り、送った件数を返す"""
        reason = self.reason_unavailable()
        if reason:
            return 0

        dates = self.pending_dates()
        if not dates:
            return 0

        client = self._client()
        sent = 0
        for date in dates:
            try:
                if self.send_date(date, client):
                    sent += 1
            except NotionError as e:
                # 失敗した日は控えないため、次の機会に送り直される
                logger.warning(f"{date} を Notion へ送れませんでした: {e}")
                break
        return sent

    # ── 常駐 ──

    def start(self) -> None:
        reason = self.reason_unavailable()
        if reason:
            logger.info(f"Notion への登録は行いません（{reason}）")
            return

        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="NotionThread", daemon=True)
        self._thread.start()
        logger.info("Notion への日次登録を開始しました")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_pending()
            except Exception as e:
                logger.error(f"Notion への登録で予期しない例外が発生しました: {e}", exc_info=True)
            self._stop_event.wait(self.check_interval)
