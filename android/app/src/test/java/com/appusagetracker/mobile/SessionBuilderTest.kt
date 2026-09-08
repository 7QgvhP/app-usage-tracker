package com.appusagetracker.mobile

import com.appusagetracker.mobile.usage.SessionBuilder
import com.appusagetracker.mobile.usage.UsageSession
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

/**
 * 区間の組み立てのテスト。
 *
 * Android の API に触れない純粋な処理のため、実機やエミュレータ無しで動く。
 */
class SessionBuilderTest {

    private val zone: ZoneId = ZoneId.of("Asia/Tokyo")

    /** 日時からエポックミリ秒を作る */
    private fun at(day: Int, hour: Int, minute: Int, second: Int = 0): Long =
        ZonedDateTime.of(2026, 8, day, hour, minute, second, 0, zone).toInstant().toEpochMilli()

    private fun build(
        events: List<SessionBuilder.Event>,
        now: Long,
        minDuration: Int = 30,
    ): SessionBuilder.Result = SessionBuilder.build(
        events = events,
        now = now,
        minDurationSeconds = minDuration,
        excludedPackages = setOf("com.android.systemui"),
        zone = zone,
        resolveName = { it.substringAfterLast('.') },
    )

    @Test
    fun `前面と背面の対で区間になる`() {
        val result = build(
            listOf(
                SessionBuilder.Event("com.example.youtube", 1, at(23, 10, 0)),
                SessionBuilder.Event("com.example.youtube", 2, at(23, 10, 30)),
            ),
            now = at(23, 11, 0),
        )

        assertEquals(1, result.sessions.size)
        assertEquals(1800, result.sessions[0].durationSeconds)
        assertEquals("youtube", result.sessions[0].appName)
    }

    @Test
    fun `別のアプリが前面に出ると前の区間が閉じる`() {
        // 明示的な背面イベントが来ない機種があるため、切り替えでも閉じる必要がある
        val result = build(
            listOf(
                SessionBuilder.Event("com.example.a", 1, at(23, 10, 0)),
                SessionBuilder.Event("com.example.b", 1, at(23, 10, 30)),
                SessionBuilder.Event("com.example.b", 2, at(23, 11, 0)),
            ),
            now = at(23, 12, 0),
        )

        assertEquals(2, result.sessions.size)
        assertEquals("a", result.sessions[0].appName)
        assertEquals(1800, result.sessions[0].durationSeconds)
        assertEquals("b", result.sessions[1].appName)
    }

    @Test
    fun `画面が消えると開いている区間が閉じる`() {
        val result = build(
            listOf(
                SessionBuilder.Event("com.example.a", 1, at(23, 10, 0)),
                SessionBuilder.Event("com.example.a", 16, at(23, 10, 30)),
            ),
            now = at(23, 12, 0),
        )

        assertEquals(1, result.sessions.size)
        assertEquals(1800, result.sessions[0].durationSeconds)
    }

    @Test
    fun `短すぎる区間は捨てる`() {
        val result = build(
            listOf(
                SessionBuilder.Event("com.example.a", 1, at(23, 10, 0)),
                SessionBuilder.Event("com.example.a", 2, at(23, 10, 0, 10)),
            ),
            now = at(23, 11, 0),
        )

        assertTrue(result.sessions.isEmpty())
    }

    @Test
    fun `除外したパッケージは記録しない`() {
        val result = build(
            listOf(
                SessionBuilder.Event("com.android.systemui", 1, at(23, 10, 0)),
                SessionBuilder.Event("com.android.systemui", 2, at(23, 11, 0)),
            ),
            now = at(23, 12, 0),
        )

        assertTrue(result.sessions.isEmpty())
    }

    @Test
    fun `閉じていない区間は確定させず次回へ持ち越す`() {
        val start = at(23, 10, 0)
        val result = build(
            listOf(SessionBuilder.Event("com.example.a", 1, start)),
            now = at(23, 11, 0),
        )

        assertTrue(result.sessions.isEmpty())
        // 次回はこの区間の開始時刻から取り直す
        assertEquals(start, result.nextCursor)
    }

    @Test
    fun `開いている区間がなければ現在時刻まで進む`() {
        val now = at(23, 12, 0)
        val result = build(
            listOf(
                SessionBuilder.Event("com.example.a", 1, at(23, 10, 0)),
                SessionBuilder.Event("com.example.a", 2, at(23, 11, 0)),
            ),
            now = now,
        )

        assertEquals(now, result.nextCursor)
    }

    @Test
    fun `組み立てた区間は互いに重ならない`() {
        // 前面アプリは常に1つなので、合計と実時間が一致する。
        // PC側はこの前提で二重計上を除いているため、崩さないよう固定しておく
        val result = build(
            listOf(
                SessionBuilder.Event("com.example.a", 1, at(23, 9, 0)),
                SessionBuilder.Event("com.example.b", 1, at(23, 10, 0)),
                SessionBuilder.Event("com.example.a", 1, at(23, 11, 0)),
                SessionBuilder.Event("com.example.a", 2, at(23, 12, 0)),
            ),
            now = at(23, 13, 0),
        )

        val sorted = result.sessions.sortedBy { it.startMillis }
        for (i in 1 until sorted.size) {
            assertTrue(
                "区間が重なっています: ${sorted[i - 1].endMillis} > ${sorted[i].startMillis}",
                sorted[i - 1].endMillis <= sorted[i].startMillis,
            )
        }
        assertEquals(3, sorted.size)
    }

    @Test
    fun `日をまたぐ区間は日付ごとに分割する`() {
        val session = UsageSession("com.example.a", "a", at(23, 23, 30), at(24, 0, 30))
        val parts = SessionBuilder.splitAtMidnight(session, zone)

        assertEquals(2, parts.size)
        assertEquals(1800, parts[0].durationSeconds)
        assertEquals(1800, parts[1].durationSeconds)
        assertEquals("2026-08-23", parts[0].startedAt(zone).substring(0, 10))
        assertEquals("2026-08-24", parts[1].startedAt(zone).substring(0, 10))
    }

    @Test
    fun `分割しても識別子は重複しない`() {
        val session = UsageSession("com.example.a", "a", at(23, 23, 30), at(24, 0, 30))
        val ids = SessionBuilder.splitAtMidnight(session, zone).map { it.externalId }

        assertEquals(ids.size, ids.toSet().size)
    }

    @Test
    fun `日をまたがない区間は分割しない`() {
        val session = UsageSession("com.example.a", "a", at(23, 10, 0), at(23, 11, 0))
        assertEquals(1, SessionBuilder.splitAtMidnight(session, zone).size)
    }

    @Test
    fun `識別子は開始時刻から決まるため再取得しても変わらない`() {
        val events = listOf(
            SessionBuilder.Event("com.example.a", 1, at(23, 10, 0)),
            SessionBuilder.Event("com.example.a", 2, at(23, 11, 0)),
        )
        val first = build(events, now = at(23, 12, 0))
        val second = build(events, now = at(23, 13, 0))

        assertEquals(first.sessions[0].externalId, second.sessions[0].externalId)
    }
}
