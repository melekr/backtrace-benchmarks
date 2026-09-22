// Root build script: resolves the benchmark cell (SDK version, variant, scenario, source) from
// Gradle properties once and exposes it to the modules through rootProject.extra.
//
//   -PbtVersion=3.14.0 | local-SNAPSHOT     SDK version under test (default in gradle.properties)
//   -PbtVariant=plain|sdk|sentinel          app identity; only app-sdk reads it
//   -PbtScenario=default|largeapk|diag|seeded-<N>
//   -PbtSource=maven|local                  where backtrace-library is resolved from
//   -PbtFixtureAssets=<dir>                 asset fixture directory for scenario largeapk
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.android.test) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.androidx.benchmark) apply false
}

val btVersion: String = (findProperty("btVersion") as String?)?.trim().takeUnless { it.isNullOrEmpty() } ?: "3.14.0"
val btVariant: String = (findProperty("btVariant") as String?)?.trim().takeUnless { it.isNullOrEmpty() } ?: "sdk"
val btScenario: String = (findProperty("btScenario") as String?)?.trim().takeUnless { it.isNullOrEmpty() } ?: "default"
val btSource: String = (findProperty("btSource") as String?)?.trim().takeUnless { it.isNullOrEmpty() } ?: "maven"
val btFixtureAssets: String? = (findProperty("btFixtureAssets") as String?)?.trim().takeUnless { it.isNullOrEmpty() }

require(btVariant in setOf("plain", "sdk", "sentinel")) { "btVariant must be plain|sdk|sentinel, got '$btVariant'" }
require(btSource in setOf("maven", "local")) { "btSource must be maven|local, got '$btSource'" }

/**
 * Tiny semver comparison used to pick compile-time adapter source sets.
 * "MAJOR.MINOR.PATCH[-prerelease]" is compared on the numeric core only; anything that does not
 * start with a numeric core (e.g. "local-SNAPSHOT", a git sha) is treated as newer than every
 * published release, because HEAD builds always carry the newest public API.
 */
fun semverCore(v: String): List<Int>? {
    val m = Regex("""^(\d+)\.(\d+)(?:\.(\d+))?""").find(v) ?: return null
    return listOf(m.groupValues[1].toInt(), m.groupValues[2].toInt(), m.groupValues[3].ifEmpty { "0" }.toInt())
}

fun compareSemver(a: String, b: String): Int {
    val ca = semverCore(a)
    val cb = semverCore(b)
    if (ca == null && cb == null) return 0
    if (ca == null) return 1
    if (cb == null) return -1
    for (i in 0 until 3) {
        val d = ca[i].compareTo(cb[i])
        if (d != 0) return d
    }
    return 0
}

fun versionAtLeast(version: String, floor: String): Boolean = compareSemver(version, floor) >= 0

val btVersionSuffix = "v" + btVersion.replace('.', '_').replace('-', '_')

extra["bt.version"] = btVersion
extra["bt.variant"] = btVariant
extra["bt.scenario"] = btScenario
extra["bt.source"] = btSource
extra["bt.fixtureAssets"] = btFixtureAssets
extra["bt.versionSuffix"] = btVersionSuffix
extra["bt.ge_3_13"] = versionAtLeast(btVersion, "3.13.0")
extra["bt.ge_3_14"] = versionAtLeast(btVersion, "3.14.0")
extra["bt.libraryCoordinate"] = "com.github.backtrace-labs.backtrace-android:backtrace-library:$btVersion"

if (btScenario == "largeapk" && btFixtureAssets == null) {
    logger.warn("btScenario=largeapk without -PbtFixtureAssets: the APK will NOT contain the 10k-entry fixture (run android/scripts/gen_fixture.py first)")
}

tasks.register("btPrintCell") {
    description = "Prints the resolved benchmark cell (version, variant, scenario, source, adapters)."
    val v = btVersion; val va = btVariant; val sc = btScenario; val so = btSource; val fx = btFixtureAssets
    val ge13 = extra["bt.ge_3_13"]; val ge14 = extra["bt.ge_3_14"]; val suffix = btVersionSuffix
    doLast {
        println("bt.version=$v")
        println("bt.variant=$va")
        println("bt.scenario=$sc")
        println("bt.source=$so")
        println("bt.fixtureAssets=${fx ?: ""}")
        println("bt.versionSuffix=$suffix")
        println("bt.ge_3_13=$ge13")
        println("bt.ge_3_14=$ge14")
    }
}
