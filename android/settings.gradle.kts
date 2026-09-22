// Backtrace Android SDK benchmark harness (docs/CONVENTIONS.md section 4 pins the toolchain).
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

// btSource=local consumes an SDK checkout published to the local Maven repository as
// local-SNAPSHOT (CONVENTIONS section 3). mavenLocal() is listed first so that it wins for that
// coordinate, but it is only registered for source=local so retro rows (source=maven) can never be
// satisfied by a locally rebuilt artifact (CONVENTIONS section 1, "published artifacts").
val btSource: String = providers.gradleProperty("btSource").orNull ?: "maven"

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        if (btSource == "local") {
            mavenLocal {
                content { includeGroup("com.github.backtrace-labs.backtrace-android") }
            }
        }
        google()
        mavenCentral()
    }
}

rootProject.name = "backtrace-android-bench"
include(":app-plain", ":app-sdk", ":microbenchmark", ":macrobenchmark")
