package io.backtrace.bench.app;

import android.app.Application;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

import backtraceio.library.BacktraceClient;

/**
 * SDK app: same harness work as app-plain (loopback mock, attachment fixture, counters, result
 * file) plus the timed SDK init sequence in BenchInit. The result file is written after a settle
 * delay so asynchronous SDK work (metrics startup events, thread starts) is reflected in counters.
 */
public class BenchApplication extends Application {
    static final long SETTLE_MS = 1500;

    private static MockServer mock;
    private static BenchResult result;
    private static volatile BacktraceClient client;

    @Override
    public void onCreate() {
        super.onCreate();
        result = new BenchResult();
        mock = new MockServer();
        try {
            mock.start();
        } catch (IOException e) {
            result.error("mock: " + e);
        }
        File attachment = writeAttachmentFixture(this);

        final int tasksBefore = ProcInfo.nativeThreadCount();
        final int javaBefore = ProcInfo.javaThreadCount();

        client = BenchInit.run(this, mock, result, Cell.SCENARIO, attachment);

        new Handler(Looper.getMainLooper()).postDelayed(() -> finish(tasksBefore, javaBefore), SETTLE_MS);
    }

    private void finish(int tasksBefore, int javaBefore) {
        result.counter("mock_requests", mock.requestCount());
        result.counter("mock_requests_expected", metricsOk() ? BenchInit.EXPECTED_MOCK_REQUESTS : 0);
        result.counter("mock_requests_unexpected", mock.unexpectedCount());
        result.counter("threads_after_init", ProcInfo.nativeThreadCount() - tasksBefore);
        result.counter("threads_java_after_init", ProcInfo.javaThreadCount() - javaBefore);
        result.counter("settle_ms", SETTLE_MS);
        result.write(this, Cell.SDK_VERSION, Cell.SOURCE, Cell.VARIANT, Cell.SCENARIO);
    }

    private static boolean metricsOk() {
        return result.allStagesOk();
    }

    /** 1 KiB file registered as the SDK attachment; app-plain writes the same file for symmetry. */
    static File writeAttachmentFixture(Application app) {
        File f = new File(app.getFilesDir(), "bench-attachment.txt");
        try (FileOutputStream out = new FileOutputStream(f)) {
            byte[] line = "bench attachment fixture line\n".getBytes(StandardCharsets.UTF_8);
            for (int written = 0; written < 1024; written += line.length) {
                out.write(line);
            }
        } catch (IOException e) {
            Log.w(BenchResult.TAG, "attachment fixture: " + e.getMessage());
        }
        return f;
    }

    /** Requested through MainActivity's crash_native extra (A8 lane). */
    public static void crashNative() {
        BacktraceClient c = client;
        if (c == null) {
            Log.w(BenchResult.TAG, "crash_native ignored: client not initialised");
            return;
        }
        c.nativeCrash();
    }
}
