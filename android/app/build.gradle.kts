plugins {
    alias(libs.plugins.android.application)
    // Kotlin 自体は AGP 9 に内蔵されている。Compose だけは別プラグインが要る
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.appusagetracker.mobile"

    // AGP 9 では compileSdk をブロックで指定する（副バージョン付きAPIに対応するため）
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.appusagetracker.mobile"
        // ACTIVITY_RESUMED / ACTIVITY_PAUSED は API 29 以降
        minSdk = 29
        targetSdk = 37
        versionCode = 9
        versionName = "1.3.0"
    }

    buildTypes {
        release {
            // 個人利用のため難読化は行わない
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
    }
}

// AGP 9 の内蔵 Kotlin では、コンパイラ設定はトップレベルの kotlin ブロックで行う
kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.work.runtime.ktx)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    debugImplementation(libs.androidx.compose.ui.tooling)

    testImplementation(libs.junit)
}
