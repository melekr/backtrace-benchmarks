package io.backtrace.bench.app;

import android.os.Build;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Map;

import org.json.JSONException;
import org.json.JSONObject;

/** Deterministic counters and device facts (CONVENTIONS section 1: "deterministic before statistical"). */
public final class ProcInfo {
    private ProcInfo() {}

    /** Thread name prefix used by the loopback mock; those threads belong to the harness, not the SDK. */
    private static final String HARNESS_THREAD_PREFIX = "MockWebServer";
    private static final String HARNESS_THREAD_PREFIX_2 = "bench-";

    /** Number of kernel tasks of this process (Java + native), excluding harness-owned threads. */
    public static int nativeThreadCount() {
        File[] tasks = new File("/proc/self/task").listFiles();
        if (tasks == null) {
            return -1;
        }
        int n = 0;
        for (File task : tasks) {
            String comm = readTrim(new File(task, "comm"));
            if (comm != null && (comm.startsWith(HARNESS_THREAD_PREFIX) || comm.startsWith(HARNESS_THREAD_PREFIX_2))) {
                continue;
            }
            n++;
        }
        return n;
    }

    /** Number of live Java threads, excluding harness-owned threads. */
    public static int javaThreadCount() {
        int n = 0;
        for (Map.Entry<Thread, StackTraceElement[]> e : Thread.getAllStackTraces().entrySet()) {
            String name = e.getKey().getName();
            if (name.startsWith(HARNESS_THREAD_PREFIX) || name.startsWith(HARNESS_THREAD_PREFIX_2)) {
                continue;
            }
            n++;
        }
        return n;
    }

    /** write_bytes from /proc/self/io, or -1 when unreadable. */
    public static long writeBytes() {
        String io = readTrim(new File("/proc/self/io"));
        if (io == null) {
            return -1;
        }
        for (String line : io.split("\n")) {
            if (line.startsWith("write_bytes:")) {
                try {
                    return Long.parseLong(line.substring("write_bytes:".length()).trim());
                } catch (NumberFormatException ignored) {
                    return -1;
                }
            }
        }
        return -1;
    }

    public static boolean isEmulator() {
        String fp = Build.FINGERPRINT == null ? "" : Build.FINGERPRINT;
        String hw = Build.HARDWARE == null ? "" : Build.HARDWARE;
        String model = Build.MODEL == null ? "" : Build.MODEL;
        String product = Build.PRODUCT == null ? "" : Build.PRODUCT;
        return fp.startsWith("generic") || fp.contains("emulator") || hw.contains("ranchu") || hw.contains("goldfish")
                || model.contains("Emulator") || model.contains("Android SDK built for") || product.contains("sdk_gphone")
                || product.contains("emulator");
    }

    public static JSONObject device() throws JSONException {
        JSONObject d = new JSONObject();
        d.put("os", "android");
        d.put("osVersion", Build.VERSION.RELEASE == null ? "" : Build.VERSION.RELEASE);
        d.put("sdkInt", Build.VERSION.SDK_INT);
        d.put("model", Build.MODEL == null ? "" : Build.MODEL);
        d.put("manufacturer", Build.MANUFACTURER == null ? "" : Build.MANUFACTURER);
        String[] abis = Build.SUPPORTED_ABIS;
        d.put("abi", abis != null && abis.length > 0 ? abis[0] : "");
        d.put("cpuCores", Runtime.getRuntime().availableProcessors());
        d.put("isEmulator", isEmulator());
        return d;
    }

    private static String readTrim(File f) {
        try {
            return new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8).trim();
        } catch (IOException | RuntimeException e) {
            return null;
        }
    }
}
