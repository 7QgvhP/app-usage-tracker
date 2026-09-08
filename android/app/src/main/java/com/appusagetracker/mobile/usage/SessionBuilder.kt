package com.appusagetracker.mobile.usage

import java.time.Instant
import java.time.ZoneId

/**
 * OSのイベント列から使用区間を組み立てる。
 *
 * Android のフレームワークに依存しない純粋な処理として切り出し、
 * 実機がなくても単体テストできるようにしている。
 */
object SessionBuilder {

    /** 画面に現れた（ACTIVITY_RESUMED / MOVE_TO_FOREGROUND） */
    const val TYPE_RESUMED = 1

    /** 画面から消えた（ACTIVITY_PAUSED / MOVE_TO_BACKGROUND） */
    const val TYPE_PAUSED = 2

    /** 画面が消えた・ロックされた・電源が切れた（開いている区間はすべて閉じる） */
    val CLOSING_TYPES = setOf(
        16, // SCREEN_NON_INTERACTIVE
        17, // KEYGUARD_SHOWN
        26, // DEVICE_SHUTDOWN
    )

    /** イベント1件分（UsageEvents.Event から必要な項目だけを取り出したもの） */
    data class Event(val packageName: String, val type: Int, val timeMillis: Long)

    /**
     * 組み立て結果。
     *
     * nextCursor は次回の取り込み開始位置。まだ閉じていない区間があれば
     * その開始時刻まで戻し、次回に完全な形で取り直せるようにする。
     */
    data class Result(val sessions: List<UsageSession>, val nextCursor: Long)

    /**
     * イベント列から区間を作る。
     *
     * @param events 時刻順のイベント列
     * @param now 取り込みを行った時刻
     * @param minDurationSeconds これより短い区間は捨てる（一瞬の切り替えを除くため）
     * @param excludedPackages 計測しないパッケージ
     * @param zone 日付の区切りを判断するタイムゾーン
     * @param resolveName パッケージ名を表示名へ変換する関数
     */
    fun build(
        events: List<Event>,
        now: Long,
        minDurationSeconds: Int,
        excludedPackages: Set<String>,
        zone: ZoneId,
        resolveName: (String) -> String,
    ): Result {
        // パッケージ名 → その区間の開始時刻
        val open = LinkedHashMap<String, Long>()
        val raw = mutableListOf<UsageSession>()

        fun close(packageName: String, at: Long) {
            val start = open.remove(packageName) ?: return
            if (at > start) {
                raw += UsageSession(packageName, packageName, start, at)
            }
        }

        fun closeAll(at: Long) {
            open.keys.toList().forEach { close(it, at) }
        }

        for (event in events.sortedBy { it.timeMillis }) {
            when {
                event.type == TYPE_RESUMED -> {
                    // 前面に立てるアプリは常に1つ。別のアプリが現れたら前のものを閉じる
                    open.keys.filter { it != event.packageName }
                        .forEach { close(it, event.timeMillis) }
                    if (event.packageName !in excludedPackages) {
                        open.putIfAbsent(event.packageName, event.timeMillis)
                    }
                }

                event.type == TYPE_PAUSED -> close(event.packageName, event.timeMillis)

                event.type in CLOSING_TYPES -> closeAll(event.timeMillis)
            }
        }

        // 閉じていない区間は「まだ使用中」なので確定させない
        val cursor = open.values.minOrNull() ?: now

        val sessions = raw
            .flatMap { splitAtMidnight(it, zone) }
            .filter { it.durationSeconds >= minDurationSeconds }
            .map { it.copy(appName = resolveName(it.packageName)) }
            .sortedBy { it.startMillis }

        return Result(sessions, cursor)
    }

    /**
     * 日をまたぐ区間を日付ごとに分割する。
     *
     * PC側は日付ごとに集計しているため、またいだままだと片方の日に
     * すべて計上されてしまう。分割後もそれぞれの開始時刻から
     * externalId が決まるので、識別子は重複しない。
     */
    fun splitAtMidnight(session: UsageSession, zone: ZoneId): List<UsageSession> {
        val result = mutableListOf<UsageSession>()
        var start = session.startMillis

        while (start < session.endMillis) {
            val nextMidnight = Instant.ofEpochMilli(start)
                .atZone(zone)
                .toLocalDate()
                .plusDays(1)
                .atStartOfDay(zone)
                .toInstant()
                .toEpochMilli()

            val end = minOf(nextMidnight, session.endMillis)
            result += session.copy(startMillis = start, endMillis = end)
            start = end
        }

        return result
    }
}
