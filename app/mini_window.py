"""
mini_window.py - 現在使用中のアプリを表示する小型ウィンドウ

現在アクティブなアプリ名と、そのアプリの本日の使用時間を「○時間○分」で表示する。
制限時間を設定している場合は進捗バーを、下段には本日の合計と計測状態を表示する。
tkinter（標準ライブラリ）のみで実装しており、追加の依存はない。

トラッカーの走査間隔（既定5秒）より細かく表示を進めるため、取得した値を起点に
クライアント側で1秒ごとに加算し、新しい値を取得するたびに補正する。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import tkinter as tk
import webbrowser
from typing import Optional

from app.display import (
    CORNERS,
    Monitor,
    clamp_to_area,
    corner_position,
    find_monitor,
    get_monitors,
    monitor_label,
    virtual_bounds,
)

logger = logging.getLogger(__name__)

# 配色（ダッシュボードの style.css に合わせる）
COLOR_BG = "#ffffff"
COLOR_BORDER = "#d3d1cc"
COLOR_RULE = "#ebebea"
COLOR_TRACK = "#f1f0ee"
COLOR_TEXT = "#37352f"
COLOR_SUB = "#787774"
COLOR_MUTED = "#9b9a97"
COLOR_HOVER = "#f1f0ee"
# 制限超過など、注意すべき状態にのみ使う色
COLOR_ALERT = "#b05c4a"

UPDATE_INTERVAL_MS = 1000
MAX_NAME_LENGTH = 18
BAR_HEIGHT = 5

# 画面の縁からの余白（ミリメートル）。実際の画素数は画面のDPIから求める
MARGIN_MM = 5
# 余白を画素で求められなかった場合の代替値
FALLBACK_MARGIN_PX = 19


def format_duration(seconds: float) -> str:
    """秒数を「2時間30分」の形へ整形する

    1分に満たない場合は「1分未満」と表す（「0分」では使ったのかどうか分からないため）。

    表記は画面（static/common.js の format.duration）とスマホ（Common.kt の
    formatDuration）に揃えている。同じ数値が場所によって違う文字列になると、
    どちらが正しいのか分からなくなるため。仕様は README「時間の表記」を参照。
    """
    value = max(0, int(seconds))
    if 0 < value < 60:
        return "1分未満"
    return format_minutes(value // 60)


def format_minutes(minutes: int) -> str:
    """分を「2時間30分」の形へ整形する（制限時間やグラフの目盛りにも使う）

    ちょうどの時間は「1時間0分」ではなく「1時間」と表す。
    """
    value = max(0, int(minutes))
    if value < 60:
        return f"{value}分"
    hours, rest = divmod(value, 60)
    return f"{hours}時間{rest}分" if rest else f"{hours}時間"


def display_name(app_name: Optional[str]) -> str:
    """表示用のアプリ名（拡張子を除き、長すぎる場合は省略）"""
    if not app_name:
        return "計測対象外"

    name = app_name[:-4] if app_name.lower().endswith(".exe") else app_name
    if len(name) > MAX_NAME_LENGTH:
        return name[:MAX_NAME_LENGTH] + "…"
    return name


def usage_ratio(seconds: float, limit_minutes: Optional[int]) -> float:
    """制限時間に対する使用率を 0.0〜1.0 で返す（制限未設定なら 0.0）"""
    if not limit_minutes or limit_minutes <= 0:
        return 0.0
    return min(1.0, max(0.0, seconds / (limit_minutes * 60)))


def load_window_position(path: str) -> Optional[tuple[int, int]]:
    """保存された表示位置を読み込む（無い場合や壊れている場合は None）"""
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            state = json.load(f)
        return int(state["x"]), int(state["y"])
    except (OSError, ValueError, TypeError, KeyError) as e:
        logger.debug(f"ウィンドウ位置を読み込めませんでした: {e}")
        return None


def save_window_position(path: str, x: int, y: int) -> None:
    """表示位置を保存する（失敗しても終了処理は継続する）"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"x": int(x), "y": int(y)}, f)
    except OSError as e:
        logger.warning(f"ウィンドウ位置を保存できませんでした: {e}")


