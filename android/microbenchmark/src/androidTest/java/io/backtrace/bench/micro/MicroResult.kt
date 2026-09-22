package io.backtrace.bench.micro

import android.content.Context
import android.os.Build
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Collects per-iteration custom samples (bytes written, ...) that Microbenchmark itself does not
 * report and writes them as a bench-result.json 'samples' map (schema/bench-result.schema.json)
 * next to the benchmarkData.json so the shared parser can ingest both.
 */
object MicroResult {
    private const val TAG = "BacktraceBench"
    const val FILE_NAME = "bench-result-micro.json"
    private const val MAX_SAMPLES_PER_METRIC = 1000

    private val samples = LinkedHashMap<String, ArrayDeque<Double>>()
    private val counters = LinkedHashMap<String, Number>()
    private val errors = ArrayList<String>()

    @Synchronized
    fun sample(metric: String, value: Double) {
        val q = samples.getOrPut(metric) { ArrayDeque() }
        if (q.size >= MAX_SAMPLES_PER_METRIC) q.removeFirst()
        q.addLast(value)
    }

    @Synchronized
    fun counter(name: String, value: Number) {
        counters[name] = value
    }

    @Synchronized
    fun error(message: String) {
        errors.add(message)
    }

    /** Directory AGP pulls from the device after the run, else the app-and-shell-readable media dir. */
    fun outputDir(): File {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val arg = InstrumentationRegistry.getArguments().getString("additionalTestOutputDir")
        val candidates = ArrayList<File>()
        if (!arg.isNullOrBlank()) candidates += File(arg)
        instrumentation.context.externalMediaDirs?.filterNotNull()?.let { candidates += it }
        candidates += instrumentation.targetContext.filesDir
        for (dir in candidates) {
            if (dir.isDirectory || dir.mkdirs()) return dir
        }
        return instrumentation.targetContext.filesDir
    }

    @Synchronized
    fun flush(context: Context) {
        val root = JSONObject()
        root.put("schemaVersion", 1)
        root.put("sdk", "android")
        root.put("sdkVersion", BuildConfig.BT_VERSION)
        root.put("source", BuildConfig.BT_SOURCE)
        root.put("variant", BuildConfig.BT_VARIANT)
        root.put("scenario", BuildConfig.BT_SCENARIO)
        root.put("appId", context.packageName)
        root.put("platform", "android")
        root.put("stages", JSONArray())
        root.put("totalMs", 0.0)
        val c = JSONObject()
        counters.forEach { (k, v) -> c.put(k, v) }
        root.put("counters", c)
        if (samples.isNotEmpty()) {
            val s = JSONObject()
            samples.forEach { (k, v) -> s.put(k, JSONArray(v.toList())) }
            root.put("samples", s)
        }
        val device = JSONObject()
        device.put("os", "android")
        device.put("osVersion", Build.VERSION.RELEASE ?: "")
        device.put("sdkInt", Build.VERSION.SDK_INT)
        device.put("model", Build.MODEL ?: "")
        device.put("abi", Build.SUPPORTED_ABIS?.firstOrNull() ?: "")
        device.put("cpuCores", Runtime.getRuntime().availableProcessors())
        root.put("device", device)
        if (errors.isNotEmpty()) root.put("errors", JSONArray(errors))

        val target = File(outputDir(), FILE_NAME)
        try {
            target.writeText(root.toString(2))
            Log.i(TAG, "micro samples written: ${target.absolutePath}")
        } catch (t: Throwable) {
            Log.w(TAG, "micro samples write failed: $t")
        }
    }
}
