// リポジトリの設定はここへ集約する（各モジュールでは指定しない）
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "AppUsageTracker"
include(":app")
