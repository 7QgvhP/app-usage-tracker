package com.appusagetracker.mobile.usage

import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** PC側と同じ時刻表記（端末のタイムゾーンで表す） */
private val TIME_FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")

/**
 * アプリを使用していた1区間。
 *
 * externalId は「パッケージ名:開始時刻のエポックミリ秒」という決まった値にする。
 * 同じ区間を再送してもPC側で同じ値になり、二重に記録されない。
 */
data class UsageSession(
    val packageName: String,
    val appName: String,
    val startMillis: Long,
    val endMillis: Long,
) {
    val durationSeconds: Int
        get() = ((endMillis - startMillis) / 1000).toInt()

    val externalId: String
        get() = "$packageName:$startMillis"

    fun startedAt(zone: ZoneId): String = format(startMillis, zone)

    fun endedAt(zone: ZoneId): String = format(endMillis, zone)

    private fun format(millis: Long, zone: ZoneId): String =
        LocalDateTime.ofInstant(Instant.ofEpochMilli(millis), zone).format(TIME_FORMAT)
}
