package io.backtrace.bench.app;

import android.app.Application;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * Plain anchor: performs exactly the harness work of the SDK app (loopback mock start, attachment
 * fixture, counters, result file) without any SDK call. Stages stay empty and totalMs is 0.
 */
public class BenchApplication extends Application {
    static final long SETTLE_MS = 1500;

    private static MockServer mock;
    private static BenchResult result;

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
        writeAttachmentFixture(this);

        final int tasksBefore = ProcInfo.nativeThreadCount();
        final int javaBefore = ProcInfo.javaThreadCount();

        // No SDK here. Sample counters after the same settle delay as app-sdk and write the file.
        new Handler(Looper.getMainLooper()).postDelayed(() -> finish(tasksBefore, javaBefore), SETTLE_MS);
    }

    private void finish(int tasksBefore, int javaBefore) {
        result.counter("mock_requests", mock.requestCount());
        result.counter("mock_requests_expected", 0);
        result.counter("mock_requests_unexpected", mock.unexpectedCount());
        result.counter("threads_after_init", ProcInfo.nativeThreadCount() - tasksBefore);
        result.counter("threads_java_after_init", ProcInfo.javaThreadCount() - javaBefore);
        result.counter("settle_ms", SETTLE_MS);
        result.write(this, Cell.SDK_VERSION, Cell.SOURCE, Cell.VARIANT, Cell.SCENARIO);
    }

    /** Same 1 KiB file the SDK app registers as an attachment; written here for symmetry. */
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

    /** Requested through MainActivity's crash_native extra; there is no SDK in the plain app. */
    public static void crashNative() {
        Log.w(BenchResult.TAG, "crash_native ignored: plain variant has no SDK");
    }
}
