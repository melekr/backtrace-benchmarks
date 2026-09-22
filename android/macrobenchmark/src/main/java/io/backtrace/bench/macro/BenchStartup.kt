package io.backtrace.bench.macro

import android.util.Log
import androidx.benchmark.macro.CompilationMode
import androidx.benchmark.macro.ExperimentalMetricApi
import androidx.benchmark.macro.Metric
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.StartupTimingMetric
import androidx.benchmark.macro.TraceSectionMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.LargeTest
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.AfterClass
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * A1/A2: cold start of the package named by instrumentation argument bt.package.
 *   timeToInitialDisplayMs / timeToFullDisplayMs      -> A2.ttid / A2.ttfd
 *   bt.init.<stage>SumMs (client, native, metrics, anr, breadcrumbs) -> A1.init.<stage>
 *   bt.init.%SumMs (all stages)                        -> A1.init.total
 * Iterations: bt.iterations (default 15). CompilationMode.Full, StartupMode.COLD, pressHome() setup.
 */
@LargeTest
@RunWith(AndroidJUnit4::class)
class BenchStartup {
    @get:Rule
    val benchmarkRule = MacrobenchmarkRule()

    @OptIn(ExperimentalMetricApi::class)
    @Test
    fun coldStartup() {
        val args = InstrumentationRegistry.getArguments()
        val packageName = args.getString("bt.package")
            ?: error("instrumentation argument bt.package is required (io.backtrace.bench.<variant>.v<version>)")
        val iterations = args.getString("bt.iterations")?.toIntOrNull() ?: DEFAULT_ITERATIONS

        val metrics = ArrayList<Metric>()
        metrics += StartupTimingMetric()
        for (stage in STAGES) {
            metrics += TraceSectionMetric("bt.init.$stage", TraceSectionMetric.Mode.Sum)
        }
        metrics += TraceSectionMetric("bt.init.%", TraceSectionMetric.Mode.Sum)

        Log.i(TAG, "coldStartup package=$packageName iterations=$iterations")
        benchmarkRule.measureRepeated(
            packageName = packageName,
            metrics = metrics,
            compilationMode = CompilationMode.Full(),
            startupMode = StartupMode.COLD,
            iterations = iterations,
            setupBlock = { pressHome() },
        ) {
            startActivityAndWait()
        }
    }

    companion object {
        private const val TAG = "BacktraceBench"
        private const val DATA_TAG = "BacktraceBenchData"
        private const val CHUNK = 2000
        private const val DEFAULT_ITERATIONS = 15
        private val STAGES = listOf("client", "native", "metrics", "anr", "breadcrumbs")

        /**
         * Device farms often return only the device log. Echo every *-benchmarkData.json the
         * library wrote as "[i/n]<chunk>" lines so android/scripts/logcat_chunks_to_json.py can
         * rebuild the file from logcat.
         */
        @JvmStatic
        @AfterClass
        fun echoBenchmarkData() {
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            val dirs = ArrayList<File>()
            InstrumentationRegistry.getArguments().getString("additionalTestOutputDir")?.let { dirs += File(it) }
            instrumentation.context.externalMediaDirs?.filterNotNull()?.let { dirs += it }
            val files = dirs.filter { it.isDirectory }
                .flatMap { dir -> dir.walkTopDown().filter { it.isFile && it.name.endsWith("-benchmarkData.json") }.toList() }
                .distinctBy { it.absolutePath }
            if (files.isEmpty()) {
                Log.w(TAG, "no benchmarkData.json found under ${dirs.joinToString()}")
                return
            }
            for (file in files) {
                val compact = file.readText().replace(Regex("\\s+"), "")
                val n = (compact.length + CHUNK - 1) / CHUNK
                Log.i(TAG, "echoing ${file.absolutePath} (${compact.length} chars, $n chunks)")
                for (i in 0 until n) {
                    val chunk = compact.substring(i * CHUNK, minOf(compact.length, (i + 1) * CHUNK))
                    Log.i(DATA_TAG, "[${i + 1}/$n]$chunk")
                }
            }
        }
    }
}
