package io.backtrace.bench.app.adapter;

import android.content.Context;

import backtraceio.library.BacktraceClient;
import backtraceio.library.enums.BacktraceBreadcrumbLevel;

/**
 * SDK >= 3.13.0: enableBreadcrumbs(Context, BacktraceBreadcrumbLevel). DEBUG is the lowest level,
 * so the amount of recorded work equals the pre-3.13 default (all breadcrumbs) while the newer
 * signature is exercised.
 */
public final class BreadcrumbsAdapter {
    public static final String API = "enableBreadcrumbs(Context, BacktraceBreadcrumbLevel)";

    private BreadcrumbsAdapter() {}

    public static boolean enable(BacktraceClient client, Context context) {
        return client.enableBreadcrumbs(context, BacktraceBreadcrumbLevel.DEBUG);
    }
}
