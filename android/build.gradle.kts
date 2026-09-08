// ルートでは各プラグインの版だけを宣言し、適用はモジュール側で行う
// AGP 9 は Kotlin を内蔵するため、kotlin.android プラグインは宣言しない
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.compose) apply false
}
