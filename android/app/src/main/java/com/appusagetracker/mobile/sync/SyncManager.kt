package com.appusagetracker.mobile.sync

import android.content.Context
import android.util.Log
import com.appusagetracker.mobile.data.SessionStore
import com.appusagetracker.mobile.data.Settings
import com.appusagetracker.mobile.usage.UsageCollector

/**
 * 「OSから取り込む → PCへ送る」という一連の流れをまとめる。
 *
 * 定期実行（SyncWorker）と画面からの手動実行の双方から呼ばれる。
 */
class SyncManager(private val context: Context) {

    companion object {
        private const val TAG = "SyncManager"

        /** 1回の送信で扱う件数。PC側の上限より十分小さくしておく */
        private const val BATCH_SIZE = 500
    }

    private val settings = Settings(context)
    private val store = SessionStore(context)
    private val collector = UsageCollector(context)

    /** 実行結果（画面へそのまま出せる文言を持たせる） */
    data class Outcome(
        val success: Boolean,
        val message: String,
        val collected: Int = 0,
        val sent: Int = 0,
    )

    /**
     * 取り込みと送信を行う。
     *
     * 取り込みは接続先が未設定でも実行する。先に溜めておけば、
     * 設定を済ませた時点でまとめて送れるため。
     */
    fun run(): Outcome {
        val collected = collect()

        if (!settings.isConfigured()) {
            return finish(false, "接続先が未設定です（${store.pendingCount()}件を保存中）", collected)
        }
        if (!collector.hasPermission()) {
            return finish(false, "使用状況へのアクセスが許可されていません", collected)
        }

        val pending = store.take(BATCH_SIZE)
        val client = SyncClient(settings.baseUrl, settings.token, settings.deviceName)

        if (pending.isEmpty()) {
            // 送るものが無くても空で送る。PC側が「届いている」ことを知るための合図で、
            // これが途絶えると同期が止まったと判断される
            return when (val result = client.send(emptyList())) {
                is SyncClient.Result.Success -> finish(true, "送信するものはありません", collected)
                is SyncClient.Result.Unreachable ->
                    finish(false, "PCへ接続できません: ${result.message}", collected)
                is SyncClient.Result.Rejected -> finish(false, result.message, collected)
            }
        }
        return when (val result = client.send(pending)) {
            is SyncClient.Result.Success -> {
                // PC側が受理した分だけを消す。届かなかった分は次回へ残る
                store.remove(pending.map { it.externalId })
                val remaining = store.pendingCount()
                val suffix = if (remaining > 0) "（残り${remaining}件）" else ""
                finish(
                    true,
                    "${pending.size}件を送信しました" +
                        "（新規${result.accepted} / 取込済${result.skipped}）$suffix",
                    collected,
                    pending.size,
                )
            }

            is SyncClient.Result.Unreachable ->
                finish(false, "PCへ接続できません: ${result.message}", collected)

            is SyncClient.Result.Rejected ->
                finish(false, result.message, collected)
        }
    }

    /** 接続確認だけを行う */
    fun ping(): Outcome {
        if (!settings.isConfigured()) {
            return Outcome(false, "接続先とトークンを入力してください")
        }
        val client = SyncClient(settings.baseUrl, settings.token, settings.deviceName)
        return when (val result = client.ping()) {
            is SyncClient.Result.Success -> Outcome(true, "PCへ接続できました")
            is SyncClient.Result.Unreachable -> Outcome(false, "接続できません: ${result.message}")
            is SyncClient.Result.Rejected -> Outcome(false, result.message)
        }
    }

    /** OSから使用区間を取り込み、送信待ちへ加える */
    private fun collect(): Int {
        if (!collector.hasPermission()) return 0

        return try {
            val result = collector.collect(settings.cursor)
            val added = store.add(result.sessions)
            // 取り込めた分まで位置を進める（未確定の区間は次回に持ち越す）
            settings.cursor = result.nextCursor
            Log.i(TAG, "使用区間を${added}件追加しました")
            added
        } catch (e: Exception) {
            Log.e(TAG, "使用区間の取り込みに失敗しました", e)
            0
        }
    }

    private fun finish(success: Boolean, message: String, collected: Int, sent: Int = 0): Outcome {
        settings.lastSyncAt = System.currentTimeMillis()
        settings.lastResult = message
        return Outcome(success, message, collected, sent)
    }

    fun pendingCount(): Int = store.pendingCount()

    fun todayTotals(date: String): List<Pair<String, Int>> = store.totalsFor(date)

    fun hasUsagePermission(): Boolean = collector.hasPermission()

    fun permissionIntent() = collector.permissionIntent()
}
