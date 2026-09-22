package io.backtrace.bench.app.adapter;

import android.content.Context;

import backtraceio.library.BacktraceClient;

/** SDK < 3.13.0: only enableBreadcrumbs(Context[, types][, maxBytes]) exists. */
public final class BreadcrumbsAdapter {
    public static final String API = "enableBreadcrumbs(Context)";

    private BreadcrumbsAdapter() {}

    public static boolean enable(BacktraceClient client, Context context) {
        return client.enableBreadcrumbs(context);
    }
}
