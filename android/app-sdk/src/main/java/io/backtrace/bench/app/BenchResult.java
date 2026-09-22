package io.backtrace.bench.app;

import android.content.Context;
import android.os.Process;
import android.os.SystemClock;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Builds and writes files/bench-result.json (schema/bench-result.schema.json). One instance per
 * process launch. Stage timings use SystemClock.elapsedRealtimeNanos() on the calling thread.
 */
public final class BenchResult {
    public static final String TAG = "BacktraceBench";
    public static final String FILE_NAME = "bench-result.json";

    public static final class Stage {
        public final String name;
        public final double ms;
        public final String thread;
        public final boolean ok;

        Stage(String name, double ms, String thread, boolean ok) {
            this.name = name;
            this.ms = ms;
            this.thread = thread;
            this.ok = ok;
        }
    }

    private final List<Stage> stages = new ArrayList<>();
    private final List<String> errors = new ArrayList<>();
    private final Map<String, Number> counters = new LinkedHashMap<>();
    private final Map<String, List<Double>> samples = new LinkedHashMap<>();
    private final String startedAt = isoNow();
    private long firstCallNanos = -1;
    private long lastEndNanos = -1;

    /** Runs one timed stage; a thrown exception marks the stage ok=false and is recorded in errors. */
    public boolean stage(String name, StageBody body) {
        android.os.Trace.beginSection("bt.init." + name);
        long t0 = SystemClock.elapsedRealtimeNanos();
        if (firstCallNanos < 0) {
            firstCallNanos = t0;
        }
        boolean ok;
        try {
            ok = body.run();
        } catch (Throwable t) {
            ok = false;
            errors.add(name + ": " + t.getClass().getName() + ": " + t.getMessage());
            Log.w(TAG, "stage " + name + " failed", t);
        } finally {
            android.os.Trace.endSection();
        }
        long t1 = SystemClock.elapsedRealtimeNanos();
        lastEndNanos = t1;
        stages.add(new Stage(name, (t1 - t0) / 1_000_000.0, Thread.currentThread().getName(), ok));
        return ok;
    }

    public interface StageBody {
        /** @return false to flag the stage as failed without throwing */
        boolean run() throws Exception;
    }

    public void counter(String name, Number value) {
        counters.put(name, value);
    }

    public void sample(String metric, double value) {
        List<Double> list = samples.get(metric);
        if (list == null) {
            list = new ArrayList<>();
            samples.put(metric, list);
        }
        list.add(value);
    }

    public void error(String message) {
        errors.add(message);
    }

    public double totalMs() {
        if (firstCallNanos < 0 || lastEndNanos < 0) {
            return 0.0;
        }
        return (lastEndNanos - firstCallNanos) / 1_000_000.0;
    }

    public boolean allStagesOk() {
        for (Stage s : stages) {
            if (!s.ok) {
                return false;
            }
        }
        return true;
    }

    public JSONObject toJson(Context ctx, String sdkVersion, String source, String variant, String scenario) throws JSONException {
        JSONObject root = new JSONObject();
        root.put("schemaVersion", 1);
        root.put("sdk", "android");
        root.put("sdkVersion", sdkVersion);
        root.put("source", source);
        root.put("variant", variant);
        root.put("scenario", scenario);
        root.put("appId", ctx.getPackageName());
        root.put("platform", "android");

        JSONObject process = new JSONObject();
        process.put("pid", Process.myPid());
        process.put("startedAt", startedAt);
        process.put("coldStart", true);
        root.put("process", process);

        JSONArray st = new JSONArray();
        for (Stage s : stages) {
            JSONObject o = new JSONObject();
            o.put("name", s.name);
            o.put("ms", s.ms);
            o.put("thread", s.thread);
            o.put("ok", s.ok);
            st.put(o);
        }
        root.put("stages", st);
        root.put("totalMs", totalMs());

        JSONObject c = new JSONObject();
        for (Map.Entry<String, Number> e : counters.entrySet()) {
            c.put(e.getKey(), e.getValue());
        }
        root.put("counters", c);

        if (!samples.isEmpty()) {
            JSONObject sm = new JSONObject();
            for (Map.Entry<String, List<Double>> e : samples.entrySet()) {
                JSONArray arr = new JSONArray();
                for (Double d : e.getValue()) {
                    arr.put(d.doubleValue());
                }
                sm.put(e.getKey(), arr);
            }
            root.put("samples", sm);
        }

        root.put("device", ProcInfo.device());

        if (!errors.isEmpty()) {
            JSONArray err = new JSONArray();
            for (String e : errors) {
                err.put(e);
            }
            root.put("errors", err);
        }
        return root;
    }

    /**
     * Writes files/bench-result.json (the location named in CONVENTIONS section 6) and mirrors it to
     * the app's external media directory, which adb can read without run-as on non-debuggable builds.
     */
    public File write(Context ctx, String sdkVersion, String source, String variant, String scenario) {
        File target = new File(ctx.getFilesDir(), FILE_NAME);
        try {
            byte[] bytes = toJson(ctx, sdkVersion, source, variant, scenario).toString(2).getBytes(StandardCharsets.UTF_8);
            writeAtomically(target, bytes);
            File[] media = ctx.getExternalMediaDirs();
            if (media != null && media.length > 0 && media[0] != null) {
                File mirror = new File(media[0], FILE_NAME);
                try {
                    writeAtomically(mirror, bytes);
                } catch (IOException e) {
                    Log.w(TAG, "mirror write failed: " + e.getMessage());
                }
            }
            Log.i(TAG, "bench-result written: " + target.getAbsolutePath() + " totalMs=" + totalMs());
        } catch (IOException | JSONException e) {
            Log.e(TAG, "bench-result write failed", e);
        }
        return target;
    }

    private static void writeAtomically(File target, byte[] bytes) throws IOException {
        File parent = target.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("cannot create " + parent);
        }
        File tmp = new File(parent, target.getName() + ".tmp");
        try (OutputStream out = new FileOutputStream(tmp)) {
            out.write(bytes);
            out.flush();
        }
        if (!tmp.renameTo(target)) {
            throw new IOException("rename failed for " + target);
        }
    }

    private static String isoNow() {
        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        f.setTimeZone(TimeZone.getTimeZone("UTC"));
        return f.format(new Date());
    }
}
