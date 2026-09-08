package com.appusagetracker.mobile

import com.appusagetracker.mobile.ui.formatDuration
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 表示用の整形のテスト
 *
 * 表記の規則は PC本体(Python)・画面(JavaScript)・スマホ(Kotlin) の3つに
 * 別々に実装されている。同じ数値が場所によって違う文字列になってはいけないため、
 * PC側の tests/duration_cases.py を唯一の仕様とし、ここでも同じ内容を検証する。
 */
class FormatTest {

    @Test
    fun `1分に満たない場合は1分未満と表す`() {
        // 「0分」では使ったのかどうか分からないため区別する
        assertEquals("1分未満", formatDuration(1))
        assertEquals("1分未満", formatDuration(30))
        assertEquals("1分未満", formatDuration(59))
    }

    @Test
    fun `記録が無い場合は0分`() {
        assertEquals("0分", formatDuration(0))
    }

    @Test
    fun `分のみ`() {
        assertEquals("1分", formatDuration(60))
        assertEquals("45分", formatDuration(45 * 60))
        assertEquals("59分", formatDuration(59 * 60))
    }

    @Test
    fun `ちょうど1時間は分を付けない`() {
        assertEquals("1時間", formatDuration(3600))
    }

    @Test
    fun `時間と分`() {
        assertEquals("1時間1分", formatDuration(3661))
        assertEquals("2時間30分", formatDuration(2 * 3600 + 30 * 60))
    }

    @Test
    fun `秒は切り上げない`() {
        assertEquals("1時間59分", formatDuration(3600 + 59 * 60 + 59))
    }

    @Test
    fun `24時間を超えても時間で表す`() {
        assertEquals("25時間", formatDuration(25 * 3600))
    }
}
