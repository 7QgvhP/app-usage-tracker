package com.appusagetracker.mobile.sync

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** 端末の再起動後も定期同期を続けるための受信側 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            SyncWorker.schedule(context)
        }
    }
}
