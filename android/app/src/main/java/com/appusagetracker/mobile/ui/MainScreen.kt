package com.appusagetracker.mobile.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Tab
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.sp

private val TABS = listOf("利用状況", "設定")

/** 画面の入れ物。利用状況と設定を切り替える */
@Composable
fun MainScreen() {
    // 画面回転などで選択が戻らないよう保存する
    var selected by rememberSaveable { mutableIntStateOf(0) }

    // Android 15 以降は画面の端まで描画されるため、
    // ステータスバーやジェスチャーバーと重ならないよう余白を取る
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
    ) {
        PrimaryTabRow(
            selectedTabIndex = selected,
            containerColor = MaterialTheme.colorScheme.surface,
        ) {
            TABS.forEachIndexed { index, title ->
                Tab(
                    selected = selected == index,
                    onClick = { selected = index },
                    text = { Text(title, fontSize = 14.sp) },
                )
            }
        }

        when (selected) {
            0 -> DashboardScreen()
            else -> SettingsScreen()
        }
    }
}
