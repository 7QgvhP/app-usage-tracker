package com.appusagetracker.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.appusagetracker.mobile.data.Settings
import com.appusagetracker.mobile.sync.SyncManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun SettingsScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val settings = remember { Settings(context) }
    val manager = remember { SyncManager(context) }

    var host by remember { mutableStateOf(settings.host) }
    var port by remember { mutableStateOf(settings.port.toString()) }
    var token by remember { mutableStateOf(settings.token) }
    var deviceName by remember { mutableStateOf(settings.deviceName) }

    var hasPermission by remember { mutableStateOf(false) }
    var pending by remember { mutableIntStateOf(0) }
    var lastSync by remember { mutableLongStateOf(settings.lastSyncAt) }
    var status by remember { mutableStateOf(settings.lastResult) }
    var busy by remember { mutableStateOf(false) }

    /** 画面の表示内容を最新にする */
    fun refresh() {
        hasPermission = manager.hasUsagePermission()
        pending = manager.pendingCount()
        lastSync = settings.lastSyncAt
    }

    // 設定画面から戻ったときにも反映されるよう、表示のたびに読み直す
    LaunchedEffect(Unit) { refresh() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("App Usage Tracker", fontSize = 22.sp, fontWeight = FontWeight.SemiBold)

        // ── 使用状況へのアクセス許可 ──
        SectionCard("使用状況へのアクセス") {
            Text(
                if (hasPermission) "許可されています" else "許可されていません",
                color = if (hasPermission) MaterialTheme.colorScheme.onSurface
                else MaterialTheme.colorScheme.error,
            )
            if (!hasPermission) {
                Text(
                    "この許可がないと、どのアプリをいつ使ったかを読み取れません。",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(4.dp))
                Button(onClick = { context.startActivity(manager.permissionIntent()) }) {
                    Text("設定を開く")
                }
            }
        }

        // ── 接続先 ──
        SectionCard("PCへの接続先") {
            OutlinedTextField(
                value = host,
                onValueChange = { host = it; settings.host = it },
                label = { Text("IPアドレス（例: 192.168.11.13）") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = port,
                onValueChange = {
                    port = it.filter(Char::isDigit)
                    port.toIntOrNull()?.let { value -> settings.port = value }
                },
                label = { Text("ポート番号") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = token,
                onValueChange = { token = it; settings.token = it },
                label = { Text("同期トークン（PCの sync_token.txt）") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = deviceName,
                onValueChange = { deviceName = it; settings.deviceName = it },
                label = { Text("端末名（PC側での表示に使う）") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedButton(
                enabled = !busy,
                onClick = {
                    scope.launch {
                        busy = true
                        val outcome = withContext(Dispatchers.IO) { manager.ping() }
                        status = outcome.message
                        busy = false
                    }
                },
            ) {
                Text("接続を確認")
            }
        }

        // ── 同期 ──
        SectionCard("同期") {
            LabeledRow("最後の同期", formatTime(lastSync))
            LabeledRow("送信待ち", "${pending}件")
            if (status.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(status, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(4.dp))
            Button(
                enabled = !busy,
                onClick = {
                    scope.launch {
                        busy = true
                        val outcome = withContext(Dispatchers.IO) { manager.run() }
                        status = outcome.message
                        refresh()
                        busy = false
                    }
                },
            ) {
                Text(if (busy) "実行中..." else "今すぐ同期")
            }
            Text(
                "15分ごとに自動で同期します。PCが起動していない間は端末に保存し、"
                    + "次に繋がったときにまとめて送ります。",
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
