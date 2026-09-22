package io.backtrace.bench.micro

import android.content.Context
import backtraceio.library.BacktraceClient
import backtraceio.library.BacktraceCredentials
import backtraceio.library.BacktraceDatabase
import backtraceio.library.enums.database.RetryBehavior
import backtraceio.library.enums.database.RetryOrder
import backtraceio.library.logger.BacktraceLogger
import backtraceio.library.logger.LogLevel
import backtraceio.library.models.database.BacktraceDatabaseSettings
import java.io.File

/** Shared client construction for the micro lanes. HTTP is never used: send() goes through setOnRequestHandler. */
object BenchSupport {
    /** Fixed placeholder token (64 hex chars) required by the SDK's URL parsing; not a secret. */
    const val TOKEN = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    /** Loopback URL on a port nothing listens on; the request handler stub short-circuits before any socket. */
    const val SUBMISSION_URL = "http://127.0.0.1:1/post?format=json&token=$TOKEN"

    class BenchCredentials(url: String) : BacktraceCredentials(url) {
        override fun getUniverseName(): String = "bench"
        override fun getSubmissionToken(): String = TOKEN
    }

    fun newClient(context: Context, dbName: String): BacktraceClient {
        BacktraceLogger.setLevel(LogLevel.OFF)
        val dir = File(context.filesDir, dbName)
        dir.deleteRecursively()
        check(dir.mkdirs() || dir.isDirectory) { "cannot create $dir" }
        val settings = BacktraceDatabaseSettings(dir.absolutePath)
        settings.setMaxRecordCount(100)
        settings.setMaxDatabaseSize(1000)
        settings.setRetryBehavior(RetryBehavior.NoRetry)
        settings.setAutoSendMode(false)
        settings.setRetryOrder(RetryOrder.Queue)
        val attributes = hashMapOf<String, Any>("bench.lane" to "micro")
        return BacktraceClient(context, BenchCredentials(SUBMISSION_URL), BacktraceDatabase(context, settings), attributes, emptyList())
    }

    /**
     * Enables the native crash handler through whichever public method the SDK version offers
     * (tryEnableNativeIntegration since 3.14.0, enableNativeIntegration before). Not timed.
     */
    fun enableNative(client: BacktraceClient): Boolean {
        return try {
            val tryEnable = client.javaClass.methods.firstOrNull { it.name == "tryEnableNativeIntegration" && it.parameterCount == 0 }
            if (tryEnable != null) {
                tryEnable.invoke(client) as Boolean
            } else {
                client.javaClass.getMethod("enableNativeIntegration").invoke(client)
                true
            }
        } catch (t: Throwable) {
            false
        }
    }

    /** write_bytes from /proc/self/io, or -1 when unreadable. */
    fun writeBytes(): Long {
        return try {
            File("/proc/self/io").readLines().firstOrNull { it.startsWith("write_bytes:") }
                ?.substringAfter(':')?.trim()?.toLong() ?: -1L
        } catch (t: Throwable) {
            -1L
        }
    }
}
