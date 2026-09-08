package com.appusagetracker.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color
import com.appusagetracker.mobile.sync.SyncWorker
import com.appusagetracker.mobile.ui.MainScreen

/** PC版に合わせた白基調の配色 */
private val LightColors = lightColorScheme(
    primary = Color(0xFF37352F),
    onPrimary = Color.White,
    surface = Color.White,
    onSurface = Color(0xFF37352F),
    background = Color(0xFFFBFBFA),
    onBackground = Color(0xFF37352F),
    surfaceVariant = Color(0xFFF1F0EE),
    onSurfaceVariant = Color(0xFF787774),
    error = Color(0xFFB05C4A),
)

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 画面を開いた時点で定期同期を確実に登録しておく
        SyncWorker.schedule(applicationContext)

        setContent {
            MaterialTheme(colorScheme = LightColors) {
                Surface {
                    MainScreen()
                }
            }
        }
    }
}
