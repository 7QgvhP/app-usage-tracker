package com.appusagetracker.mobile.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.core.database.sqlite.transaction
import com.appusagetracker.mobile.usage.UsageSession
import java.time.ZoneId

/** 送信待ちの使用区間1件 */
data class PendingSession(
    val externalId: String,
    val appName: String,
    val startedAt: String,
    val endedAt: String,
    val seconds: Int,
    val date: String,
)

/**
 * PCへ送るまでの使用区間を溜めておく場所。
 *
 * PCの電源が入っていない間も記録を失わないよう、送信できたものだけを消す。
 * 表が1つで問い合わせも単純なため、SQLite をそのまま使う。
 */
class SessionStore(context: Context) : SQLiteOpenHelper(context, NAME, null, VERSION) {

    companion object {
        private const val NAME = "usage.db"
        private const val VERSION = 1
        private const val TABLE = "pending_session"
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE $TABLE (
                external_id TEXT PRIMARY KEY,
                app_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                seconds INTEGER NOT NULL,
                date TEXT NOT NULL
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX idx_pending_date ON $TABLE(date)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // 将来スキーマを変える場合はここで移行する
    }

    /**
     * 取り込んだ区間を送信待ちへ加える。
     *
     * 同じ externalId は既に控えているため無視する。
     *
     * @return 新たに加えた件数
     */
    fun add(sessions: List<UsageSession>, zone: ZoneId = ZoneId.systemDefault()): Int {
        if (sessions.isEmpty()) return 0

        var added = 0
        writableDatabase.transaction {
            for (session in sessions) {
                val startedAt = session.startedAt(zone)
                val values = ContentValues().apply {
                    put("external_id", session.externalId)
                    put("app_name", session.appName)
                    put("started_at", startedAt)
                    put("ended_at", session.endedAt(zone))
                    put("seconds", session.durationSeconds)
                    put("date", startedAt.substring(0, 10))
                }
                val id = insertWithOnConflict(
                    TABLE, null, values, SQLiteDatabase.CONFLICT_IGNORE
                )
                if (id != -1L) added++
            }
        }
        return added
    }

    /** 送信待ちを古い順に取り出す */
    fun take(limit: Int): List<PendingSession> {
        val result = mutableListOf<PendingSession>()
        readableDatabase.rawQuery(
            """
            SELECT external_id, app_name, started_at, ended_at, seconds, date
            FROM $TABLE ORDER BY started_at LIMIT ?
            """.trimIndent(),
            arrayOf(limit.toString()),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                result += PendingSession(
                    externalId = cursor.getString(0),
                    appName = cursor.getString(1),
                    startedAt = cursor.getString(2),
                    endedAt = cursor.getString(3),
                    seconds = cursor.getInt(4),
                    date = cursor.getString(5),
                )
            }
        }
        return result
    }

    /** 送信できた区間を消す */
    fun remove(externalIds: List<String>) {
        if (externalIds.isEmpty()) return

        val placeholders = externalIds.joinToString(",") { "?" }
        writableDatabase.execSQL(
            "DELETE FROM $TABLE WHERE external_id IN ($placeholders)",
            externalIds.toTypedArray(),
        )
    }

    /** 送信待ちの件数 */
    fun pendingCount(): Int =
        readableDatabase.rawQuery("SELECT COUNT(*) FROM $TABLE", null).use {
            if (it.moveToFirst()) it.getInt(0) else 0
        }

    /**
     * 指定日のアプリ別合計を多い順で返す。
     *
     * 送信済みの分は消えているため、これは「まだ送っていない分」の集計になる。
     */
    fun totalsFor(date: String): List<Pair<String, Int>> {
        val result = mutableListOf<Pair<String, Int>>()
        readableDatabase.rawQuery(
            """
            SELECT app_name, SUM(seconds) FROM $TABLE
            WHERE date = ? GROUP BY app_name ORDER BY SUM(seconds) DESC
            """.trimIndent(),
            arrayOf(date),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                result += cursor.getString(0) to cursor.getInt(1)
            }
        }
        return result
    }
}
