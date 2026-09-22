// app-plain: the no-SDK anchor. Everything here (dependencies, minification, manifest, activity,
// mock server start, result writer) is declared identically in app-sdk so that the only
// difference between the two APKs is the Backtrace SDK and the calls into it.
plugins {
    alias(libs.plugins.android.application)
}

val btVersion = rootProject.extra["bt.version"] as String
val btScenario = rootProject.extra["bt.scenario"] as String
val btSource = rootProject.extra["bt.source"] as String
val btVersionSuffix = rootProject.extra["bt.versionSuffix"] as String
val btFixtureAssets = rootProject.extra["bt.fixtureAssets"] as String?

android {
    namespace = "io.backtrace.bench.plain"
    compileSdk = 36

    defaultConfig {
        // CONVENTIONS section 5: io.backtrace.bench.<variant>.v<version with . and - -> _>
        applicationId = "io.backtrace.bench.plain.$btVersionSuffix"
        minSdk = 21
        targetSdk = 36
        versionCode = 1
        versionName = btVersion
        buildConfigField("String", "BT_VERSION", "\"$btVersion\"")
        buildConfigField("String", "BT_VARIANT", "\"plain\"")
        buildConfigField("String", "BT_SCENARIO", "\"$btScenario\"")
        buildConfigField("String", "BT_SOURCE", "\"$btSource\"")
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        // Release builds are signed with the debug key so they install on emulators without a
        // keystore. Same choice in app-sdk.
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

    if (btScenario == "largeapk" && btFixtureAssets != null) {
        sourceSets.getByName("main").assets.srcDir(btFixtureAssets)
    }
}

dependencies {
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.profileinstaller)
    // The in-process loopback HTTP mock is part of the harness, not the SDK, so both apps ship it.
    implementation(libs.okhttp.mockwebserver)
}
