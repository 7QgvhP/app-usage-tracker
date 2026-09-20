package com.appusagetracker.mobile.data

import android.content.Context
import android.os.Build
import androidx.core.content.edit

/**
 * 接続先や取り込み位置の保存。
 *
 * 項目数が少なく構造も単純なため、SharedPreferences をそのまま使う。
 */
class Settings(context: Context) {

    companion object {
        private const val FILE = "settings"
        private const val KEY_HOST = "host"
        private const val KEY_PORT = "port"
        private const val KEY_TOKEN = "token"
        private const val KEY_DEVICE = "device"
        private const val KEY_CURSOR = "cursor"
        private const val KEY_LAST_SYNC = "last_sync"
        private const val KEY_LAST_RESULT = "last_result"

        const val DEFAULT_PORT = 5000
    }

    private val prefs = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** PCのLAN内アドレス（例: 192.168.11.13） */
    var host: String
        get() = prefs.getString(KEY_HOST, "") ?: ""
        set(value) = prefs.edit { putString(KEY_HOST, value.trim()) }

    var port: Int
        get() = prefs.getInt(KEY_PORT, DEFAULT_PORT)
        set(value) = prefs.edit { putInt(KEY_PORT, value) }

    /** PC側の data/sync_token.txt に書かれている値 */
    var token: String
        get() = prefs.getString(KEY_TOKEN, "") ?: ""
        set(value) = prefs.edit { putString(KEY_TOKEN, value.trim()) }

    /** PC側で記録を区別するための端末名。英小文字・数字・ハイフンのみ */
    var deviceName: String
        get() = prefs.getString(KEY_DEVICE, null) ?: defaultDeviceName()
        set(value) = prefs.edit { putString(KEY_DEVICE, value.trim().lowercase()) }

    /** 次回の取り込み開始位置（エポックミリ秒） */
    var cursor: Long
        get() = prefs.getLong(KEY_CURSOR, 0L)
        set(value) = prefs.edit { putLong(KEY_CURSOR, value) }

    /** 最後に同期した時刻。未実施なら 0 */
    var lastSyncAt: Long
        get() = prefs.getLong(KEY_LAST_SYNC, 0L)
        set(value) = prefs.edit { putLong(KEY_LAST_SYNC, value) }

    /** 最後の同期結果（画面に出す短い説明） */
    var lastResult: String
        get() = prefs.getString(KEY_LAST_RESULT, "") ?: ""
        set(value) = prefs.edit { putString(KEY_LAST_RESULT, value) }

    /** 接続先が揃っているか */
    fun isConfigured(): Boolean = host.isNotBlank() && token.isNotBlank()

    val baseUrl: String
        get() = "http://$host:$port"

    /** 端末の機種名から既定の端末名を作る（PC側の制限に合わせて整える） */
    private fun defaultDeviceName(): String {
        val raw = "${Build.MANUFACTURER}-${Build.MODEL}".lowercase()
        val cleaned = raw.replace(Regex("[^a-z0-9_-]"), "-")
            .replace(Regex("-+"), "-")
            .trim('-')
            .take(32)
        return cleaned.ifBlank { "android" }
    }
}
