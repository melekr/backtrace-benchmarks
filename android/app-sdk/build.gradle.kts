// app-sdk: identical to app-plain plus the Backtrace SDK at -PbtVersion and the init sequence in
// BenchApplication/BenchInit. -PbtVariant=sentinel builds the same APK under its own identity.
plugins {
    alias(libs.plugins.android.application)
}

val btVersion = rootProject.extra["bt.version"] as String
val btVariantRaw = rootProject.extra["bt.variant"] as String
val btVariant = if (btVariantRaw == "plain") "sdk" else btVariantRaw // app-sdk never carries the plain identity
val btScenario = rootProject.extra["bt.scenario"] as String
val btSource = rootProject.extra["bt.source"] as String
val btVersionSuffix = rootProject.extra["bt.versionSuffix"] as String
val btFixtureAssets = rootProject.extra["bt.fixtureAssets"] as String?
val btGe313 = rootProject.extra["bt.ge_3_13"] as Boolean
val btGe314 = rootProject.extra["bt.ge_3_14"] as Boolean
val btLibrary = rootProject.extra["bt.libraryCoordinate"] as String

android {
    namespace = "io.backtrace.bench.sdk"
    compileSdk = 36

    defaultConfig {
        // CONVENTIONS section 5: io.backtrace.bench.<variant>.v<version with . and - -> _>
        applicationId = "io.backtrace.bench.$btVariant.$btVersionSuffix"
        minSdk = 21
        targetSdk = 36
        versionCode = 1
        versionName = btVersion
        buildConfigField("String", "BT_VERSION", "\"$btVersion\"")
        buildConfigField("String", "BT_VARIANT", "\"$btVariant\"")
        buildConfigField("String", "BT_SCENARIO", "\"$btScenario\"")
        buildConfigField("String", "BT_SOURCE", "\"$btSource\"")
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        getByName("debug")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            isDebuggable = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        jniLibs { useLegacyPackaging = false }
    }

    sourceSets {
        getByName("main") {
            // Compile-time adapters for public API that changed along the ladder (see README).
            java.srcDir(if (btGe314) "src/bt_ge_3_14/java" else "src/bt_lt_3_14/java")
            java.srcDir(if (btGe313) "src/bt_ge_3_13/java" else "src/bt_lt_3_13/java")
            if (btScenario == "largeapk" && btFixtureAssets != null) {
                assets.srcDir(btFixtureAssets)
            }
        }
    }
}

dependencies {
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.profileinstaller)
    implementation(libs.okhttp.mockwebserver)
    // The only line that differs from app-plain.
    implementation(btLibrary)
}
