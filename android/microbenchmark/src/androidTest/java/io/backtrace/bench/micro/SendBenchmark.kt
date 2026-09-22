package io.backtrace.bench.micro

import androidx.benchmark.junit4.BenchmarkRule
import androidx.benchmark.junit4.measureRepeated
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import backtraceio.library.BacktraceClient
import backtraceio.library.events.OnServerResponseEventListener
import backtraceio.library.events.RequestHandler
import backtraceio.library.models.BacktraceResult
import backtraceio.library.models.types.BacktraceResultStatus
import org.junit.AfterClass
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * A4: send(Exception) with a request-handler stub (no HTTP).
 *  - sendE2E: caller call to OnServerResponseEventListener callback (timeNs -> A4.send.e2e_ms,
 *    allocationCount -> A4.send.alloc_count, /proc/self/io write_bytes delta -> A4.send.write_bytes)
 *  - sendCallerThread: only the time the calling thread is blocked inside send() (A4.send.caller_ms)
 */
@RunWith(AndroidJUnit4::class)
class SendBenchmark {
    @get:Rule
    val benchmarkRule = BenchmarkRule()

    private lateinit var client: BacktraceClient
    private val handled = AtomicInteger()

    @Before
    fun setUp() {
        client = BenchSupport.newClient(ApplicationProvider.getApplicationContext(), "bt-micro-send")
        client.setOnRequestHandler(RequestHandler {
            handled.incrementAndGet()
            BacktraceResult(null, "ok", BacktraceResultStatus.Ok)
        })
    }

    @Test
    fun sendE2E() {
        var before = 0L
        var sends = 0
        benchmarkRule.measureRepeated {
            runWithTimingDisabled { before = BenchSupport.writeBytes() }
            val latch = CountDownLatch(1)
            client.send(RuntimeException("bench send"), OnServerResponseEventListener { latch.countDown() })
            check(latch.await(30, TimeUnit.SECONDS)) { "send callback timed out" }
            runWithTimingDisabled {
                sends++
                val after = BenchSupport.writeBytes()
                if (before >= 0 && after >= 0) MicroResult.sample("A4.send.write_bytes", (after - before).toDouble())
            }
        }
        MicroResult.counter("send_e2e_iterations", sends)
        MicroResult.counter("send_e2e_stub_requests", handled.get())
        if (handled.get() != sends) MicroResult.error("sendE2E: stub saw ${handled.get()} requests for $sends sends")
    }

    @Test
    fun sendCallerThread() {
        benchmarkRule.measureRepeated {
            val latch = CountDownLatch(1)
            client.send(RuntimeException("bench send"), OnServerResponseEventListener { latch.countDown() })
            runWithTimingDisabled { check(latch.await(30, TimeUnit.SECONDS)) { "send callback timed out" } }
        }
    }

    companion object {
        @JvmStatic
        @AfterClass
        fun writeSamples() {
            MicroResult.flush(InstrumentationRegistry.getInstrumentation().targetContext)
        }
    }
}
