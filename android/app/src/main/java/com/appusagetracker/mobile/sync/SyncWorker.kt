package com.appusagetracker.mobile.sync

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * 定期的に取り込みと送信を行う。
 *
 * WorkManager の周期実行は最短15分。省電力状態でも取りこぼさないよう、
 * 失敗しても記録は端末に残し、次回まとめて送る仕組みにしている。
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "SyncWorker"
        private const val WORK_NAME = "periodic-sync"

        /** 実行間隔。OSのイベント保持期間に対して十分短くする */
        private const val INTERVAL_MINUTES = 15L

        /** 定期実行を登録する（既に登録済みなら設定を保ったままにする） */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(
                INTERVAL_MINUTES, TimeUnit.MINUTES
            ).setConstraints(
                // PCと同じLANにいるときだけ試みる
                Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            ).build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
            Log.i(TAG, "定期同期を登録しました（${INTERVAL_MINUTES}分ごと）")
        }
    }

    override suspend fun doWork(): Result {
        val outcome = SyncManager(applicationContext).run()
        Log.i(TAG, "定期同期: ${outcome.message}")

        // 送れなかった分は端末に残っているため、失敗しても再試行は求めない
        // （次の周期で改めて送る）
        return Result.success()
    }
}
