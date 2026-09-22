package io.backtrace.bench.app;

import android.content.Context;

import java.io.File;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import backtraceio.library.BacktraceClient;
import backtraceio.library.BacktraceDatabase;
import backtraceio.library.enums.database.RetryBehavior;
import backtraceio.library.enums.database.RetryOrder;
import backtraceio.library.logger.BacktraceLogger;
import backtraceio.library.logger.LogLevel;
import backtraceio.library.models.BacktraceExceptionHandler;
import backtraceio.library.models.BacktraceMetricsSettings;
import backtraceio.library.models.database.BacktraceDatabaseSettings;
import io.backtrace.bench.app.adapter.BreadcrumbsAdapter;
import io.backtrace.bench.app.adapter.NativeAdapter;

/**
 * The measured SDK initialisation sequence (stage names from CONVENTIONS section 6). Every stage
 * is wrapped in an android.os.Trace section "bt.init.<stage>" (Macrobenchmark TraceSectionMetric)
 * and timed with SystemClock.elapsedRealtimeNanos() on the calling (main) thread.
 *
 * Only public API that exists on every ladder version is called directly; the two signatures that
 * changed along the ladder go through compile-time adapters selected by build.gradle.kts.
 */
public final class BenchInit {
    /** Requests the mock is expected to receive from a full init: metrics startup unique + summed events. */
    public static final int EXPECTED_MOCK_REQUESTS = 2;

    private BenchInit() {}

    public static BacktraceClient run(Context ctx, MockServer mock, BenchResult result, String scenario, File attachment) {
        // Logger level is a scenario knob, not part of the timed work.
        BacktraceLogger.setLevel("diag".equals(scenario) ? LogLevel.DEBUG : LogLevel.OFF);

        final BenchCredentials creds = new BenchCredentials(mock.submissionUrl(), MockServer.TOKEN);

        // Database settings follow the SDK example app so the timed work matches a typical integration.
        File dbDir = new File(ctx.getFilesDir(), "bt-db-" + scenario);
        if (!dbDir.exists() && !dbDir.mkdirs()) {
            result.error("database dir could not be created: " + dbDir);
        }
        final BacktraceDatabaseSettings dbSettings = new BacktraceDatabaseSettings(dbDir.getAbsolutePath());
        dbSettings.setMaxRecordCount(100);
        dbSettings.setMaxDatabaseSize(1000);
        dbSettings.setRetryBehavior(RetryBehavior.ByInterval);
        dbSettings.setAutoSendMode(true);
        dbSettings.setRetryOrder(RetryOrder.Queue);

        final Map<String, Object> attributes = new HashMap<>();
        attributes.put("bench.variant", Cell.VARIANT);
        attributes.put("bench.scenario", scenario);
        final List<String> attachments = Collections.singletonList(attachment.getAbsolutePath());

        final BacktraceClient[] holder = new BacktraceClient[1];

        result.stage("client", () -> {
            BacktraceDatabase database = new BacktraceDatabase(ctx, dbSettings);
            BacktraceClient client = new BacktraceClient(ctx, creds, database, attributes, attachments);
            BacktraceExceptionHandler.enable(client);
            holder[0] = client;
            return true;
        });
        final BacktraceClient client = holder[0];
        if (client == null) {
            return null;
        }

        result.stage("native", () -> NativeAdapter.enable(client));

        result.stage("metrics", () -> {
            // 0 ms interval disables the periodic flush; the two startup events still go to the mock.
            client.metrics.enable(new BacktraceMetricsSettings(creds, mock.metricsBaseUrl(), 0));
            return true;
        });

        result.stage("anr", () -> {
            client.enableAnr();
            return true;
        });

        result.stage("breadcrumbs", () -> BreadcrumbsAdapter.enable(client, ctx));

        result.counter("adapter_native_ge_3_14", NativeAdapter.API.startsWith("try") ? 1 : 0);
        result.counter("adapter_breadcrumbs_ge_3_13", BreadcrumbsAdapter.API.contains("Level") ? 1 : 0);
        return client;
    }
}