class MiniWindowController:
    """ミニウィンドウの表示状態と再表示要求を仲介する

    tkinter はメインスレッドでしか動かせないため、Webサーバー側のスレッドからは
    直接ウィンドウを作れない。ここで要求だけを受け取り、メインスレッドが拾う。
    """

    def __init__(self):
        self._request = threading.Event()
        self._visible = False

    @property
    def visible(self) -> bool:
        """現在ウィンドウが表示されているか"""
        return self._visible

    def set_visible(self, visible: bool) -> None:
        self._visible = visible

    def request_show(self) -> None:
        """再表示を要求する"""
        self._request.set()

    def wait_for_request(self, timeout: float) -> bool:
        """再表示が要求されるまで待つ（タイムアウトで False）"""
        return self._request.wait(timeout)

    def consume_request(self) -> None:
        """要求を破棄する"""
        self._request.clear()


class MiniWindow:
    """現在使用中のアプリと本日の使用時間を表示する小型ウィンドウ

    Args:
        tracker: 現在の使用状況を提供するトラッカー
        config: アプリケーション設定
        shutdown_event: アプリ全体の終了を通知するイベント
    """

    def __init__(self, tracker, config, shutdown_event=None):
        self._tracker = tracker
        self._config = config
        self._shutdown_event = shutdown_event

        self._root: Optional[tk.Tk] = None
        self._name_label: Optional[tk.Label] = None
        self._time_label: Optional[tk.Label] = None
        self._limit_label: Optional[tk.Label] = None
        self._total_label: Optional[tk.Label] = None
        self._status_label: Optional[tk.Label] = None
        self._bar: Optional[tk.Canvas] = None
        self._bar_fill = None
        self._dot: Optional[tk.Canvas] = None
        self._dot_shape = None
        self._after_id: Optional[str] = None

        # 表示値を滑らかに進めるための基準値
        self._anchor_app: Optional[str] = None
        self._anchor_seconds = 0.0
        self._anchor_at = time.monotonic()
        self._anchor_tracking = False

        # ドラッグ移動用の掴んだ位置
        self._drag_x = 0
        self._drag_y = 0

    # ── 表示 ──

    def run(self) -> None:
        """ウィンドウを表示する（閉じられるまで呼び出し元をブロックする）"""
        self._build()
        logger.info("小型ウィンドウを表示しました")

        self._update()
        if self._root is None:
            # 初回更新の時点で既に終了が要求されていた場合はここで戻る
            return

        self._root.mainloop()

    def _build(self) -> None:
        """ウィンドウとウィジェットを組み立てる"""
        root = tk.Tk()
        self._root = root

        root.title("App Usage Tracker")
        # タイトルバーを消して付箋のような見た目にする
        root.overrideredirect(True)
        root.attributes("-topmost", self._config.mini_window_always_on_top)
        root.attributes("-alpha", self._config.mini_window_opacity)
        root.configure(bg=COLOR_BG)

        size = self._config.mini_window_font_size
        outer = tk.Frame(root, bg=COLOR_BG, highlightthickness=1)
        outer.configure(highlightbackground=COLOR_BORDER, highlightcolor=COLOR_BORDER)
        outer.pack(fill="both", expand=True)

        self._build_header(outer, size)
        self._add_rule(outer)
        self._build_body(outer, size)
        self._add_rule(outer)
        self._build_footer(outer, size)

        self._bind_events(root)
        self._place_window(root, size)

    def _add_rule(self, parent: tk.Frame) -> None:
        """1pxの区切り線を追加する"""
        tk.Frame(parent, bg=COLOR_RULE, height=1).pack(fill="x")

    def _build_header(self, parent: tk.Frame, size: int) -> None:
        """アイコン・アプリ名・メニューボタンの行"""
        header = tk.Frame(parent, bg=COLOR_BG, padx=14, pady=9)
        header.pack(fill="x")

        icon = tk.Canvas(
            header, width=13, height=13, bg=COLOR_BG, highlightthickness=0, bd=0
        )
        self._draw_hourglass(icon, 13)
        icon.pack(side="left")

        tk.Label(
            header,
            text="App Usage Tracker",
            bg=COLOR_BG,
            fg=COLOR_SUB,
            font=("Yu Gothic UI", max(8, int(size * 0.42))),
        ).pack(side="left", padx=(7, 0))

        menu_button = tk.Label(
            header,
            text="⋯",
            bg=COLOR_BG,
            fg=COLOR_MUTED,
            font=("Yu Gothic UI", max(9, int(size * 0.5))),
            cursor="hand2",
        )
        menu_button.pack(side="right")
        menu_button.bind("<Button-1>", self._show_menu)
        menu_button.bind("<Enter>", lambda _e: menu_button.config(fg=COLOR_TEXT))
        menu_button.bind("<Leave>", lambda _e: menu_button.config(fg=COLOR_MUTED))

    def _build_body(self, parent: tk.Frame, size: int) -> None:
        """現在のアプリ名・使用時間・制限バーの行"""
        body = tk.Frame(parent, bg=COLOR_BG, padx=14, pady=11)
        body.pack(fill="x")

        # アプリ名は「どのアプリの時間か」を示す主題のため、はっきり読める大きさにする
        self._name_label = tk.Label(
            body,
            text="―",
            bg=COLOR_BG,
            fg=COLOR_TEXT,
            font=("Yu Gothic UI", max(9, int(size * 0.62))),
            anchor="w",
        )
        self._name_label.pack(fill="x", pady=(0, 2))

        self._time_label = tk.Label(
            body,
            text="0時間0分",
            bg=COLOR_BG,
            fg=COLOR_TEXT,
            font=("Yu Gothic UI", size, "bold"),
            anchor="w",
        )
        self._time_label.pack(fill="x", pady=(1, 9))

        bar_row = tk.Frame(body, bg=COLOR_BG)
        bar_row.pack(fill="x")

        self._bar = tk.Canvas(
            bar_row, height=BAR_HEIGHT, bg=COLOR_TRACK, highlightthickness=0, bd=0
        )
        self._bar.pack(side="left", fill="x", expand=True, pady=(4, 0))
        self._bar_fill = self._bar.create_rectangle(
            0, 0, 0, BAR_HEIGHT, fill=COLOR_SUB, width=0
        )

        self._limit_label = tk.Label(
            bar_row,
            text="",
            bg=COLOR_BG,
            fg=COLOR_MUTED,
            font=("Yu Gothic UI", max(8, int(size * 0.38))),
        )
        self._limit_label.pack(side="right", padx=(8, 0))

    def _build_footer(self, parent: tk.Frame, size: int) -> None:
        """本日の合計と計測状態の行"""
        footer = tk.Frame(parent, bg=COLOR_BG, padx=14, pady=8)
        footer.pack(fill="x")

        font = ("Yu Gothic UI", max(8, int(size * 0.38)))
        self._total_label = tk.Label(
            footer, text="", bg=COLOR_BG, fg=COLOR_SUB, font=font
        )
        self._total_label.pack(side="left")

        self._status_label = tk.Label(
            footer, text="計測中", bg=COLOR_BG, fg=COLOR_SUB, font=font
        )
        self._status_label.pack(side="right")

        self._dot = tk.Canvas(footer, width=6, height=6, bg=COLOR_BG, highlightthickness=0, bd=0)
        self._dot_shape = self._dot.create_oval(0, 0, 5, 5, fill=COLOR_MUTED, width=0)
        self._dot.pack(side="right", padx=(0, 5))

    def _draw_hourglass(self, canvas: tk.Canvas, size: int) -> None:
        """アプリアイコン（砂時計）をキャンバスへ描く"""
        s = size / 32.0

        def sc(*points):
            return [p * s for p in points]

        canvas.create_rectangle(*sc(4.5, 2.5, 27.5, 5.5), fill=COLOR_SUB, width=0)
        canvas.create_rectangle(*sc(4.5, 26.5, 27.5, 29.5), fill=COLOR_SUB, width=0)
        canvas.create_polygon(*sc(9.8, 8.4, 22.2, 8.4, 16, 14.6), fill=COLOR_SUB, width=0)
        canvas.create_polygon(*sc(16, 19.2, 22.2, 24.8, 9.8, 24.8), fill=COLOR_SUB, width=0)
        for x in (8, 24):
            canvas.create_line(
                *sc(x, 5.5, x, 9.5, 16, 16, x, 22.5, x, 26.5),
                fill=COLOR_SUB,
                width=max(1, 2.2 * s),
            )

    def _bind_events(self, widget) -> None:
        """ドラッグ移動と右クリックメニューを再帰的に登録する"""
        widget.bind("<Button-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag)
        widget.bind("<Button-3>", self._show_menu)
        for child in widget.winfo_children():
            # メニューボタンは専用の動作を持つため除外する
            if isinstance(child, tk.Label) and child.cget("text") == "⋯":
                continue
            self._bind_events(child)

    def _margin_px(self) -> int:
        """画面の縁から空ける余白を画素で返す（DPIに応じて5mm相当）"""
        try:
            return max(1, int(round(self._root.winfo_fpixels(f"{MARGIN_MM}m"))))
        except (tk.TclError, AttributeError) as e:
            logger.debug(f"余白を画素へ変換できませんでした: {e}")
            return FALLBACK_MARGIN_PX

    def _monitors(self) -> list[Monitor]:
        """接続されている全モニターを取得する"""
        return get_monitors(self._root.winfo_screenwidth(), self._root.winfo_screenheight())

    def _place_window(self, root: tk.Tk, size: int) -> None:
        """保存された位置、または画面右上へ配置する

        アプリ名の長さで幅が変わらないよう、横幅は固定する。
        """
        root.update_idletasks()
        width = max(280, int(size * 14))
        height = root.winfo_reqheight()
        monitors = get_monitors(root.winfo_screenwidth(), root.winfo_screenheight())

        saved = load_window_position(self._config.window_state_path)
        if saved is None:
            x, y = corner_position(
                "top-right", width, height, monitors[0].work_area, self._margin_px()
            )
        else:
            x, y = saved

        # サブモニター上の位置も保てるよう、全モニターを覆う範囲で判定する
        x, y = clamp_to_area(x, y, width, height, virtual_bounds(monitors))
        root.geometry(f"{width}x{height}+{x}+{y}")

    def move_to_corner(self, corner: str, monitor_index: Optional[int] = None) -> None:
        """ウィンドウを指定したモニターの隅へ移動する

        タスクバーに重ならないよう作業領域を基準にし、縁から余白を空ける。

        Args:
            corner: top-left / top-right / bottom-left / bottom-right
            monitor_index: 対象モニター（省略時は現在ウィンドウがあるモニター）
        """
        if self._root is None:
            return

        self._root.update_idletasks()
        width = self._root.winfo_width()
        height = self._root.winfo_height()
        monitors = self._monitors()

        if monitor_index is None:
            target = find_monitor(self._root.winfo_x(), self._root.winfo_y(), width, height, monitors)
        else:
            target = monitors[min(max(0, monitor_index), len(monitors) - 1)]

        x, y = corner_position(corner, width, height, target.work_area, self._margin_px())
        x, y = clamp_to_area(x, y, width, height, target.work_area)

        self._root.geometry(f"+{x}+{y}")
        save_window_position(self._config.window_state_path, x, y)

    # ── 更新 ──

    def _update(self) -> None:
        """表示を更新し、1秒後の更新を予約する"""
        if self._shutdown_event is not None and self._shutdown_event.is_set():
            self.quit_app()
            return

        usage = self._tracker.get_current_usage()
        seconds = self._resolve_seconds(usage)
        limit = usage.get("limit_minutes")
        ratio = usage_ratio(seconds, limit)
        over_limit = bool(limit) and ratio >= 1.0
        inactive = usage["paused"] or usage["idle"] or not usage["app"]

        self._name_label.config(text=display_name(usage["app"]))
        self._time_label.config(text=format_duration(seconds))
        if over_limit:
            self._time_label.config(fg=COLOR_ALERT)
        elif inactive:
            self._time_label.config(fg=COLOR_MUTED)
        else:
            self._time_label.config(fg=COLOR_TEXT)

        self._update_bar(limit, ratio, over_limit)

        self._total_label.config(text=f"今日 {format_duration(usage.get('total_seconds', 0))}")
        if usage["paused"]:
            status, color = "一時停止中", COLOR_ALERT
        elif usage["idle"]:
            status, color = "離席中", COLOR_MUTED
        else:
            status, color = "計測中", COLOR_MUTED
        self._status_label.config(text=status)
        self._dot.itemconfig(self._dot_shape, fill=color)

        self._after_id = self._root.after(UPDATE_INTERVAL_MS, self._update)

    def _update_bar(self, limit: Optional[int], ratio: float, over_limit: bool) -> None:
        """制限時間の進捗バーを更新する"""
        if not limit:
            self._bar.coords(self._bar_fill, 0, 0, 0, BAR_HEIGHT)
            self._limit_label.config(text="制限なし")
            return

        width = self._bar.winfo_width()
        self._bar.coords(self._bar_fill, 0, 0, width * ratio, BAR_HEIGHT)
        self._bar.itemconfig(self._bar_fill, fill=COLOR_ALERT if over_limit else COLOR_SUB)
        self._limit_label.config(text=f"制限 {format_minutes(limit)}")

    def _resolve_seconds(self, usage: dict) -> float:
        """表示する秒数を求める

        トラッカーの走査間隔ぶん表示が飛ぶのを避けるため、取得した値を基準に
        経過時間を加算する。取得値が基準を追い越した場合はそちらへ合わせる。
        """
        now = time.monotonic()
        is_tracking = bool(usage["app"]) and not usage["paused"] and not usage["idle"]

        # 計測を再開した直後に基準を取り直さないと、停止していた時間ぶん表示が飛んでしまう
        if usage["app"] != self._anchor_app or not is_tracking or not self._anchor_tracking:
            self._anchor_app = usage["app"]
            self._anchor_seconds = float(usage["seconds"])
            self._anchor_at = now
            self._anchor_tracking = is_tracking
            return self._anchor_seconds

        interpolated = self._anchor_seconds + (now - self._anchor_at)
        if usage["seconds"] > interpolated:
            self._anchor_seconds = float(usage["seconds"])
            self._anchor_at = now
            return self._anchor_seconds

        return interpolated

    # ── 操作 ──

    def _on_drag_start(self, event) -> None:
        self._drag_x = event.x_root - self._root.winfo_x()
        self._drag_y = event.y_root - self._root.winfo_y()

    def _on_drag(self, event) -> None:
        self._root.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    def _new_menu(self, parent) -> tk.Menu:
        """配色を揃えたメニューを生成する"""
        return tk.Menu(
            parent,
            tearoff=0,
            bg=COLOR_BG,
            fg=COLOR_TEXT,
            activebackground=COLOR_HOVER,
            activeforeground=COLOR_TEXT,
            activeborderwidth=0,
            borderwidth=1,
            font=("Yu Gothic UI", 9),
        )

    def _build_corner_menu(self, parent: tk.Menu) -> tk.Menu:
        """四隅への移動メニューを組み立てる

        モニターが複数ある場合は、モニターごとの階層メニューにする。
        """
        monitors = self._monitors()
        corner_menu = self._new_menu(parent)

        if len(monitors) == 1:
            for corner, label in CORNERS:
                corner_menu.add_command(
                    label=label, command=lambda c=corner: self.move_to_corner(c, 0)
                )
            return corner_menu

        for index, monitor in enumerate(monitors):
            monitor_menu = self._new_menu(corner_menu)
            for corner, label in CORNERS:
                monitor_menu.add_command(
                    label=label,
                    command=lambda c=corner, i=index: self.move_to_corner(c, i),
                )
            corner_menu.add_cascade(label=monitor_label(monitor, index), menu=monitor_menu)

        return corner_menu

    def _show_menu(self, event) -> None:
        """メニューを表示する"""
        menu = self._new_menu(self._root)
        menu.add_command(label="ダッシュボードを開く", command=self._open_dashboard)
        menu.add_command(
            label="計測を再開" if self._tracker.is_paused else "計測を一時停止",
            command=self._toggle_pause,
        )
        menu.add_separator()

        menu.add_cascade(label="定位置へ移動", menu=self._build_corner_menu(menu))
        menu.add_separator()
        # 一度閉じると再表示にはアプリの再起動が必要なため、文言で明示する
        menu.add_command(label="ウィンドウを閉じる（次回起動まで・計測は継続）", command=self.close_window)
        menu.add_command(label="アプリを終了", command=self.quit_app)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_dashboard(self) -> None:
        webbrowser.open(self._config.url)

    def _toggle_pause(self) -> None:
        if self._tracker.is_paused:
            self._tracker.resume()
        else:
            self._tracker.pause()

    def close_window(self) -> None:
        """ウィンドウのみ閉じる（計測は継続する）"""
        self._destroy()
        logger.info("小型ウィンドウを閉じました（計測は継続します）")

    def quit_app(self) -> None:
        """アプリ全体を終了する"""
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        self._destroy()

    def _destroy(self) -> None:
        """表示位置を保存してウィンドウを破棄する"""
        if self._root is None:
            return

        try:
            save_window_position(
                self._config.window_state_path, self._root.winfo_x(), self._root.winfo_y()
            )
            if self._after_id is not None:
                self._root.after_cancel(self._after_id)
                self._after_id = None
            self._root.destroy()
        except tk.TclError as e:
            # 既に破棄されている場合など
            logger.debug(f"ウィンドウの破棄中に例外が発生しました: {e}")
        finally:
            self._root = None
