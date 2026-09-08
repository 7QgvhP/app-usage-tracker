"""
test_display.py - モニター構成と座標計算のテスト

Windows API を呼ぶのは get_monitors のみで、他は純粋な計算のため
実際の画面構成に依存せず検証できる。
"""

from __future__ import annotations

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


MAIN = Monitor(
    name="\\\\.\\DISPLAY2",
    primary=True,
    bounds=(0, 0, 1920, 1080),
    work_area=(0, 0, 1920, 1032),
)
# 右側に縦置きしたサブモニター（原点が負になる配置）
SUB = Monitor(
    name="\\\\.\\DISPLAY1",
    primary=False,
    bounds=(1920, -569, 3000, 1351),
    work_area=(1920, -569, 3000, 1303),
)


class TestClampToArea:
    """表示位置の補正"""

    SCREEN = (0, 0, 1920, 1080)

    def test_position_inside_screen_is_kept(self):
        assert clamp_to_area(100, 200, 240, 90, self.SCREEN) == (100, 200)

    def test_position_beyond_right_edge_is_pulled_back(self):
        assert clamp_to_area(1900, 10, 240, 90, self.SCREEN) == (1680, 10)

    def test_position_beyond_bottom_edge_is_pulled_back(self):
        assert clamp_to_area(10, 1070, 240, 90, self.SCREEN) == (10, 990)

    def test_position_outside_area_is_corrected(self):
        # モニタ構成が変わって画面外に取り残された場合
        assert clamp_to_area(-500, -300, 240, 90, self.SCREEN) == (0, 0)

    def test_window_larger_than_area(self):
        assert clamp_to_area(50, 50, 3000, 2000, self.SCREEN) == (0, 0)

    def test_negative_origin_area_is_preserved(self):
        # 上に伸びたサブモニターなど、原点が負の領域でも0で丸めない
        area = (1920, -569, 3000, 1303)

        assert clamp_to_area(1939, -550, 308, 201, area) == (1939, -550)

    def test_clamped_into_negative_origin_area(self):
        area = (1920, -569, 3000, 1303)

        assert clamp_to_area(0, -9999, 308, 201, area) == (1920, -569)


class TestMonitors:
    """マルチモニターの扱い"""

    def test_virtual_bounds_covers_all(self):
        assert virtual_bounds([MAIN, SUB]) == (0, -569, 3000, 1351)

    def test_monitor_size(self):
        assert (SUB.width, SUB.height) == (1080, 1920)

    def test_find_monitor_by_window_center(self):
        # サブモニターの中央付近にあるウィンドウ
        assert find_monitor(2400, 200, 308, 201, [MAIN, SUB]) is SUB

    def test_find_monitor_on_primary(self):
        assert find_monitor(100, 100, 308, 201, [MAIN, SUB]) is MAIN

    def test_find_monitor_falls_back_to_first(self):
        # どのモニターにも乗っていない座標
        assert find_monitor(-5000, -5000, 308, 201, [MAIN, SUB]) is MAIN

    def test_label_marks_primary(self):
        assert monitor_label(MAIN, 0) == "メイン（1920×1080）"

    def test_label_for_secondary(self):
        assert monitor_label(SUB, 1) == "サブ1（1080×1920）"

    def test_corner_on_secondary_monitor(self):
        # サブモニターの左上は負のy座標になる
        assert corner_position("top-left", 308, 201, SUB.work_area, 19) == (1939, -550)

    def test_bottom_right_on_secondary_monitor(self):
        expected = (3000 - 308 - 19, 1303 - 201 - 19)

        assert corner_position("bottom-right", 308, 201, SUB.work_area, 19) == expected

    def test_get_monitors_returns_real_displays(self):
        monitors = get_monitors(1920, 1080)

        assert len(monitors) >= 1
        assert monitors[0].primary is True
        for m in monitors:
            assert m.width > 0 and m.height > 0
            # 作業領域は必ずモニターの範囲内に収まる
            assert m.work_area[0] >= m.bounds[0] and m.work_area[2] <= m.bounds[2]


class TestCornerPosition:
    """四隅への配置

    作業領域は 1920x1080 からタスクバー48pxを除いた (0, 0, 1920, 1032) を想定。
    ウィンドウは 308x201、余白は5mm相当の19pxとする。
    """

    AREA = (0, 0, 1920, 1032)
    W, H, MARGIN = 308, 201, 19

    def position(self, corner):
        return corner_position(corner, self.W, self.H, self.AREA, self.MARGIN)

    def test_top_left(self):
        assert self.position("top-left") == (19, 19)

    def test_top_right(self):
        assert self.position("top-right") == (1920 - 308 - 19, 19)

    def test_bottom_left(self):
        # タスクバーを避けるため作業領域の下端を基準にする
        assert self.position("bottom-left") == (19, 1032 - 201 - 19)

    def test_bottom_right(self):
        assert self.position("bottom-right") == (1920 - 308 - 19, 1032 - 201 - 19)

    def test_margin_is_kept_on_every_corner(self):
        left, top, right, bottom = self.AREA
        for corner, _label in CORNERS:
            x, y = self.position(corner)
            assert min(x - left, right - (x + self.W)) == self.MARGIN
            assert min(y - top, bottom - (y + self.H)) == self.MARGIN

    def test_offset_work_area_is_respected(self):
        # タスクバーが左側にある場合など、原点が0でない作業領域
        area = (60, 0, 1920, 1080)

        assert corner_position("top-left", self.W, self.H, area, self.MARGIN) == (79, 19)

    def test_all_corner_ids_are_supported(self):
        assert {c for c, _ in CORNERS} == {"top-left", "top-right", "bottom-left", "bottom-right"}
