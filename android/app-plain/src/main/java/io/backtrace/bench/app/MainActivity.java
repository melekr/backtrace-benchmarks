package io.backtrace.bench.app;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

/**
 * Single-screen activity. Draws one TextView, reports full draw after the first frame (TTFD) and,
 * on request through intent extras, triggers the crash-path lanes once the launch is complete:
 *   --ez crash_native true   native crash via the SDK (only meaningful in app-sdk)
 *   --ez crash_java true     uncaught Java exception on the main thread
 */
public class MainActivity extends AppCompatActivity {
    private static final long CRASH_DELAY_MS = 2500;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        TextView view = new TextView(this);
        view.setText(Cell.VARIANT + " " + Cell.SDK_VERSION + " " + Cell.SCENARIO);
        setContentView(view);

        final Handler main = new Handler(Looper.getMainLooper());
        // Report full draw from the first pre-draw pass so the frame that renders the content ends after the
        // report (StartupTimingMetric requires a Choreographer frame to end after reportFullyDrawn).
        view.getViewTreeObserver().addOnPreDrawListener(new android.view.ViewTreeObserver.OnPreDrawListener() {
            @Override
            public boolean onPreDraw() {
                view.getViewTreeObserver().removeOnPreDrawListener(this);
                reportFullyDrawn();
                Log.i(BenchResult.TAG, "reportFullyDrawn");
                return true;
            }
        });

        final boolean crashNative = getIntent().getBooleanExtra("crash_native", false);
        final boolean crashJava = getIntent().getBooleanExtra("crash_java", false);
        if (crashNative || crashJava) {
            // Let the bench-result file land first so the launch row is still usable.
            main.postDelayed(() -> {
                if (crashNative) {
                    Log.i(BenchResult.TAG, "crash_native requested t=" + System.currentTimeMillis());
                    BenchApplication.crashNative();
                }
                if (crashJava) {
                    Log.i(BenchResult.TAG, "crash_java requested t=" + System.currentTimeMillis());
                    throw new IllegalStateException("bench: requested uncaught Java exception");
                }
            }, CRASH_DELAY_MS);
        }
    }
}
