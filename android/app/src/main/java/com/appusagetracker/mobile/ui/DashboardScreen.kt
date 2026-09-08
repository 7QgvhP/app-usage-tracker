package com.appusagetracker.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.appusagetracker.mobile.usage.DailyUsage
import com.appusagetracker.mobile.usage.UsageCollector
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.LocalDate

/** 曜日つきの見出し（PC版と同じ表記） */
private fun formatHeading(date: LocalDate): String {
    val weekday = "月火水木金土日"[date.dayOfWeek.value - 1]
    return "${date.monthValue}月${date.dayOfMonth}日（$weekday）"
}

@Composable
fun DashboardScreen() {
    val context = LocalContext.current
    val collector = remember { UsageCollector(context) }

    var date by remember { mutableStateOf(LocalDate.now()) }
    var usage by remember { mutableStateOf<DailyUsage?>(null) }
    var loading by remember { mutableStateOf(true) }

    // OSへの問い合わせは時間がかかることがあるため、別スレッドで行う
    LaunchedEffect(date) {
        loading = true
        usage = withContext(Dispatchers.IO) { collector.dailyUsage(date) }
        loading = false
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        DateNavigator(
            date = date,
            onPrevious = { date = date.minusDays(1) },
            onNext = { date = date.plusDays(1) },
            onToday = { date = LocalDate.now() },
        )

        val current = usage
        when {
            loading -> Hint("読み込んでいます...")

            current == null || current.isEmpty -> Hint(
                if (date.isAfter(LocalDate.now())) "まだ先の日付です"
                else "この日の記録はありません（端末が保持しているのは直近数日分です）"
            )

            else -> {
                SectionCard("合計") {
                    Text(
                        formatDuration(current.totalSeconds),
                        fontSize = 28.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        "${current.apps.size}個のアプリ",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                SectionCard("アプリ別") {
                    val max = current.apps.firstOrNull()?.seconds ?: 1
                    current.apps.forEach { app ->
                        UsageBar(app.appName, app.seconds, max)
                    }
                }
            }
        }
    }
}

@Composable
private fun DateNavigator(
    date: LocalDate,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onToday: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TextButton(onClick = onPrevious) { Text("←") }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(formatHeading(date), fontSize = 17.sp, fontWeight = FontWeight.Medium)
            if (date != LocalDate.now()) {
                TextButton(onClick = onToday) { Text("今日へ", fontSize = 12.sp) }
            }
        }
        // 未来の日付へは進めないようにする
        if (date.isBefore(LocalDate.now())) {
            TextButton(onClick = onNext) { Text("→") }
        } else {
            Spacer(Modifier.width(48.dp))
        }
    }
}

/** アプリ1件分の棒。最も長いアプリを全幅として比率で描く */
@Composable
private fun UsageBar(appName: String, seconds: Int, maxSeconds: Int) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(appName, fontSize = 14.sp, modifier = Modifier.weight(1f, fill = false))
            Text(
                formatDuration(seconds),
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(4.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(seconds.toFloat() / maxSeconds.coerceAtLeast(1))
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp))
                    .background(MaterialTheme.colorScheme.primary)
            )
        }
        Spacer(Modifier.height(10.dp))
    }
}

@Composable
private fun Hint(text: String) {
    Text(
        text,
        fontSize = 13.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = 24.dp),
    )
}
