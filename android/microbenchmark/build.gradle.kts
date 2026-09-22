// microbenchmark: Jetpack Microbenchmark module (androidx.benchmark 1.4.1). The tests live in
// androidTest and run as connectedReleaseAndroidTest; the test APK must not be debuggable.
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.androidx.benchmark)
}

val btVersion = rootProject.extra["bt.version"] as String
val btVariantRaw = rootProject.extra["bt.variant"] as String
val btVariant = if (btVariantRaw == "plain") "sdk" else btVariantRaw
val btScenario = rootProject.extra["bt.scenario"] as String
val btSource = rootProject.extra["bt.source"] as String
val btLibrary = rootProject.extra["bt.libraryCoordinate"] as String

android {
    namespace = "io.backtrace.bench.micro"
    compileSdk = 36

    defaultConfig {
        minSdk = 24
        testInstrumentationRunner = "androidx.benchmark.junit4.AndroidBenchmarkRunner"
        testInstrumentationRunnerArguments["androidx.benchmark.suppressErrors"] = "EMULATOR,LOW-BATTERY,UNLOCKED,DEBUGGABLE"
        testInstrumentationRunnerArguments["androidx.benchmark.output.enable"] = "true"
        buildConfigField("String", "BT_VERSION", "\"$btVersion\"")
        buildConfigField("String", "BT_VARIANT", "\"$btVariant\"")
        buildConfigField("String", "BT_SCENARIO", "\"$btScenario\"")
        buildConfigField("String", "BT_SOURCE", "\"$btSource\"")
    }

    buildFeatures {
        buildConfig = true
    }

    testBuildType = "release"

    testOptions {
        targetSdk = 36
    }

    buildTypes {
        release {
            isDefault = true
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    androidTestImplementation(libs.androidx.benchmark.junit4)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.rules)
    androidTestImplementation(libs.junit)
    // Same coordinate and version property as app-sdk.
    androidTestImplementation(btLibrary)
}
