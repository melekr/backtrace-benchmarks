package io.backtrace.bench.app.adapter;

import backtraceio.library.BacktraceClient;

/** SDK < 3.14.0: enableNativeIntegration() is void; failures surface as exceptions or log lines. */
public final class NativeAdapter {
    public static final String API = "enableNativeIntegration";

    private NativeAdapter() {}

    public static boolean enable(BacktraceClient client) {
        client.enableNativeIntegration();
        return true;
    }
}
