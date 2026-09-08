package com.appusagetracker.mobile.usage

import java.time.LocalDate

/** 1日分のアプリ別使用時間 */
data class AppUsage(val appName: String, val seconds: Int)

/** 画面に出す1日分のまとめ */
data class DailyUsage(
    val date: LocalDate,
    val apps: List<AppUsage>,
) {
    val totalSeconds: Int
        get() = apps.sumOf { it.seconds }

    val isEmpty: Boolean
        get() = apps.isEmpty()
}

/**
 * 区間の一覧をアプリ別の合計へまとめる。
 *
 * 送信する内容と同じ区間から集計するため、PC側に記録される値と一致する。
 */
fun summarize(sessions: List<UsageSession>, date: LocalDate): DailyUsage {
    val totals = LinkedHashMap<String, Int>()
    for (session in sessions) {
        totals[session.appName] = (totals[session.appName] ?: 0) + session.durationSeconds
    }

    val apps = totals.map { AppUsage(it.key, it.value) }.sortedByDescending { it.seconds }
    return DailyUsage(date, apps)
}
