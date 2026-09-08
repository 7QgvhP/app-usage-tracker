package com.appusagetracker.mobile.usage

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Process
import android.provider.Settings
import android.util.Log
import java.time.LocalDate
import java.time.ZoneId

/**
 * OSが記録している使用状況を読み取る。
 *
 * PC版が自分でポーリングして記録するのに対し、Android では OS が既に記録しているため、
 * このアプリは定期的に取り込むだけでよい。ただし OS が保持する生イベントは
 * 数日程度で消えるため、間隔を空けすぎると欠損する。
 */
class UsageCollector(private val context: Context) {

    companion object {
        private const val TAG = "UsageCollector"

        /** これより短い区間は記録しない（一瞬の切り替えを除くため） */
        const val MIN_DURATION_SECONDS = 30

        /** 取り込みの遡り上限。OSの保持期間より短くしておく */
        const val MAX_LOOKBACK_MILLIS = 3L * 24 * 60 * 60 * 1000

        private const val ONE_DAY_MILLIS = 24L * 60 * 60 * 1000

        /** 画面を持たず、使用時間として意味がないもの */
        private val ALWAYS_EXCLUDED = setOf(
            "com.android.systemui",
            "android",
        )
    }

    private val usageStatsManager: UsageStatsManager? =
        context.getSystemService(Context.USAGE_STATS_SERVICE) as? UsageStatsManager

    /**
     * 使用状況へのアクセスが許可されているか。
     *
     * unsafeCheckOpNoThrow は非推奨だが、代わりの checkOpNoThrow（4引数）は
     * API 36 以降でしか使えない。minSdk 29 で動かす必要があるためこちらを使う。
     */
    @Suppress("DEPRECATION")
    fun hasPermission(): Boolean {
        val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager
            ?: return false

        val mode = appOps.unsafeCheckOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            Process.myUid(),
            context.packageName,
        )
        return mode == AppOpsManager.MODE_ALLOWED
    }

    /** 許可を求める設定画面を開くためのインテント */
    fun permissionIntent(): Intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)

    /**
     * 指定時刻以降の使用区間を取り込む。
     *
     * @param since 前回の取り込み位置。古すぎる場合は MAX_LOOKBACK_MILLIS まで切り上げる
     */
    fun collect(since: Long, now: Long = System.currentTimeMillis()): SessionBuilder.Result {
        val manager = usageStatsManager
        if (manager == null || !hasPermission()) {
            Log.w(TAG, "使用状況へのアクセスが許可されていません")
            return SessionBuilder.Result(emptyList(), now)
        }

        val from = maxOf(since, now - MAX_LOOKBACK_MILLIS)
        val events = readEvents(manager, from, now)
        Log.i(TAG, "イベントを${events.size}件読み取りました (${from}〜${now})")

        return SessionBuilder.build(
            events = events,
            now = now,
            minDurationSeconds = MIN_DURATION_SECONDS,
            excludedPackages = excludedPackages(),
            zone = ZoneId.systemDefault(),
            resolveName = ::resolveAppName,
        )
    }

    /**
     * 指定日のアプリ別使用時間を返す（画面表示用）。
     *
     * 送信済みの区間は端末に残していないため、そのつどOSへ問い合わせ直す。
     * 送信する内容と同じ組み立て処理を通すので、PC側の記録と値が一致する。
     *
     * OSが保持する生イベントは数日程度で消えるため、それより前の日は空になる。
     */
    fun dailyUsage(date: LocalDate): DailyUsage {
        val manager = usageStatsManager
        if (manager == null || !hasPermission()) {
            return DailyUsage(date, emptyList())
        }

        val zone = ZoneId.systemDefault()
        val dayStart = date.atStartOfDay(zone).toInstant().toEpochMilli()
        val dayEnd = minOf(
            date.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli(),
            System.currentTimeMillis(),
        )
        if (dayEnd <= dayStart) return DailyUsage(date, emptyList())

        // その日の開始時点で前面にあったアプリを捉えるため、前日から読み始める
        val events = readEvents(manager, dayStart - ONE_DAY_MILLIS, dayEnd)
        val result = SessionBuilder.build(
            events = events,
            now = dayEnd,
            minDurationSeconds = MIN_DURATION_SECONDS,
            excludedPackages = excludedPackages(),
            zone = zone,
            resolveName = ::resolveAppName,
        )

        // 前日から読んだ分が混ざるため、対象日の区間だけを残す
        val target = date.toString()
        return summarize(result.sessions.filter { it.startedAt(zone).startsWith(target) }, date)
    }

    /**
     * 計測しないパッケージを返す。
     *
     * ホーム画面に留まっている時間はアプリの使用とは言えないため除く
     * （Windows版で explorer.exe を除いているのと同じ考え方）。
     */
    private fun excludedPackages(): Set<String> {
        val home = try {
            val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            context.packageManager
                .resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
                ?.activityInfo?.packageName
        } catch (e: Exception) {
            Log.d(TAG, "ホームアプリを特定できませんでした: ${e.message}")
            null
        }
        return ALWAYS_EXCLUDED + context.packageName + setOfNotNull(home)
    }

    private fun readEvents(
        manager: UsageStatsManager,
        from: Long,
        to: Long,
    ): List<SessionBuilder.Event> {
        val result = mutableListOf<SessionBuilder.Event>()
        val events = manager.queryEvents(from, to)
        val event = UsageEvents.Event()

        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            val packageName = event.packageName ?: continue
            result += SessionBuilder.Event(packageName, event.eventType, event.timeStamp)
        }
        return result
    }

    /**
     * パッケージ名を表示名へ変換する。
     *
     * Windows版の FileDescription にあたるが、こちらは端末の言語に合わせた
     * 正式なアプリ名が確実に得られる。取得できない場合はパッケージ名のまま返す。
     */
    private fun resolveAppName(packageName: String): String = try {
        val info = context.packageManager.getApplicationInfo(packageName, 0)
        context.packageManager.getApplicationLabel(info).toString()
    } catch (e: Exception) {
        Log.d(TAG, "アプリ名を取得できませんでした ($packageName): ${e.message}")
        packageName
    }
}
