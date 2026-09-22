package io.backtrace.bench.micro

import androidx.benchmark.junit4.BenchmarkRule
import androidx.benchmark.junit4.measureRepeated
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import backtraceio.library.BacktraceClient
import org.junit.AfterClass
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * A5: addBreadcrumb latency.
 *  - addBreadcrumb: breadcrumbs enabled, native integration off (timeNs/1e3 -> A5.breadcrumb.add_us)
 *  - addBreadcrumbNative: breadcrumbs enabled after the native handler (-> A5.breadcrumb.add_native_us)
 * Both also record bytes written per 1000 breadcrumbs (A5.breadcrumb.write_bytes_per_1k).
 */
@RunWith(AndroidJUnit4::class)
class BreadcrumbBenchmark {
    @get:Rule
    val benchmarkRule = BenchmarkRule()

    private fun newEnabledClient(dbName: String, native: Boolean): BacktraceClient {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val client = BenchSupport.newClient(context, dbName)
        if (native) {
            val ok = BenchSupport.enableNative(client)
            MicroResult.counter("breadcrumb_native_enabled", if (ok) 1 else 0)
            assumeTrue("native integration unavailable on this device/ABI", ok)
        }
        check(client.enableBreadcrumbs(context)) { "enableBreadcrumbs returned false" }
        return client
    }

    private fun measure(client: BacktraceClient, metricPer1k: String) {
        var i = 0
        benchmarkRule.measureRepeated {
            client.addBreadcrumb("bench crumb " + (i++))
        }
        val before = BenchSupport.writeBytes()
        for (k in 0 until 1000) {
            client.addBreadcrumb("bench crumb bulk $k")
        }
        val after = BenchSupport.writeBytes()
        if (before >= 0 && after >= 0) MicroResult.sample(metricPer1k, (after - before).toDouble())
    }

    @Test
    fun addBreadcrumb() {
        measure(newEnabledClient("bt-micro-crumbs", native = false), "A5.breadcrumb.write_bytes_per_1k")
    }

    @Test
    fun addBreadcrumbNative() {
        measure(newEnabledClient("bt-micro-crumbs-native", native = true), "A5.breadcrumb.write_bytes_per_1k.native")
    }

    companion object {
        @JvmStatic
        @AfterClass
        fun writeSamples() {
            MicroResult.flush(InstrumentationRegistry.getInstrumentation().targetContext)
        }
    }
}
