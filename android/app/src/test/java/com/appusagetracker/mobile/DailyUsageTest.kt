package com.appusagetracker.mobile

import com.appusagetracker.mobile.usage.UsageSession
import com.appusagetracker.mobile.usage.summarize
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime

/** 画面表示用の集計のテスト */
class DailyUsageTest {

    private val zone: ZoneId = ZoneId.of("Asia/Tokyo")
    private val date: LocalDate = LocalDate.of(2026, 8, 23)

    private fun at(hour: Int, minute: Int): Long =
        ZonedDateTime.of(2026, 8, 23, hour, minute, 0, 0, zone).toInstant().toEpochMilli()

    private fun session(name: String, fromHour: Int, toHour: Int) =
        UsageSession("com.example.$name", name, at(fromHour, 0), at(toHour, 0))

    @Test
    fun `同じアプリの区間は合算される`() {
        val result = summarize(
            listOf(session("a", 9, 10), session("a", 14, 15), session("b", 11, 12)),
            date,
        )

        assertEquals(2, result.apps.size)
        assertEquals(7200, result.apps[0].seconds)
        assertEquals("a", result.apps[0].appName)
    }

    @Test
    fun `使用時間の多い順に並ぶ`() {
        val result = summarize(
            listOf(session("short", 9, 10), session("long", 12, 15)),
            date,
        )

        assertEquals("long", result.apps[0].appName)
        assertEquals("short", result.apps[1].appName)
    }

    @Test
    fun `合計は全アプリの和になる`() {
        val result = summarize(listOf(session("a", 9, 10), session("b", 11, 13)), date)
        assertEquals(3 * 3600, result.totalSeconds)
    }

    @Test
    fun `記録が無い日は空になる`() {
        val result = summarize(emptyList(), date)
        assertTrue(result.isEmpty)
        assertEquals(0, result.totalSeconds)
    }
}
