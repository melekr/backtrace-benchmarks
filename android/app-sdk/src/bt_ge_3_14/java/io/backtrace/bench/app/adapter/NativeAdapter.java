package io.backtrace.bench.app.adapter;

import backtraceio.library.BacktraceClient;

/** SDK >= 3.14.0: tryEnableNativeIntegration() returns whether the native handler is up. */
public final class NativeAdapter {
    public static final String API = "tryEnableNativeIntegration";

    private NativeAdapter() {}

    public static boolean enable(BacktraceClient client) {
        return client.tryEnableNativeIntegration();
    }
}
