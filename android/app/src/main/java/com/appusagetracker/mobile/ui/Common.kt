package com.appusagetracker.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** 秒数を「2時間30分」の形へ（PC版と同じ表記。1分に満たない場合は「1分未満」） */
fun formatDuration(seconds: Int): String {
    if (seconds in 1..59) return "1分未満"
    val minutes = seconds / 60
    if (minutes < 60) return "${minutes}分"
    val hours = minutes / 60
    val rest = minutes % 60
    return if (rest > 0) "${hours}時間${rest}分" else "${hours}時間"
}

/** エポックミリ秒を「8月23日 21:45」の形へ */
fun formatTime(millis: Long): String =
    if (millis <= 0) "未実施"
    else LocalDateTime.ofInstant(Instant.ofEpochMilli(millis), ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("M月d日 HH:mm"))

/** 見出し付きの区切り */
@Composable
fun SectionCard(title: String, content: @Composable () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                title,
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            content()
        }
    }
}

/** 左に項目名、右に値を並べる行 */
@Composable
fun LabeledRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, fontSize = 14.sp)
        Text(value, fontSize = 14.sp, fontWeight = FontWeight.Medium)
    }
}
